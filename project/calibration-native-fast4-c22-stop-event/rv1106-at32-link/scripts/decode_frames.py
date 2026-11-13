#!/usr/bin/env python3
"""Find CRC-valid Klipper-shaped frames under observed XOR+rotate wrapper.

This is passive capture analysis, not a wire-protocol implementation. XOR bytes
are recovered independently per candidate from the expected 0x7e terminator;
valid length, sequence destination and CRC are all required. Negotiation bytes
and unmatched bytes are not interpreted. Command IDs require the MCU dictionary.
"""
import argparse,json
from pathlib import Path

def crc16(data):
    crc=0xffff
    for byte in data:
        byte^=crc&255; byte^=(byte&15)<<4
        crc=(((byte<<8)|(crc>>8))^(byte>>4)^(byte<<3))&0xffff
    return crc

def frames(data):
    offset=0
    while offset<len(data):
        found=False
        for size in range(5,min(64,len(data)-offset)+1):
            raw=data[offset:offset+size]
            # Some MCU output is already plain framing; try that before wrapper.
            for key in [None,raw[-1]^0xfc]:
                decoded=raw if key is None else bytes(((x^key)>>1)|(((x^key)&1)<<7) for x in raw)
                if decoded[0]!=size or decoded[1]&0xf0!=0x10 or decoded[-1]!=0x7e: continue
                if crc16(decoded[:-3])!=int.from_bytes(decoded[-3:-1],'big'): continue
                yield {'offset':offset,'length':size,'xor_byte':key,'transform':'plain' if key is None else 'XOR then ROR1','raw_hex':raw.hex(),'decoded_hex':decoded.hex(),'crc_valid':True}
                offset+=size;found=True;break
            if found: break
        if not found:offset+=1

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('capture',type=Path);a=p.parse_args()
    print(json.dumps(list(frames(a.capture.read_bytes())),indent=2))
