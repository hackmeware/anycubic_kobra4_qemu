#!/usr/bin/env python3
"""Passive original main→motor USART2 capture decoding; no identity/private RAM extraction."""
import argparse,hashlib,json
from pathlib import Path

def crc16(data):
    crc=0xffff
    for b in data:
        b^=crc&255; b^=(b&15)<<4
        crc=(((b<<8)|(crc>>8))^(b>>4)^(b<<3))&65535
    return crc

def crc8(data):
    crc=0
    for b in data:
        for _ in range(8):
            crc=((crc<<1)^7 if (crc>>7)^(b&1) else crc<<1)&255
            b>>=1
    return crc

def inspect(data):
    frames=[];i=0
    while i+6<=len(data):
        if data[i]!=126 or data[i+3]>58:
            i+=1;continue
        n=data[i+3]+6;frame=data[i:i+n]
        if len(frame)!=n or crc16(frame[:-2])!=int.from_bytes(frame[-2:],'little'):
            i+=1;continue
        item=dict(offset=i,sequence=frame[1],command=frame[2],payload_hex=frame[4:-2].hex(),crc_valid=True)
        if frame[2]==8 and frame[3] in [5,9]:
            t=frame[5:-2]
            item['tmc']=dict(oid=frame[4],address=t[1],register=t[2]&127,write=bool(t[2]&128),crc_valid=crc8(t[:-1])==t[-1])
        frames.append(item);i+=n
    return dict(sha256=hashlib.sha256(data).hexdigest(),size=len(data),frames=frames)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('capture',type=Path);a=p.parse_args()
    print(json.dumps(inspect(a.capture.read_bytes()),indent=2))
