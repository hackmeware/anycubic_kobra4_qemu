#!/usr/bin/env python3
"""qtest regression tests against a compiled RV1106 QEMU machine."""
import pathlib
import subprocess
import sys
import tempfile

qemu = str(pathlib.Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory() as tmp:
    proc = subprocess.Popen([qemu, '-M', 'rv1106', '-m', '64M', '-S',
                             '-display', 'none', '-serial', 'null', '-monitor', 'none',
                             '-qtest', 'stdio', '-qtest-log', tmp + '/qtest.log'],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    try:
        def command(text):
            proc.stdin.write((text + '\n').encode())
            proc.stdin.flush()
            response = proc.stdout.readline().decode().strip()
            assert response.startswith('OK'), (text, response)
            return int(response.split()[1], 0) if ' ' in response else None
        def read(addr): return command('readl %#x' % addr)
        def write(addr, value): return command('writel %#x %#x' % (addr, value))
        assert read(0x1fe000) == 5
        assert read(0x1fe004) == 0x54410001
        assert read(0x1fe014) == 48
        assert read(0x1fe018) == 0x54410052
        assert read(0x1fe01c) == 1
        assert read(0x1fe02c) == 64 * 1024 * 1024
        assert read(0xff4c0014) & 0x60 == 0x60
        assert read(0xff4c007c) == 6
        assert read(0xff3b0004) & 0x400
        write(0xff000004, 0x00ff005a)
        assert read(0xff000004) == 0x5a
        write(0xff000004, 0x000f0003)
        assert read(0xff000004) == 0x53
        write(0xff000508, 0x12345678)
        assert read(0xff000508) == 0x12345678
        write(0xff3b0328, 0x12345678)
        assert read(0xff3b0328) == 0x12345678
        assert read(0xff1f1004) & 0x1f == 4  # 160 GIC IRQs
        assert read(0x1fe0d8) == 0x54410050
        assert read(0x1fe0e0) == 1
        assert read(0xff4480f0) == 0x46bc
        assert read(0xff448014) & 1
        write(0xff448014, 1)
        assert read(0xff448014) == 0
        write(0xff448000, 1)
        assert read(0xff448014) & 1
        # Request produces host entropy; avoid flaky assertions about exact bytes.
        rng_words = [read(0xff448020 + i * 4) for i in range(8)]
        assert len(rng_words) == 8
        write(0xff3c0000, 0x00300030)
        assert read(0xff3c0110) == 1
        assert read(0xff3c0120) == 1023
        write(0xff3c0110, 1)
        assert read(0xff3c0110) == 0
        assert read(0xffa90050) == 1
        write(0xffa90000, 7)
        assert read(0xffa90000) == 0
        write(0xffa9002c, 0x80000041)
        assert read(0xffa9002c) == 0x41
        assert read(0xffa90044) == 0x104
        write(0xffa90044, 0xffffffff)
        assert read(0xffa90044) == 0
        print('PASS: DDR/SERIAL ATAG, UART, PLL/GRF, divider, GIC, TRNG, ADC, MMC no-card')
    finally:
        proc.terminate()
        proc.communicate(timeout=5)
