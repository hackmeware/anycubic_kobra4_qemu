#!/usr/bin/env python3
"""Independent UART transport test, not either device's production protocol."""
from pathlib import Path
import struct
ROOT = Path(__file__).resolve().parent

def mov16(reg, imm, top=False):
    return (0xE3400000 if top else 0xE3000000) | ((imm & 0xF000) << 4) | reg << 12 | (imm & 0xFFF)

# ARMv7: send every byte to UART1, await its XOR-0x5A response, compare.
code = [mov16(0,0), mov16(0,0xFF4B,True)]
branches=[]
for byte in range(256):
    code += [0xE5902014,0xE3120020,0x0AFFFFFC,0xE3A01000|byte,0xE5801000]
    code += [0xE5902014,0xE3120001,0x0AFFFFFC,0xE5901000,0xE3510000|(byte^0x5A)]
    branches.append(len(code)); code.append(0)
def print_marker(marker):
    code.extend([mov16(0,0),mov16(0,0xFF4C,True)])
    for byte in marker:
        code.extend([0xE5902014,0xE3120020,0x0AFFFFFC,0xE3A01000|byte,0xE5801000])
    code.append(0xEAFFFFFE)
print_marker(b'PASS: 256 UART round trips, all byte values\r\n')
fail = len(code)
print_marker(b'FAIL: UART response mismatch\r\n')
for i in branches: code[i] = 0x1A000000 | ((fail-i-2)&0xFFFFFF)
(ROOT/'rv1106-test.bin').write_bytes(struct.pack('<%dI'%len(code),*code))

# Cortex-M Thumb: USART1 enabled; poll RX, xor received byte, transmit.
# One outstanding request ensures AT32's real single-byte RX depth is respected.
code=bytearray(); fix=[]
def half(v): code.extend(struct.pack('<H',v))
def literal(rd,val): fix.append((len(code),rd,val)); half(0)
literal(0,0x40013800); literal(1,0x200C); half(0x60C1)
literal(2,0x20); literal(3,0x5A)
half(0x6801) # ldr r1,[r0]
half(0x4211) # tst r1,r2
half(0xD0FC) # beq poll
half(0x6841) # ldr r1,[r0,#4]
half(0x4059) # eors r1,r3
half(0x6041) # str r1,[r0,#4]
half(0xE7F8) # b poll
while len(code)%4: half(0xBF00)
for off,rd,val in fix:
    delta=len(code)-((off+4)&~3)
    struct.pack_into('<H',code,off,0x4800|rd<<8|delta//4)
    code.extend(struct.pack('<I',val))
image=bytearray(0x100);struct.pack_into('<II',image,0,0x20018000,0x08000101);image.extend(code)
(ROOT/'at32-test.bin').write_bytes(image)
print('Generated independent ARMv7 and Cortex-M UART test firmware.')
