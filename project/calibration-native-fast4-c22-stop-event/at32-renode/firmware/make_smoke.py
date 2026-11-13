#!/usr/bin/env python3
"""Build an auditable, toolchain-free Cortex-M Thumb-1 boot smoke image.

Not application firmware: exercises vector boot, actual ARM instruction execution,
USART1 transmit and SRAM writes. The board/model may have other untested blocks.
"""
from pathlib import Path
import struct
BASE = 0x08000000
ENTRY = BASE + 0x100
code = bytearray()
fixups = []
def half(v): code.extend(struct.pack('<H', v))
def literal(rd, value):
    fixups.append((len(code), rd, value))
    half(0)
literal(0, 0x40013800)                 # USART1
literal(1, 0x200c)                     # USART enabled, TX+RX enabled
half(0x60c1)                           # str r1, [r0, #12]
for char in b'AT32 RENODE BOOT OK\r\n':
    half(0x2100 | char)                # movs r1, #char
    half(0x6041)                       # str r1, [r0, #4]
literal(0, 0x20000000)
literal(1, 0x41543332)                 # marker "AT32"
half(0x6001)                           # str r1, [r0]
half(0xe7fe)                           # b .
while len(code) % 4: half(0xbf00)
for off, rd, value in fixups:
    target = ENTRY + len(code)
    pc = (ENTRY + off + 4) & ~3
    delta = target - pc
    assert delta >= 0 and delta % 4 == 0 and delta // 4 < 256
    struct.pack_into('<H', code, off, 0x4800 | rd << 8 | delta // 4)
    code.extend(struct.pack('<I', value))
image = bytearray(0x100)
struct.pack_into('<II', image, 0, 0x20018000, ENTRY | 1)
image.extend(code)
path = Path(__file__).with_name('smoke.bin')
path.write_bytes(image)
print(f'{path}: {len(image)} bytes, reset=0x{ENTRY|1:08x}')
