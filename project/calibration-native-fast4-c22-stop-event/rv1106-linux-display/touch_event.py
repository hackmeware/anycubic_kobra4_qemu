#!/usr/bin/env python3
"""Print a guest-shell command injecting one diagnostic touchscreen event."""
import argparse,struct
p=argparse.ArgumentParser();p.add_argument('x',type=int);p.add_argument('y',type=int);p.add_argument('--release',action='store_true');a=p.parse_args()
if not 0<=a.x<480 or not 0<=a.y<320:p.error('Coordinates must be within480x320')
events=[(3,0,a.x),(3,1,a.y),(1,330,0 if a.release else 1),(0,0,0)]
data=b''.join(struct.pack('<IIHHi',0,0,t,c,v) for t,c,v in events)
print("printf '"+''.join('\\%03o'%b for b in data)+"' > /tmp/touch-events")
