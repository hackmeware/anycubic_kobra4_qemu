#!/usr/bin/env python3
"""Toolchain-free Thumb UART RX-poll/echo test image; writes count and received bytes."""
from pathlib import Path
import struct
code=bytearray(); fix=[]; ENTRY=0x08000100
def h(x): code.extend(struct.pack('<H',x))
def lit(r,v): fix.append((len(code),r,v)); h(0)
lit(0,0x40013800); lit(1,0x200c); h(0x60c1)
lit(2,0x20000000); lit(5,0x20000100); h(0x2300)
loop=len(code); h(0x6801); h(0x2420); h(0x4221)
branch=len(code); h(0xd000 | (((loop-(branch+4))//2)&255))
h(0x6841); h(0x54d1); h(0x3301); h(0x602b); h(0x6041)
branch=len(code); h(0xe000 | (((loop-(branch+4))//2)&2047))
while len(code)%4: h(0xbf00)
for off,r,v in fix:
 delta=ENTRY+len(code)-((ENTRY+off+4)&~3)
 struct.pack_into('<H',code,off,0x4800|(r<<8)|(delta//4)); code.extend(struct.pack('<I',v))
image=bytearray(0x100); struct.pack_into('<II',image,0,0x20001000,ENTRY|1); image.extend(code)
Path(__file__).with_name('serial-wire-test.bin').write_bytes(image)
