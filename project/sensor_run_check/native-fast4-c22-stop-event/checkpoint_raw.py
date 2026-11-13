#!/usr/bin/env python3
"""Finite immutable raw checkpoints. Log tails/prefixes are explicitly partial, never final proof."""
from pathlib import Path
import argparse,hashlib,json,os,stat,time
E=Path(__file__).resolve().parent;W=E.parents[1];P=W/'calibration-native-fast4-c22-stop-event';RUN=P/'runs/native-fast4-86400s-c23';HOST=E/'run-c23'
MAX_SLOTS=145;MAX_TOTAL=16*1024**2;PER_FILE=1024**2
NAMES=('sensor-profile.json','sensor-status.json','sensor-final.json','sensor-final.json.cleanup.json','native-calibration-attempt.json','renode-step.json','virtual-time.json','thermal-profile.json','thermal-profile.json.pending','ui-pid-intent.json','ui-pid-input-outcome.json','console.bin','renode.log','qemu.log','launcher.log','bed-thermal-live.csv','nozzle-thermal-live.csv','physical-state.csv','contact-transitions.csv','final-export.json','startup-abort.json','startup-cleanup.json')
def fsync_directory(path):
 fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:os.fsync(fd)
 finally:os.close(fd)

def atomic_manifest(path, value):
 # A temporary manifest never establishes completion.
 tmp=path.with_name(path.name+'.pending')
 raw=(json.dumps(value,indent=2)+'\n').encode()
 fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 os.replace(tmp,path)
 fsync_directory(path.parent)

def verify_checkpoint(out):
 """Fail closed: committed manifest plus every captured byte must verify."""
 out=Path(out)
 result={'status':'incomplete','resumable_vm_snapshot':False}
 try:
  if out.is_symlink() or (out/'SNAPSHOT.json.pending').exists():return result
  fd=os.open(out/'SNAPSHOT.json',os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
  with os.fdopen(fd,'rb') as f:
   if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):return result
   raw=f.read(1024*1024+1)
  if len(raw)>1024*1024:return result
  def unique_object(pairs):
   obj={}
   for key,value in pairs:
    if key in obj:raise ValueError('Duplicate JSON key')
    obj[key]=value
   return obj
  def invalid_constant(value):raise ValueError('Nonfinite JSON constant')
  report=json.loads(raw,object_pairs_hook=unique_object,parse_constant=invalid_constant)
  if type(report) is not dict or set(report)!={'slot','final_evidence','resumable_vm_snapshot','atomic_cross_file','total_byte_limit','files','captured_bytes','state'}:return result
  if report['state']!='committed':return result
  if any(report[k] is not False for k in ('final_evidence','resumable_vm_snapshot','atomic_cross_file')):return result
  if type(report['slot']) is not int or not 1<=report['slot']<=MAX_SLOTS:return result
  if out.name!=f"checkpoint-{report['slot']:04d}":return result
  if type(report['total_byte_limit']) is not int or report['total_byte_limit']!=MAX_TOTAL:return result
  if type(report['captured_bytes']) is not int or not 0<=report['captured_bytes']<=MAX_TOTAL:return result
  files=report['files']
  if type(files) is not dict or set(files)!=set(NAMES):return result
  total=0
  # Writer budget allocation follows NAMES, independent of JSON object order.
  for name in NAMES:
   v=files[name]
   if type(v) is not dict:return result
   if set(v)=={'missing'} and v['missing'] is True:
    if os.path.lexists(out/name):return result
    continue
   if set(v)!={'bytes_at_open','offset','bytes','complete_file_at_open','sha256'}:return result
   if any(type(v[k]) is not int or not 0<=v[k]<=2**63-1 for k in ('bytes_at_open','offset','bytes')):return result
   size,offset,length=v['bytes_at_open'],v['offset'],v['bytes']
   limit=min(PER_FILE,MAX_TOTAL-total)
   expected_offset=max(0,size-limit) if Path(name).suffix in ('.log','.bin') else 0
   if offset!=expected_offset or length!=min(size-offset,limit):return result
   if type(v['complete_file_at_open']) is not bool or v['complete_file_at_open']!=(offset==0 and length==size):return result
   digest=v['sha256']
   if type(digest) is not str or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):return result
   fd=os.open(out/name,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
   with os.fdopen(fd,'rb') as f:
    if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):return result
    raw=f.read(PER_FILE+1)
   if len(raw)!=length or hashlib.sha256(raw).hexdigest()!=digest:return result
   total+=length
  if total!=report['captured_bytes'] or total>MAX_TOTAL:return result
  result['status']='committed_evidence'
 except (OSError,ValueError,KeyError,TypeError,AttributeError):pass
 return result

def capture(slot):
 if type(slot)is not int or not 1<=slot<=MAX_SLOTS:raise ValueError('Checkpoint slot bound')
 store=E/'raw-checkpoints';store.mkdir(exist_ok=True);fsync_directory(E);out=store/f'checkpoint-{slot:04d}';out.mkdir();fsync_directory(store)
 atomic_manifest(out/'CLAIMED.json',{'slot':slot,'state':'claimed','completion_requires_SNAPSHOT':True})
 report={'slot':slot,'final_evidence':False,'resumable_vm_snapshot':False,'atomic_cross_file':False,'total_byte_limit':MAX_TOTAL,'files':{}};total=0
 for name in NAMES:
  if (HOST/'owner-cancel').exists():raise ValueError('Owner cancelled checkpoint')
  src=RUN/name
  try:fd=os.open(src,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
  except FileNotFoundError:report['files'][name]={'missing':True};continue
  with os.fdopen(fd,'rb') as f:
   st=os.fstat(f.fileno())
   if not stat.S_ISREG(st.st_mode):raise ValueError('Nonregular checkpoint input')
   limit=min(PER_FILE,MAX_TOTAL-total)
   offset=max(0,st.st_size-limit) if src.suffix in ('.log','.bin') else 0
   f.seek(offset);raw=f.read(min(st.st_size-offset,limit));after=os.fstat(f.fileno())
   if after.st_size<st.st_size:raise ValueError('Checkpoint source truncated')
  with (out/name).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  total+=len(raw);report['files'][name]={'bytes_at_open':st.st_size,'offset':offset,'bytes':len(raw),'complete_file_at_open':offset==0 and len(raw)==st.st_size,'sha256':hashlib.sha256(raw).hexdigest()}
 report['captured_bytes']=total
 fsync_directory(out)
 report['state']='committed'
 atomic_manifest(out/'SNAPSHOT.json',report)
 return report
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('slot',type=int);print(json.dumps(capture(a.parse_args().slot),indent=2))
