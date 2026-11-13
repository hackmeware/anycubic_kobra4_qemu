#!/usr/bin/env python3
"""Read-only final c9 source/resource preflight; no native execution."""
from pathlib import Path
import hashlib,json,time,types
E=Path(__file__).resolve().parent;W=E.parents[1];P=W/'calibration-native-fast4-c22-stop-event';N='native-fast4-86400s-c23';R=P/'rv1106-at32-link/experimental/native-ui-resonance'
for name,value in json.loads((E/'final-c22-pins.json').read_text()).items():
 if hashlib.sha256((P/name).read_bytes()).hexdigest()!=value:raise ValueError('Changed reviewed source: '+name)
m=types.ModuleType('preflight');m.__file__=str(R/'runner.py');m.__package__='';exec(compile((R/'runner.py').read_bytes(),m.__file__,'exec'),m.__dict__)
c,r,paths=m.plan(P,E/'run-c23',N);start=time.monotonic();m.preflight(c,r,paths)
report={'passed':True,'native_launch_performed':False,'elapsed_seconds':time.monotonic()-start,'configuration':c,'run_still_absent':not r.exists(),'cache_still_absent':not Path(c['python_cache_prefix']).exists()}
with (E/'preflight-c22.json').open('x') as f:json.dump(report,f,indent=2);f.write('\n')
print(json.dumps(report,indent=2))
