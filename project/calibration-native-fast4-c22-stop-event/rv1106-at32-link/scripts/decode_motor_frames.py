#!/usr/bin/env python3
"""Validate captured motor bus frames, without interpreting vendor status bits."""
import argparse,json,pathlib,collections

def crc16(data):
 c=65535
 for v in data:
  v^=c&255;v^=(v&15)<<4;c=(((v<<8)|(c>>8))^(v>>4)^(v<<3))&65535
 return c

def decode(data,response):
 frames=[];i=0
 while i<len(data):
  if data[i]!=126:raise ValueError(f'Invalid header at {i}')
  length_index=2 if response else 3
  if i+length_index>=len(data):raise ValueError('Truncated header')
  n=data[i+length_index]+(5 if response else 6);f=data[i:i+n]
  if len(f)!=n:raise ValueError('Truncated frame')
  if crc16(f[:-2])!=int.from_bytes(f[-2:],'little'):raise ValueError(f'CRC mismatch at {i}')
  frames.append({'offset':i,'command':f[1 if response else 2],'payload_hex':f[3 if response else 4:-2].hex(),'frame_hex':f.hex()});i+=n
 return frames
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('capture',type=pathlib.Path);p.add_argument('--response',action='store_true');a=p.parse_args()
 f=decode(a.capture.read_bytes(),a.response)
 print(json.dumps({'frame_count':len(f),'command_counts':dict(collections.Counter(x['command'] for x in f)),'frames':f},indent=2))
