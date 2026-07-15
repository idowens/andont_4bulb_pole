"""Find the minimum reliable inter-frame hold time for the ANDONT light.

Sweeps a list of hold times (seconds between frames) from longest to shortest.
For each value it runs a running loop; the hold time IS the interval between every
frame, so it's exactly the "active state time" under test. Bypasses AndonLight's
MIN_GAP so the timing is exact. Reliable clear + 1 s pause between tests.

Run:  ./.venv/bin/python gaptest.py
No buzzer.
"""

import time

import serial

from andon import frame, DEFAULT_PORT, BAUD, RED, ORANGE, GREEN, BLUE

LIGHTS = [RED, ORANGE, GREEN, BLUE]      # physical order top -> bottom
TIMES = [0.015, 0.012, 0.010, 0.008, 0.005]
CYCLES = 4
CLEAR_GAP = 0.12                          # known-safe gap for the reset sweep


def clear(s):
    for addr in range(0x00, 0x0B):
        if addr == 0x04:
            continue
        s.write(frame(addr, 0x00))
        s.flush()
        time.sleep(CLEAR_GAP)


def run_loop(s, hold):
    for _ in range(CYCLES):
        for color in LIGHTS:
            s.write(frame(color, 0x01)); s.flush()
            time.sleep(hold)
            s.write(frame(color, 0x00)); s.flush()
            time.sleep(hold)


def main():
    s = serial.Serial(DEFAULT_PORT, BAUD, bytesize=8, parity=serial.PARITY_NONE,
                      stopbits=1, timeout=1)
    try:
        clear(s)
        for hold in TIMES:
            print(f"\n=== hold {int(hold * 1000)} ms  ({CYCLES} cycles) ===")
            run_loop(s, hold)
            clear(s)
            time.sleep(1.0)
        print("\nSweep complete — all off.")
    finally:
        s.close()


if __name__ == "__main__":
    main()
