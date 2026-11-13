"""Read-only verifier. Never starts copied native programs."""
from pathlib import Path
import json,hashlib,ast,os,types
T=Path(__file__).resolve().parent;P=T/'calibration-native-fast4-c22-stop-event';E=T/'sensor_run_check/native-fast4-c22-stop-event';r=json.loads((T/'INSTANCE-PINS.json').read_text());fail=[]
for root,key in [(P,'profile'),(E,'controls')]:
 for rel,h in r[key].items():
  p=root/rel
  if not p.is_file() or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=h:fail.append(key+':'+rel)
runner=P/'rv1106-at32-link/experimental/native-ui-resonance/runner.py';tree=ast.parse(runner.read_text());f=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='environment');fake=types.SimpleNamespace(environ={});g={'os':fake};exec(compile(ast.Module(body=[f],type_ignores=[]),'environment-only','exec'),g)
assert g['environment'](P)['CLOCK_CLIENT']=='scalar';fake.environ['C22_STOP_EVENT_OPT_IN']='1';assert g['environment'](P)['CLOCK_CLIENT']=='stop-event'
assert (E/'launch_c22.sh').read_text().rstrip().endswith('exit 78')
assert json.loads((E/'independent-review/final-review.json').read_text())['passed'] is False
out={'all_present_file_pins_match':not fail,'pin_mismatches':fail,'profile_files_verified':len(r['profile']),'control_files_verified':len(r['controls']),'default_scalar_checked':True,'explicit_stop_event_checked':True,'launch_blocked':True,'missing_historical_inputs':r['missing_historical_inputs'],'complete':False,'native_launched':False}
(T/'VERIFICATION.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2));assert not fail
