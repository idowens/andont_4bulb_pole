"""Serial controller for the ANDONT USB andon tower light (CH340).

Protocol (see README.md for the full command reference):

    4-byte frame:  A0  [ADDR]  [STATE]  [CHECKSUM]
    CHECKSUM = (0xA0 + ADDR + STATE) & 0xFF

The buzzer is disabled by default (``allow_buzzer=False``); buzzer commands are
silently dropped unless explicitly enabled. ``all_off`` always silences the
buzzer regardless of that flag.
"""

import time

import serial

DEFAULT_PORT = "/dev/cu.usbserial-110"
BAUD = 9600

# The device drops frames sent back-to-back; enforce a minimum gap between writes.
# Tested clean down to 5 ms hold (near the ~4.2 ms wire floor at 9600 baud);
# 10 ms is a safety margin. Only a zero-gap burst actually drops frames.
MIN_GAP = 0.01

# Channels (ADDR byte)
RED = 0x01
GREEN = 0x02
YELLOW = 0x03
ORANGE = 0x03  # this unit's 2nd lamp reads as orange/amber
BUZZER = 0x04
BLUE = 0x05
WHITE = 0x06

# States (STATE byte)
OFF = 0x00
ON = 0x01
FLASH = 0x12  # hardware blink, ~1 Hz

COLORS = (RED, GREEN, YELLOW, BLUE, WHITE)
COLOR_NAMES = {RED: "red", GREEN: "green", ORANGE: "orange", BLUE: "blue", WHITE: "white"}
NAME_TO_COLOR = {v: k for k, v in COLOR_NAMES.items()}


def frame(addr, state):
    """Return the 4-byte command frame for a channel/state."""
    return bytes([0xA0, addr, state, (0xA0 + addr + state) & 0xFF])


class AndonLight:
    def __init__(self, port=DEFAULT_PORT, baud=BAUD, allow_buzzer=False):
        self.port = port
        self.baud = baud
        self.allow_buzzer = allow_buzzer
        self.ser = None
        self._last_write = 0.0

    def open(self):
        self.ser = serial.Serial(
            self.port,
            self.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1,
        )
        return self

    def close(self):
        if self.ser and self.ser.is_open:
            self.all_off()
            self.ser.close()

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    def _write(self, addr, state):
        # Space frames out; the device drops commands sent back-to-back.
        wait = MIN_GAP - (time.monotonic() - self._last_write)
        if wait > 0:
            time.sleep(wait)
        self.ser.write(frame(addr, state))
        self.ser.flush()
        self._last_write = time.monotonic()

    def _cmd(self, addr, state):
        if addr == BUZZER and not self.allow_buzzer:
            return  # buzzer disabled
        self._write(addr, state)

    def on(self, color):
        self._cmd(color, ON)

    def off(self, color):
        self._cmd(color, OFF)

    def flash(self, color):
        """Hardware blink (~1 Hz) until turned off."""
        self._cmd(color, FLASH)

    def set(self, color, is_on):
        self._cmd(color, ON if is_on else OFF)

    def all_off(self):
        for color in COLORS:
            self._write(color, OFF)
        self._write(BUZZER, OFF)  # silence buzzer even when allow_buzzer is False

    def buzzer(self, state):
        """Buzzer control; no-op unless allow_buzzer=True. state: ON/FLASH/OFF."""
        self._cmd(BUZZER, state)


if __name__ == "__main__":
    # Minimal self-test: blink red once (no buzzer).
    with AndonLight() as light:
        light.on(RED)
        time.sleep(0.5)
        light.off(RED)
    print("andon.py self-test complete (red blink)")
