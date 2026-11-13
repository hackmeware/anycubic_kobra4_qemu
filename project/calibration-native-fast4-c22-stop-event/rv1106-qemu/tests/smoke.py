#!/usr/bin/env python3
"""Execute ARM code on the real RV1106 machine; no ARM toolchain required."""
import pathlib
import struct
import subprocess
import sys
import tempfile


def mov16(reg, imm, top=False):
    return (0xE3400000 if top else 0xE3000000) | ((imm & 0xF000) << 4) | (reg << 12) | (imm & 0xFFF)


def main():
    qemu = str(pathlib.Path(sys.argv[1]).resolve())
    marker = b"RV1106 ARM/UART smoke OK\r\n"
    # UART2 at ff4c0000. Poll THRE before every byte.
    code = [mov16(0, 0), mov16(0, 0xFF4C, True)]
    for byte in marker:
        code += [0xE5902014, 0xE3120020, 0x0AFFFFFC,
                 0xE3A01000 | byte, 0xE5801000]
    code += [0xEAFFFFFE]
    with tempfile.TemporaryDirectory() as d:
        binary = pathlib.Path(d) / "uart-smoke.bin"
        binary.write_bytes(struct.pack("<%dI" % len(code), *code))
        cmd = [qemu, "-M", "rv1106", "-m", "64M", "-display", "none",
               "-monitor", "none", "-serial", "stdio", "-kernel", str(binary)]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=3)
            out = result.stdout
            err = result.stderr
        except subprocess.TimeoutExpired as e:
            out, err = e.stdout or b"", e.stderr or b""
        if marker not in out:
            raise SystemExit("FAIL: " + repr(out) + " stderr=" + repr(err))
        print("PASS: ARMv7 instructions, firmware load/entry, UART2 TX/LSR")


if __name__ == "__main__":
    main()
