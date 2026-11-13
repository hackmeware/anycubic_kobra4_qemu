from pathlib import Path
import json,hashlib,zipfile
T=Path(__file__).resolve().parent;S=T.parent/'c22_stop_event_instance_r3_20261111';old=json.loads((S/'INSTANCE-PINS.json').read_text());new=json.loads((T/'INSTANCE-PINS.json').read_text());changed=[];origin_bad=[]
for key,sub in [('profile','calibration-native-fast4-c22-stop-event'),('controls','sensor_run_check/native-fast4-c22-stop-event')]:
 for rel,h in old[key].items():
  if hashlib.sha256((S/sub/rel).read_bytes()).hexdigest()!=h:origin_bad.append(sub+'/'+rel)
 for rel,h in new[key].items():
  if old[key].get(rel)!=h:changed.append(sub+'/'+rel)
assert not origin_bad
historical=T/'historical/C22-execution-manifest.json';assert historical.read_bytes()==(S/'historical/C22-execution-manifest.json').read_bytes()
files=[T/rel for rel in changed]+[p for p in T.iterdir() if p.is_file() and p.name!='R5-DELTA-MANIFEST.json']+list((T/'offline-review').glob('*.json'))+[historical]
for run in ['r5-offline-scalar','r5-offline-stop-event']:
 files += [p for p in (T/'calibration-native-fast4-c22-stop-event/runs'/run).rglob('*') if p.is_file()]
files=sorted(set(files));manifest={'base_space_file':'libfile_db5b514fd8f881a4aaa87692d3cc3d3b','relative_target_root':T.name,'changed_source_paths':changed,'original_r3_pins_unchanged':True,'historical_manifest_unchanged':True,'native_launch_admitted':False,'native_executed':False,'files':{str(p.relative_to(T)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
(T/'R5-DELTA-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n');files+=[T/'R5-DELTA-MANIFEST.json'];out=T.parent/'Kobra4-C22-Runtime-Integrated-R5-20261111.zip'
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,strict_timestamps=False) as z:
 for p in files:z.write(p,str(p.relative_to(T)))
print(json.dumps({'changed_files':len(changed),'zip_bytes':out.stat().st_size,'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'path':str(out)}))
