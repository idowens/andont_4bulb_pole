<div align="center">

```
        .-----.
        | (o) |  red
        |-----|
        | (o) |  orange
        |-----|
        | (o) |  green
        |-----|
        | (o) |  blue
        |-----|
        |#####|
        '--+--'
           |  USB
```

# andont_4bulb_pole

**Serial protocol + natural-language control for ANDONT USB andon tower lights.**

*"flash orange and green alternately for 1 minute, then run an all-color loop at 20ms per lamp"* → the pole does exactly that.

![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey) ![Hardware](https://img.shields.io/badge/hardware-CH340%20serial-green) ![License](https://img.shields.io/badge/license-MIT-blue)

</div>

---

## TL;DR

**The problem:** ANDONT's USB tower lights (TCH-M4F series and friends) are great, cheap hardware — but the serial protocol ships as a screenshot in a product listing and a Windows-only `commassistant.exe`. There's no SDK, no docs, no Linux/macOS story.

**The solution:** This repo documents the full hex protocol (verified against real hardware, including a firmware quirk that silently drops commands), wraps it in a small Python controller, and puts a natural-language web UI on top — type what you want the light to do, an LLM translates it to pattern steps, the pole does it.

| | |
|---|---|
| 📖 **Full protocol reference** | Every hex command for lights, flash, and buzzer — plus the frame-timing quirk the vendor doesn't document |
| 🐍 **Zero-dependency-ish controller** | `andon.py` needs only `pyserial` |
| 🎨 **Pattern engine** | steady / blink / alternate / chase, sliding two-lamp windows, soft overlapping transitions, background execution with preemption |
| 🗣️ **Natural-language control** | FastAPI web app: plain English → Claude → validated JSON steps → light |
| 🔇 **Silent by default** | The buzzer never fires unless you explicitly toggle it on |

---

## 60-second test (no Python required)

Plug the light in and blink it from a shell:

```bash
# macOS — find your port (CH340 driver required)
ls /dev/cu.usbserial*

PORT=/dev/cu.usbserial-110            # adjust to yours
stty -f "$PORT" 9600 cs8 -cstopb -parenb
printf '\xA0\x01\x01\xA2' > "$PORT"   # red ON
sleep 1
printf '\xA0\x01\x00\xA1' > "$PORT"   # red OFF
```

If red blinked, everything below will work.

---

## Protocol reference

### Serial settings

| Setting | Value |
|---|---|
| Chipset | CH340 (USB vendor `0x1A86`) |
| Baud | 9600, 8 data bits, 1 stop bit, no parity (`9600 8N1`) |
| Payload | Raw hex bytes, not ASCII |

### Frame format

Every command is 4 bytes:

```
A0  [ADDR]  [STATE]  [CHECKSUM]      CHECKSUM = (0xA0 + ADDR + STATE) & 0xFF
```

### Channels

| ADDR | Channel | Notes |
|---|---|---|
| `0x01` | Red | |
| `0x02` | Green | |
| `0x03` | Yellow / Orange | vendor says "yellow"; reads orange on the 4-lamp unit |
| `0x04` | Buzzer | |
| `0x05` | Blue | |
| `0x06` | White | if fitted |

On the 4-lamp TCH-M4F the physical stack top→bottom is **red, orange, green, blue** = addresses `01, 03, 02, 05` — note the addressing is *not* in physical order. Commands to channels your unit doesn't have are ignored.

### Light commands

| Color | ON | Flash (~1 Hz) | OFF |
|---|---|---|---|
| Red | `A0 01 01 A2` | `A0 01 12 B3` | `A0 01 00 A1` |
| Green | `A0 02 01 A3` | `A0 02 12 B4` | `A0 02 00 A2` |
| Yellow/Orange | `A0 03 01 A4` | `A0 03 12 B5` | `A0 03 00 A3` |
| Blue | `A0 05 01 A6` | `A0 05 12 B7` | `A0 05 00 A5` |
| White | `A0 06 01 A7` | `A0 06 12 B8` | `A0 06 00 A6` |

### Buzzer commands

| Mode | Command |
|---|---|
| Loud, continuous | `A0 04 01 A5` |
| Loud, intermittent | `A0 04 12 B6` |
| Quiet, continuous | `A0 04 23 C7` |
| Quiet, intermittent | `A0 04 34 D8` |
| OFF | `A0 04 00 A4` |

### ⚠️ The frame-timing quirk

**The device silently drops frames sent truly back-to-back.** A burst of commands flushed in the same millisecond lands only the first one — the classic symptom is a light stuck on that ignores its OFF command. Any real spacing fixes it: the firmware handled a sustained stream at a 5 ms per-frame hold cleanly in testing (near the ~4.2 ms wire time of a 4-byte frame at 9600 baud). The `AndonLight` class enforces a conservative 10 ms minimum gap automatically; if you write to the port by hand, just don't fire frames with zero delay between them.

Other behavior worth knowing:

- Channels are fully independent — there's no combined state word, and turning one lamp on doesn't clear another. Send explicit OFFs.
- Hardware flash rate is fixed at ~1 Hz. For faster or asymmetric blinking, drive ON/OFF yourself (that's what the pattern engine does).

---

## Installation

```bash
git clone https://github.com/idowens/andont_4bulb_pole.git
cd andont_4bulb_pole
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

**Driver:** the light is a CH340 device. macOS ≥ 13 and most Linux kernels ship support; otherwise install the WCH CH340/CH341 driver. It enumerates as `/dev/cu.usbserial-*` (macOS — use the `cu.` node, not `tty.`), `/dev/ttyUSB0` (Linux), or `COMx` (Windows).

**Port:** edit `DEFAULT_PORT` in `andon.py` or pass `port=` to `AndonLight(...)`.

**API key (web app only):** the NL translator calls the Claude API. Put a key in the environment or a `.env` file next to `app.py`:

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
```

The controller and pattern engine work fine without any key.

---

## Usage

### Python controller

```python
from andon import AndonLight, RED, GREEN, BLUE

with AndonLight() as light:      # buzzer disabled unless allow_buzzer=True
    light.on(RED)
    light.flash(GREEN)           # hardware ~1 Hz blink
    light.off(RED)
    light.all_off()              # also runs automatically on exit
```

### Pattern engine

```python
from patterns import PatternRunner

r = PatternRunner()
r.run([
  {"mode": "alternate", "colors": ["orange", "green"], "on_ms": 60, "off_ms": 60,
   "duration_s": 60, "buzzer": False},
  {"mode": "chase", "colors": ["red", "orange", "green", "blue"], "on_ms": 20,
   "off_ms": 0, "duration_s": 3, "buzzer": False, "width": 1, "overlap_ms": 0},
])
r.reset()   # stop + everything off
```

Chase extras: `width: 2` slides a two-lamp window down the pole; `overlap_ms: 15` lights the incoming lamp a few ms before the outgoing drops, so transitions bleed instead of snapping; reverse the color list to chase upward.

### Natural-language web app

```bash
./.venv/bin/uvicorn app:app --port 8321
# open http://localhost:8321
```

Type a command, hit **RUN** (⌘+Enter works). **RESET** kills any pattern and darkens the pole. The speaker icon toggles the buzzer — off by default, and when off, buzzer steps are stripped server-side so the model can't sneak a beep in.

Things it handles well:

```
flash orange and green alternately for 1 minute with 60ms on and 60ms off,
then run an all-color loop for 3 seconds at 20ms per lamp

FAST alternating police lights, alternating patterns every 5 seconds, for 30 seconds

run 5 rainbow loops, each at a different speed, from slow to very fast, 60 seconds total

traffic light cycle for 30 seconds

slow calm green pulse
```

The translator (Claude `claude-sonnet-4-6`, structured output against a strict JSON schema — so the reply is always valid steps, never prose) decomposes compound requests: "changing patterns every 5 seconds for 30 seconds" becomes six genuinely different 5-second phases, including volley effects built from rapid consecutive steps.

---

## Architecture

```
 "police lights, 30s"       HTTP POST /run
 --------------------->  FastAPI (app.py)
                             |
                             v
                     Claude (structured output)
                             |   [{mode, colors, on_ms, ...}, ...]
                             v
                     PatternRunner (patterns.py)   <-- POST /reset preempts
                             |   background thread, cancel-safe
                             v
                     AndonLight (andon.py)
                             |   4-byte frames, >=10ms apart
                             v
                     CH340 serial @ 9600 8N1  --->  tower light
```

## File map

| File | Purpose |
|---|---|
| `andon.py` | Low-level controller: channels, frames, checksums, frame-gap enforcement |
| `patterns.py` | Pattern engine: steady / blink / alternate / chase, threading, preemption |
| `app.py` | FastAPI web app + NL→JSON translation + single-page UI |
| `demo.py` | Scripted visual demo of the pattern vocabulary |
| `calibrate.py` | Clear everything, light one address solo — for mapping your unit's colors |
| `poke.py` | Fire one raw channel/state command |
| `gaptest.py` | Sweep inter-frame hold times to find your unit's timing floor |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| No `usbserial` device appears | Install the WCH CH340 driver; try a data (not charge-only) USB cable |
| Writes hang forever on macOS | You're on `/dev/tty.usbserial-*` — use the `/dev/cu.*` node instead |
| A light sticks on and ignores OFF | You sent frames back-to-back and the device dropped some — space frames ≥10 ms apart (or just use `AndonLight`) |
| Wrong colors light up | Your unit's channel→position map differs — run `calibrate.py 01/02/03/05/06` and label each |
| Web app: "ANTHROPIC_API_KEY not set" | Add the key to `.env` next to `app.py` or export it before starting uvicorn |
| Buzzer never sounds | By design. Toggle the speaker icon in the UI, or pass `allow_buzzer=True` in code |

## Limitations

- Built and verified against the 4-lamp **TCH-M4F-4ABFT-USB**; other ANDONT models share the protocol but channel counts/colors vary — recalibrate.
- The hardware flash/buzzer STATE bytes (`0x12`/`0x23`/`0x34`) are derived from the vendor's published checksums; ON/OFF are verified on hardware. If hardware flash misbehaves on your unit, drive blinking in software (the pattern engine does anyway).
- The web app is a localhost tool — no auth, don't expose it to the internet.
- One device per server process; no multi-pole orchestration.
- NL translation needs network + an Anthropic API key (pennies per command). Everything else is fully offline.

## FAQ

**Can I use this without the AI part?**
Yes — `andon.py` and `patterns.py` are plain Python + pyserial, fully offline.

**Which lights does this work with?**
Any ANDONT USB tower light on the CH340 + `A0`-frame protocol (their USB 3-stack and multi-color families). Channel-to-color mapping varies by model — `calibrate.py` sorts that out in a minute.

**How fast can it switch?**
The firmware kept up with a sustained 5 ms per-frame hold in testing (~62 full 4-lamp chase cycles/second at 8 ms). The controller enforces a 10 ms floor for margin.

**Why is the buzzer off by default?**
Because an accidental 85 dB beep is never the surprise anyone wants. Opt in explicitly per run.

**Does "flash" use the hardware blink?**
`AndonLight.flash()` does (~1 Hz, fixed). The pattern engine's `blink` mode drives ON/OFF itself so any rate works.

**Why Claude for the translation?**
Structured output against a strict JSON schema means the model's reply *is* the validated pattern program — no parsing, no prompt-injection surface into the serial layer. Swap `MODEL` in `app.py` if you want a different tier.

---

## About Contributions

*About Contributions:* Please don't take this the wrong way, but I do not accept outside contributions for any of my projects. I simply don't have the mental bandwidth to review anything, and it's my name on the thing, so I'm responsible for any problems it causes; thus, the risk-reward is highly asymmetric from my perspective. I'd also have to worry about other "stakeholders," which seems unwise for tools I mostly make for myself for free. Feel free to submit issues, and even PRs if you want to illustrate a proposed fix, but know I won't merge them directly. Instead, I'll have Claude or Codex review submissions via `gh` and independently decide whether and how to address them. Bug reports in particular are welcome. Sorry if this offends, but I want to avoid wasted time and hurt feelings. I understand this isn't in sync with the prevailing open-source ethos that seeks community contributions, but it's the only way I can move at this velocity and keep my sanity.
