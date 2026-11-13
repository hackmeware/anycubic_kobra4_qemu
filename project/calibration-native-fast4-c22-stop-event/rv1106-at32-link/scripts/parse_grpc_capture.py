#!/usr/bin/env python3
"""Extract BusyBox od -b output and inspect HTTP2/gRPC response payloads."""
import argparse,pathlib,re,json
p=argparse.ArgumentParser();p.add_argument('console',type=pathlib.Path);a=p.parse_args()
data=bytearray()
for line in a.console.read_text(errors='replace').splitlines():
 if re.fullmatch(r'[0-7]{7,}\s+(?:[0-7]{3}\s*)+',line):
  data.extend(int(x,8) for x in line.split()[1:])
frames=[];i=0
while i+9<=len(data):
 n=int.from_bytes(data[i:i+3],'big');payload=bytes(data[i+9:i+9+n]);typ=data[i+3]
 frame={'type':typ,'flags':data[i+4],'stream':int.from_bytes(data[i+5:i+9],'big'),'payload_hex':payload.hex()}
 if typ==0 and len(payload)>=5:
  frame['grpc_compressed']=payload[0];frame['grpc_length']=int.from_bytes(payload[1:5],'big');frame['protobuf_hex']=payload[5:].hex()
 frames.append(frame);i+=9+n
print(json.dumps({'captured_bytes':len(data),'parsed_bytes':i,'frames':frames},indent=2))
