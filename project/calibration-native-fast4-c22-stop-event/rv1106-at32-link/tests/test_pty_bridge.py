#!/usr/bin/env python3
import os,pathlib,pty,select,sys,time,tty
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
from pty_bridge import PtyBridge
pairs=[pty.openpty(),pty.openpty()]
for pair in pairs:
 for fd in pair:tty.setraw(fd)
b=PtyBridge(*(os.ttyname(pair[1]) for pair in pairs))
try:
 for source,target in [(0,1),(1,0)]:
  payload=bytes(range(256))*8;os.write(pairs[source][0],payload);got=b'';until=time.monotonic()+2
  while len(got)<len(payload) and time.monotonic()<until:
   if select.select([pairs[target][0]],[],[],.1)[0]:got+=os.read(pairs[target][0],4096)
  assert got==payload
 assert b.error is None
 print('PASS: PTY bridge preserves all 256 byte values in both directions')
finally:
 b.close()
 for pair in pairs:
  for fd in pair:os.close(fd)
