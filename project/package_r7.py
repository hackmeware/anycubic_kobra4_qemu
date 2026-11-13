from pathlib import Path
import json,hashlib,zipfile
T=Path(__file__).resolve().parent;W=T.parent;S=W/'c22_stop_event_instance_r5_20261111';old=json.loads((S/'INSTANCE-PINS.json').read_text());new=json.loads((T/'INSTANCE-PINS.json').read_text());changed=[]
for key,sub in [('profile','calibration-native-fast4-c22-stop-event'),('controls','sensor_run_check/native-fast4-c22-stop-event')]:
 for rel,h in old[key].items():assert hashlib.sha256((S/sub/rel).read_bytes()).hexdigest()==h,rel
 for rel,h in new[key].items():
  if old[key].get(rel)!=h:changed.append(T/sub/rel)
files={str(p.relative_to(T/'..')):p for p in []}
for p in changed+[p for p in T.iterdir() if p.is_file()]:files['integration/'+str(p.relative_to(T))]=p
for name in ['c22_jit_repeat_findings_20261111','c22_native_jit_reverse_20261111']:
 for p in (W/name).rglob('*'):
  if p.is_file():files['evidence/'+str(p.relative_to(W))]=p
manifest={'base_full_tree':'libfile_db5b514fd8f881a4aaa87692d3cc3d3b','base_r5_delta':'libfile_ec05c5a7ab6081a4959434062051c422','prior_first_pair_evidence':'libfile_04deed71c92081a4bccd09552073a98d','target_instance':str(T),'changed_source_paths':[str(p.relative_to(T)) for p in changed],'original_r5_unchanged':True,'production_default_changed':False,'native_r7_run_performed':False,'files':{name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in files.items()}}
out=W/'Kobra4-C22-R7-JIT-OptIn-And-Repetition-20261111.zip'
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,strict_timestamps=False) as z:
 for name,p in files.items():z.write(p,name)
 z.writestr('PACKAGE-MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'source_changes':len(changed),'files':len(files),'bytes':out.stat().st_size,'sha256':hashlib.sha256(out.read_bytes()).hexdigest()}))
