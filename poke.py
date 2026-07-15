"""Set a single channel to a single state, without clearing anything else.

Usage:  ./.venv/bin/python poke.py <addr_hex> <state_hex>
Example: ./.venv/bin/python poke.py 01 01   # channel 0x01 ON
         ./.venv/bin/python poke.py 01 00   # channel 0x01 OFF
         ./.venv/bin/python poke.py off     # turn every channel off

Unlike AndonLight.close(), this does NOT auto-clear on exit, so a light it turns
on stays on. Buzzer (0x04) is refused.
"""

import sys
import serial

from andon import frame, DEFAULT_PORT, BAUD, COLORS, BUZZER


def main():
    s = serial.Serial(DEFAULT_PORT, BAUD, bytesize=serial.EIGHTBITS,
                      parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, timeout=1)
    try:
        if len(sys.argv) == 2 and sys.argv[1].lower() == "off":
            for c in COLORS:
                s.write(frame(c, 0x00))
            s.write(frame(BUZZER, 0x00))
            s.flush()
            print("all channels off")
            return
        addr = int(sys.argv[1], 16)
        state = int(sys.argv[2], 16)
        if addr == BUZZER:
            print("refused: buzzer (0x04) disabled")
            return
        s.write(frame(addr, state))
        s.flush()
        print(f"sent A0 {addr:02X} {state:02X} {(0xA0 + addr + state) & 0xFF:02X}")
    finally:
        s.close()


if __name__ == "__main__":
    main()
