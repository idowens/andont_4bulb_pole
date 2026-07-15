"""Pattern engine for the ANDONT light: runs a list of pattern steps in a
background thread with cancel support.

Step shape (what the NL translator produces):
    {
      "mode": "steady" | "blink" | "alternate" | "chase",
      "colors": ["red", "orange", "green", "blue"],
      "on_ms": 250,        # time lit per phase
      "off_ms": 250,       # time dark per phase (blink/alternate; chase ignores)
      "duration_s": 10.0,  # how long this step runs
      "buzzer": false      # only honored when the runner allows the buzzer
    }

Modes:
    steady    - all listed colors on for duration_s, then off
    blink     - all listed colors flash together (on_ms on / off_ms off)
    alternate - colors take turns: one on at a time, on_ms lit, off_ms dark between
    chase     - a lit window "runs" through the color list, no dark gap.
                Direction comes from color order (reverse the list to chase up).
                Optional: width (lamps lit at once, default 1) and overlap_ms
                (light the incoming lamp before dropping the outgoing one, for
                a softer transition; default 0).
"""

import threading
import time

from andon import AndonLight, BUZZER, ON, OFF, NAME_TO_COLOR

MIN_HOLD_S = 0.005  # tested floor; clamp anything the translator produces below this


def _resolve(names):
    colors = [NAME_TO_COLOR[n] for n in names if n in NAME_TO_COLOR]
    if not colors:
        raise ValueError(f"no valid colors in {names!r}")
    return colors


class PatternRunner:
    """Runs one pattern program at a time; a new run preempts the current one."""

    def __init__(self, port=None):
        self._light_kwargs = {"port": port} if port else {}
        self._thread = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self.status = "idle"  # idle | running

    def run(self, steps, allow_buzzer=False):
        with self._lock:
            self._stop_current()
            self._cancel = threading.Event()
            self._thread = threading.Thread(
                target=self._execute, args=(steps, allow_buzzer, self._cancel), daemon=True
            )
            self.status = "running"
            self._thread.start()

    def reset(self):
        with self._lock:
            self._stop_current()
            # explicit clear so nothing stays latched
            with AndonLight(**self._light_kwargs) as light:
                light.all_off()
            self.status = "idle"

    def _stop_current(self):
        if self._thread and self._thread.is_alive():
            self._cancel.set()
            self._thread.join(timeout=5)

    def _execute(self, steps, allow_buzzer, cancel):
        try:
            with AndonLight(allow_buzzer=allow_buzzer, **self._light_kwargs) as light:
                for step in steps:
                    if cancel.is_set():
                        break
                    self._run_step(light, step, cancel)
                light.all_off()
        finally:
            self.status = "idle"

    def _run_step(self, light, step, cancel):
        mode = step.get("mode", "steady")
        colors = _resolve(step.get("colors", []))
        on_s = max(step.get("on_ms", 250) / 1000.0, MIN_HOLD_S)
        off_s = max(step.get("off_ms", 250) / 1000.0, MIN_HOLD_S)
        duration = float(step.get("duration_s", 5.0))
        buzz = bool(step.get("buzzer", False))
        deadline = time.monotonic() + duration

        if buzz and light.allow_buzzer:
            light.buzzer(ON)

        try:
            if mode == "steady":
                for c in colors:
                    light.on(c)
                self._wait(deadline, cancel)
                for c in colors:
                    light.off(c)

            elif mode == "blink":
                while time.monotonic() < deadline and not cancel.is_set():
                    for c in colors:
                        light.on(c)
                    if self._wait(min(deadline, time.monotonic() + on_s), cancel):
                        break
                    for c in colors:
                        light.off(c)
                    if self._wait(min(deadline, time.monotonic() + off_s), cancel):
                        break
                for c in colors:
                    light.off(c)

            elif mode == "alternate":
                i = 0
                while time.monotonic() < deadline and not cancel.is_set():
                    c = colors[i % len(colors)]
                    light.on(c)
                    if self._wait(min(deadline, time.monotonic() + on_s), cancel):
                        light.off(c)
                        break
                    light.off(c)
                    if off_s and self._wait(min(deadline, time.monotonic() + off_s), cancel):
                        break
                    i += 1

            elif mode == "chase":
                n = len(colors)
                width = max(1, min(int(step.get("width", 1)), max(1, n - 1)))
                overlap_s = max(step.get("overlap_ms", 0), 0) / 1000.0
                overlap_s = min(overlap_s, on_s * 0.8)  # overlap must fit in the hold
                # light the initial window
                for j in range(width):
                    light.on(colors[j % n])
                i = 0
                while time.monotonic() < deadline and not cancel.is_set():
                    incoming = colors[(i + width) % n]
                    outgoing = colors[i % n]
                    if self._wait(min(deadline, time.monotonic() + on_s - overlap_s), cancel):
                        break
                    light.on(incoming)  # bleed: incoming joins before outgoing drops
                    if overlap_s and self._wait(min(deadline, time.monotonic() + overlap_s), cancel):
                        break
                    light.off(outgoing)
                    i += 1
                for c in set(colors):
                    light.off(c)

            else:
                raise ValueError(f"unknown mode {mode!r}")
        finally:
            if buzz and light.allow_buzzer:
                light.buzzer(OFF)

    @staticmethod
    def _wait(until, cancel):
        """Sleep until `until` or cancel; returns True if cancelled."""
        remaining = until - time.monotonic()
        return cancel.wait(remaining) if remaining > 0 else cancel.is_set()
