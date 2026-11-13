#!/usr/bin/env python3
"""Fixed c19 read-only owner poll/checkpoint/cancel; no emulation, input, or source changes."""
from pathlib import Path
import argparse,hashlib,json,os,stat,sys,time,types
CONTROL_ROOT=Path(__file__).resolve().parent;W=CONTROL_ROOT.parents[1];E=CONTROL_ROOT/'run-c23';P=W/'calibration-native-fast4-c22-stop-event';S=P/'rv1106-at32-link/experimental/native-ui-resonance/owner_lease.py'
OWNER_SHA256='033e110607e5a77a4c9d59d0323a4e3ee7000cce7b5c8a7369832104cfd17bf8'
def bounded_regular_bytes(path, limit=1024*1024):
 fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as f:
  if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):raise ValueError('Evidence/source is not a regular file')
  raw=f.read(limit+1)
 if len(raw)>limit:raise ValueError('Evidence/source exceeds limit')
 return raw
source=bounded_regular_bytes(S)
if hashlib.sha256(source).hexdigest()!=OWNER_SHA256:raise ValueError('Owner source identity changed')
m=types.ModuleType('owner');m.__file__=str(S);exec(compile(source,str(S),'exec'),m.__dict__)
p=argparse.ArgumentParser();p.add_argument('action',choices=('poll','checkpoint','cancel'));a=p.parse_args()
if a.action=='cancel':
 try:
  with (E/'owner-cancel').open('x') as f:f.write('Parent requested cancellation.\n');f.flush();os.fsync(f.fileno())
 except FileExistsError:pass
else:
 lease=m.read(E/'owner-lease.json') # The bounded owner_watch is the sole renewing writer.
output={'action':a.action,'heartbeat':m.read(E/'owner-heartbeat.json'),'control_call_launches_native':False,'observed_launch_sentinel':(E/'launch-attempt.started').is_file(),'native_process_execution_inferred':False}
latest=E/'native-fast4-86400s-c23-latest.json'
try:raw=bounded_regular_bytes(latest)
except FileNotFoundError:pass
else:output['latest']=json.loads(raw)
if a.action=='checkpoint':
 folder=E/'owner-checkpoints';folder.mkdir(exist_ok=True)
 m.write(folder/(str(time.monotonic_ns())+'.json'),output)
print(json.dumps(output,indent=2))
