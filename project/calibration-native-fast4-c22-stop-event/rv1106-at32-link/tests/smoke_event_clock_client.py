#!/usr/bin/env python3
"""FIFO/client integration against rebuilt QEMU; no disk or printer firmware."""
import argparse,json,os,pathlib,subprocess,sys,tempfile
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
from event_clock_client import EventClockClient
parser=argparse.ArgumentParser();parser.add_argument('binary');parser.add_argument('--icount-shift',type=int,choices=range(11));parser.add_argument('--count',type=int,default=20);a=parser.parse_args()
if not 1<=a.count<=100000:parser.error('count must be1..100000')
binary=str(pathlib.Path(a.binary).resolve())
icount=[] if a.icount_shift is None else ['-icount',f'shift={a.icount_shift},align=off,sleep=off']
with tempfile.TemporaryDirectory() as folder:
 base=pathlib.Path(folder)/'qmp'
 for suffix in ('.in','.out'):os.mkfifo(str(base)+suffix)
 p=subprocess.Popen([binary,'-M','rv1106,virtual-deadline-enabled=on','-m','64M','-S','-display','none','-serial','null','-monitor','none','-qmp',f'pipe:{base}']+icount,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
 q=None
 try:
  q=EventClockClient.from_pipes(base);observed=[]
  for _ in range(a.count):
   target=q.now()+1000000;actual=q.run_until(target);observed.append(actual-target)
   assert 0<=actual-target<=5000000,observed
  print(json.dumps({'result':'EVENT CLOCK CLIENT PASS','icount_shift':a.icount_shift,'samples':len(observed),'maximum_overshoot_ns':max(observed),'overshoot_ns':observed}))
 finally:
  if q:q.close()
  p.terminate()
  try:p.communicate(timeout=5)
  except subprocess.TimeoutExpired:p.kill();p.communicate(timeout=5)
