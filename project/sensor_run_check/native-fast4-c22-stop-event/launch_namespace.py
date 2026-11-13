#!/usr/bin/env python3
"""Fixed c19 private PID namespace around the unchanged bounded long-run owners."""
from contextlib import contextmanager
from pathlib import Path
import fcntl, hashlib, json, os, subprocess, sys, time
E=Path(__file__).resolve().parent
S=E.with_name(E.name+'-supervision')
P=E.parents[1]/'calibration-native-fast4-c22-stop-event'
sys.path.insert(0,str(E/'supervision'))
from pid_namespace_supervisor import NamespaceSupervisor

def write(name,data):
    path=S/name; temporary=path.with_name(path.name+'.tmp')
    with temporary.open('w') as f:
        json.dump(data,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    temporary.replace(path)

@contextmanager
def held_stdin():
    read,writer=os.pipe()
    try:yield read
    finally:
        try:os.close(read)
        finally:os.close(writer)

def main():
    os.umask(0o077)
    if not (E/'run-c23/launch-attempt.started').is_file():raise ValueError('Once-only reviewed sentinel missing')
    review=json.loads((E/'independent-review/final-review.json').read_text())
    for filename,key,root in [('final-c22-pins.json','final_pins_sha256',P),('control-script-pins.json','control_pins_sha256',E)]:
        raw=(E/filename).read_bytes()
        if review.get('passed') is not True or hashlib.sha256(raw).hexdigest()!=review.get(key):raise ValueError('Missing/stale review')
        for name,digest in json.loads(raw).items():
            path=root/name
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Reviewed bytes changed: '+name)
    import types
    admission=types.ModuleType('c19_admission');admission.__file__=str(E/'validate_admission.py')
    exec(compile((E/'validate_admission.py').read_bytes(),admission.__file__,'exec'),admission.__dict__);admission.require(review)
    S.mkdir(mode=0o700,exist_ok=True)
    if S.is_symlink() or S.stat().st_uid!=os.getuid():raise ValueError('Unsafe supervision directory')
    lock=(S/'exclusive.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    started=time.monotonic();owner=None;code=None;error=None;last=0
    try:
        with held_stdin() as stdin, NamespaceSupervisor(S/'namespace-claim.json',{'profile':str(P),'review':review,'synthetic_pid_not_hardware_transferable':True}) as owner:
            process=owner.launch([sys.executable,'-I','-B',str(E/'owner_watch.py')],stdin=stdin)
            while process.poll() is None:
                if owner.cancelled:raise InterruptedError('Namespace owner cancelled')
                now=time.monotonic()
                if now-started>=86490:raise TimeoutError('Namespace absolute cleanup ceiling')
                if now-last>=60:
                    write('namespace-progress.json',{'elapsed_host_seconds':now-started,'sampled_peak_rss_bytes':owner.peak,'private_namespace_verified':owner.verified,'namespace_child_pids_are_not_host_pids':True,'native_completion_claimed':False})
                    last=now
                time.sleep(.025)
            code=process.returncode
    except BaseException as exc:error=type(exc).__name__+': '+str(exc)
    result={'exit_code':code,'error':error,'cleanup_verified':bool(owner and owner.cleanup_verified),'elapsed_host_seconds':time.monotonic()-started,'sampled_peak_rss_bytes':None if owner is None else owner.peak,'private_namespace_verified':bool(owner and owner.verified),'native_completion_claimed':False,'pid_values_hardware_transferable':False}
    write('namespace-result.json',result)
    if owner and owner.cleanup_verified:owner.complete(S/'namespace-result.json')
    print(json.dumps(result,indent=2),flush=True)
    return 0 if code==0 and error is None and result['cleanup_verified'] else 1
if __name__=='__main__':raise SystemExit(main())
