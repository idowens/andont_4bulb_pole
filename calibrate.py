"""Calibration helper: reliably clear ALL channels, then light one address solo.

Usage:  ./.venv/bin/python calibrate.py <addr_hex>
        ./.venv/bin/python calibrate.py off     # just clear everything

Clears by sweeping addresses 0x00-0x0A with a gap between frames (the device
drops frames sent with no gap), so nothing stays latched between probes.
"""

import sys
import time

import serial

from andon import frame, DEFAULT_PORT, BAUD

GAP = 0.12  # seconds between frames; device drops frames sent faster


def clear(s):
    for addr in range(0x00, 0x0B):
        if addr == 0x04:  # skip buzzer
            continue
        s.write(frame(addr, 0x00))
        s.flush()
        time.sleep(GAP)


def main():
    arg = sys.argv[1]
    s = serial.Serial(DEFAULT_PORT, BAUD, bytesize=8, parity=serial.PARITY_NONE,
                      stopbits=1, timeout=1)
    try:
        clear(s)
        if arg.lower() == "off":
            print("cleared")
            return
        addr = int(arg, 16)
        s.write(frame(addr, 0x01))
        s.flush()
        print(f"lit addr {addr:#04x}  (frame A0 {addr:02X} 01 {(0xA0 + addr + 1) & 0xFF:02X})")
    finally:
        s.close()


if __name__ == "__main__":
    main()
