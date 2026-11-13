from pathlib import Path
import json,hashlib,shutil
T=Path(__file__).resolve().parent;oldT=T.parent/'c22_stop_event_instance_20261111';P=T/'calibration-native-fast4-c22-stop-event';E=T/'sensor_run_check/native-fast4-c22-stop-event';R='rv1106-at32-link/experimental/native-ui-resonance/'
cache={}
def sha(p):
 s=p.stat();k=(str(p),s.st_mtime_ns,s.st_size)
 if k not in cache:cache[k]=hashlib.sha256(p.read_bytes()).hexdigest()
 return cache[k]
def dump(p,r):p.write_text(json.dumps(r,indent=2)+'\n')
previous=json.loads((T/'INSTANCE-PINS.json').read_text())
files=[root/rel for root,key in [(P,'profile'),(E,'controls')] for rel in previous[key]];texts=[]
for p in files:
 if p.stat().st_size<2000000:
  try:p.read_text();texts.append(p)
  except UnicodeDecodeError:pass
previous=json.loads((T/'INSTANCE-PINS.json').read_text())
old={p:previous['profile' if p.is_relative_to(P) else 'controls'][str(p.relative_to(P if p.is_relative_to(P) else E))] for p in files}
mfile=P/(R+'execution-manifest.json');m=json.loads(mfile.read_text())
for iteration in range(20):
 replacements={h:sha(p) for p,h in old.items() if sha(p)!=h};old={p:sha(p) for p in files}
 if not replacements:break
 for p in texts:
  if p==mfile:continue
  s=p.read_text();n=s
  for a,b in replacements.items():n=n.replace(a,b)
  if s!=n:p.write_text(n)
 m['files']={k:sha(P/k) if (P/k).is_file() else h for k,h in m['files'].items()};dump(mfile,m)
else:raise RuntimeError('Nonconverging pin graph')
rows=json.loads((T/'INSTANCE-PINS.json').read_text())
for root,key in [(P,'profile'),(E,'controls')]:rows[key]={rel:sha(root/rel) for rel in previous[key]}
rows.update(pin_iterations=iteration,archive_complete=False,native_launch_admitted=False,complete=False,control_isolation_revision=2)
dump(T/'INSTANCE-PINS.json',rows)
# Store historical manifest exactly, outside the mutable candidate profile.
h=T/'historical';h.mkdir(exist_ok=True);source=T.parent/'c22_performance_review_20261111/delta/c22-delta-20261111/overlay/calibration-native-fast4-c22'/R/'execution-manifest.json';shutil.copy2(source,h/'C22-execution-manifest.json');assert sha(source)==sha(h/'C22-execution-manifest.json')
print('Pins converged',iteration,'historical manifest byte-identical; runtime exclusions retained; no admission changes')
