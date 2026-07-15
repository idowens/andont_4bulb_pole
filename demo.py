"""Visual demo for the ANDONT USB andon tower light.

Runs a sequence of light patterns with a 1-second dark pause between each test.
No buzzer at any point.

Run:  ./.venv/bin/python demo.py
"""

import random
import time

from andon import AndonLight, RED, GREEN, ORANGE, BLUE, COLOR_NAMES

# Physical lights on this unit, in stack order top -> bottom (verified 07/15/2026):
#   1 red (0x01), 2 orange (0x03), 3 green (0x02), 4 blue (0x05)
LIGHTS = [RED, ORANGE, GREEN, BLUE]

STEP = 0.25   # seconds per step in the running patterns
PAUSE = 1.0   # dark pause between tests


def banner(title):
    print(f"\n=== {title} ===")


def rest(light):
    """All lights off, then a quiet 1-second pause between tests."""
    light.all_off()
    time.sleep(PAUSE)


def discovery(light):
    """Light each color in turn so the physical color order can be confirmed."""
    banner("Discovery — naming each light (0.6s each)")
    for color in LIGHTS:
        print(f"  -> {COLOR_NAMES[color]}")
        light.on(color)
        time.sleep(0.6)
        light.off(color)
    rest(light)


def running_loop(light, cycles=3):
    banner(f"Running loop — single light, {STEP}s, {cycles} cycles")
    for _ in range(cycles):
        for color in LIGHTS:
            light.on(color)
            time.sleep(STEP)
            light.off(color)
    rest(light)


def up_and_down(light, cycles=2):
    banner(f"Up & back down — ping-pong, {cycles} cycles")
    # up then down, without repeating the endpoints
    sequence = LIGHTS + LIGHTS[-2:0:-1]
    for _ in range(cycles):
        for color in sequence:
            light.on(color)
            time.sleep(STEP)
            light.off(color)
    rest(light)


def random_flash(light, count=12):
    banner(f"Random — {count} random single flashes, {STEP}s each")
    for _ in range(count):
        color = random.choice(LIGHTS)
        light.on(color)
        time.sleep(STEP)
        light.off(color)
    rest(light)


def two_at_once(light):
    banner("Two lights at once — simultaneous pairs")
    pairs = [
        (LIGHTS[0], LIGHTS[-1]),   # ends together
        (LIGHTS[1], LIGHTS[-2]),   # inner pair together
        (LIGHTS[0], LIGHTS[1]),    # adjacent top
        (LIGHTS[-2], LIGHTS[-1]),  # adjacent bottom
    ]
    for a, b in pairs:
        print(f"  -> {COLOR_NAMES[a]} + {COLOR_NAMES[b]}")
        light.on(a)
        light.on(b)
        time.sleep(0.5)
        light.off(a)
        light.off(b)
        time.sleep(STEP)
    rest(light)


def two_light_running_loop(light, cycles=3):
    banner(f"Two-light running loop — sliding pair, {STEP}s, {cycles} cycles")
    for _ in range(cycles):
        for i in range(len(LIGHTS) - 1):
            a, b = LIGHTS[i], LIGHTS[i + 1]
            light.on(a)
            light.on(b)
            time.sleep(STEP)
            light.off(a)
            light.off(b)
    rest(light)


def main():
    with AndonLight() as light:  # buzzer disabled by default
        light.all_off()
        discovery(light)
        running_loop(light)
        up_and_down(light)
        random_flash(light)
        two_at_once(light)
        two_light_running_loop(light)
        print("\nDemo complete — all lights off.")


if __name__ == "__main__":
    main()
