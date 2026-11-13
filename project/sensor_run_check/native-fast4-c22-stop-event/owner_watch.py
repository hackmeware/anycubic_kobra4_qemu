#!/usr/bin/env python3
"""One bounded intentional owner. Never retries launch or restarts an expired owner."""
from pathlib import Path
import hashlib,json,os,signal,subprocess,sys,time,types
E=Path(__file__).resolve().parent;W=E.parents[1];P=W/'calibration-native-fast4-c22-stop-event';H=E/'run-c23';R=P/'rv1106-at32-link/experimental/native-ui-resonance';NAME='native-fast4-86400s-c23'
PYTHON='/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3'
OWNER_SHA256='033e110607e5a77a4c9d59d0323a4e3ee7000cce7b5c8a7369832104cfd17bf8'
def identity(pid):
 text=Path('/proc')/str(pid)/'stat';s=text.read_text();f=s[s.rfind(')')+2:].split();return int(f[19])
def cancel(reason):
 try:
  with (H/'owner-cancel').open('x') as f:f.write(reason+'\n');f.flush();os.fsync(f.fileno())
 except FileExistsError:pass

def finish_worker(worker):
 worker.terminate()
 try:worker.wait(timeout=5)
 except subprocess.TimeoutExpired:
  worker.kill()
  try:worker.wait(timeout=2)
  except subprocess.TimeoutExpired:
   try:
    with (H/'checkpoint-survivor.json').open('x') as f:json.dump({'pid':worker.pid,'outcome':'survivor_not_cleaned'},f)
   except FileExistsError:pass
   return False
 return worker.poll() is not None

def main():
 claim=json.loads((E.with_name(E.name+'-supervision')/'namespace-claim.json').read_text())
 if claim.get('state')!='running' or claim.get('backend')!='pid-namespace' or claim.get('namespace')!=os.readlink('/proc/self/ns/pid') or os.getppid()!=1:raise ValueError('Verified private PID namespace required; never run host-global guards')
 if not (H/'launch-attempt.started').is_file():raise ValueError('Once-only reviewed launch sentinel required')
 review=json.loads((E/'independent-review/final-review.json').read_text())
 for file,key,root in [('final-c22-pins.json','final_pins_sha256',P),('control-script-pins.json','control_pins_sha256',E)]:
  content=(E/file).read_bytes()
  if review.get('passed') is not True or hashlib.sha256(content).hexdigest()!=review.get(key):raise ValueError('Independent review missing/stale')
  for name,expected in json.loads(content).items():
   path=root/name
   if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('Reviewed launch source/control changed')
 import types
 admission=types.ModuleType('c19_admission');admission.__file__=str(E/'validate_admission.py')
 exec(compile((E/'validate_admission.py').read_bytes(),admission.__file__,'exec'),admission.__dict__);admission.require(review)
 with (H/'owner-watch.started').open('x') as claim:claim.write('Exclusive bounded owner claimed. No restart.\n');claim.flush();os.fsync(claim.fileno())
 raw=(R/'owner_lease.py').read_bytes()
 if hashlib.sha256(raw).hexdigest()!=OWNER_SHA256:raise ValueError('Owner lease source changed')
 m=types.ModuleType('owner');m.__file__=str(R/'owner_lease.py');exec(compile(raw,m.__file__,'exec'),m.__dict__)
 began=time.monotonic();child=None;checkpoint=None;checkpoint_began=None;next_raw=0;raw_slot=0;gpio_slot=0;next_renew=0;last_report=0;stop=False;heartbeat_seen=False
 def stop_handler(*_):
  nonlocal stop
  stop=True;cancel('Owner watch interrupted')
 signal.signal(signal.SIGTERM,stop_handler);signal.signal(signal.SIGINT,stop_handler)
 try:
  child=subprocess.Popen([PYTHON,'-I','-B','-X',f'pycache_prefix={H}/{NAME}-python-cache',str(R/'outer_guard.py'),'--profile',str(P),'--evidence-dir',str(H),'--name',NAME])
  start_ticks=identity(child.pid)
  while child.poll() is None:
   elapsed=time.monotonic()-began
   if elapsed>=86400:stop=True;cancel('Absolute24h owner work bound reached')
   if (H/'owner-cancel').exists():stop=True
   if identity(child.pid)!=start_ticks:raise ValueError('Owner process identity changed')
   try:heartbeat=m.read(H/'owner-heartbeat.json')
   except FileNotFoundError:
    if heartbeat_seen or elapsed>300:raise ValueError('Owner heartbeat disappeared or absent after300s')
    heartbeat=None
   if heartbeat:
    heartbeat_seen=True
    stamp=heartbeat.get('monotonic_ns')
    if heartbeat.get('schema')!=1 or type(stamp)is not int or not 0<=time.monotonic_ns()-stamp<=10_000_000_000:raise ValueError('Owner heartbeat malformed or stale')
    if heartbeat.get('owner_pid')!=child.pid:raise ValueError('Heartbeat is not exact launched owner')
    if heartbeat.get('stop_reason') or heartbeat.get('status')!='active' or heartbeat.get('guard_cleanup_signal_sent') is not False:stop=True
    if not stop and time.monotonic()>=next_renew:
     m.renew(H);next_renew=time.monotonic()+30
   if checkpoint is not None and checkpoint.poll() is None and time.monotonic()-checkpoint_began>=180:
    raise TimeoutError('Checkpoint worker exceeded180host seconds')
   if checkpoint is not None and checkpoint.poll() is not None:
    if checkpoint.returncode!=0 and not stop:raise ValueError('Checkpoint failed; inspect checkpoint log')
    checkpoint=None
   if stop and checkpoint is not None:
    if not finish_worker(checkpoint):raise RuntimeError('Checkpoint cleanup failed; survivor retained')
    checkpoint=None
   if not stop and heartbeat and checkpoint is None and (P/'runs'/NAME/'native-calibration-attempt.json').exists():
    command=None
    if elapsed>=next_raw and raw_slot<145:
     raw_slot+=1;command=[PYTHON,'-I','-B',str(E/'checkpoint_raw.py'),str(raw_slot)];next_raw=elapsed+600
    elif gpio_slot<2 and elapsed>=(gpio_slot+1)*28800:
     gpio_slot+=1;command=[PYTHON,'-B',str(R/'checkpoint_run.py'),str(P/'runs'/NAME),str(E/'gpio-checkpoints'),str(R/'gpio-capture-budget.json'),str(gpio_slot)]
    if command:
     with (H/'checkpoint-worker.log').open('ab') as log:checkpoint=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
     checkpoint_began=time.monotonic()
   if time.monotonic()-last_report>=60:
    m.write(H/'owner-watch-progress.json',{'elapsed_seconds':elapsed,'owner_pid':child.pid,'owner_starttime_ticks':start_ticks,'renewal_allowed':not stop,'raw_checkpoint_slots_claimed':raw_slot,'gpio_checkpoint_slots_claimed':gpio_slot,'absolute_work_bound_s':86400,'native_completion_claimed':False});last_report=time.monotonic()
   if elapsed>=86430:raise TimeoutError('Outer owner did not finish within absolute bound plus30s cleanup')
   time.sleep(.2)
  return child.returncode
 except BaseException:
  cancel('Owner watch error; no relaunch')
  if child and child.poll() is None:
   if identity(child.pid)==start_ticks:child.terminate()
   child.wait(timeout=30)
  raise
 finally:
  cleanup_ok=True
  if checkpoint and checkpoint.poll() is None:cleanup_ok=finish_worker(checkpoint)
  cleanup_ok=cleanup_ok and not (H/'checkpoint-survivor.json').exists()
  m.write(H/'owner-watch-final.json',{'owner_exit_code':None if child is None else child.poll(),'elapsed_seconds':time.monotonic()-began,'native_completion_claimed':False,'launched_exactly_once':child is not None,'checkpoint_cleanup_confirmed':cleanup_ok,'owner_process_exited':child is not None and child.poll() is not None})
  if not cleanup_ok:raise RuntimeError('Checkpoint cleanup failed; final evidence is incomplete')
if __name__=='__main__':raise SystemExit(main())
