"""Real selector/generator execution, emulator endpoint replaced by offline preparation only."""
from pathlib import Path
import ast,types,json,subprocess,sys
T=Path(__file__).resolve().parent;P=T/'calibration-native-fast4-c22-stop-event';R=P/'rv1106-at32-link/experimental/native-ui-resonance';D=T/'offline-review';D.mkdir(exist_ok=False)
# Use the actual new scripts; change only their location/terminal endpoint for offline harness.
s=(R/'run_ui_fixture.sh').read_text();lines=s.splitlines();lines[3]='ROOT='+str(P);s='\n'.join(lines)+'\n';old='exec "$ROOT/rv1106-at32-link/scripts/run_combined.sh"';assert old in s;s=s.replace(old,f'exec /bin/sh {D}/run_combined_offline.sh');(D/'fixture_offline.sh').write_text(s)
s=(P/'rv1106-at32-link/scripts/run_combined.sh').read_text();lines=s.splitlines();lines[3]='HERE='+str(P/'rv1106-at32-link');s='\n'.join(lines)+'\n';old='exec python3 "$HERE/scripts/run_link.py"';assert old in s;s=s.replace(old,f'exec python3 {D}/offline_prepare.py');(D/'run_combined_offline.sh').write_text(s)
endpoint='''from pathlib import Path
import sys,json
sys.dont_write_bytecode=True
P=Path(PROFILE)
sys.path.insert(0,str(P/'rv1106-at32-link/scripts'))
import run_link,shared_mcu
a=run_link.parser().parse_args();run_link.execution_args(a)
tmp=a.log_dir/'offline-generated';tmp.mkdir()
result=shared_mcu.prepare(a,tmp,a.mcu_setup_commands.read_text().splitlines(),a.nozzle_setup_commands.read_text().splitlines())
(a.log_dir/'OFFLINE-PREPARED.json').write_text(json.dumps({'native_launched':False,'clock_client':a.clock_client,'result':str(result)},indent=2)+'\\n')
'''.replace('PROFILE',repr(str(P)))
(D/'offline_prepare.py').write_text(endpoint)
def load(file,name,env):
 node=next(n for n in ast.parse((R/file).read_text()).body if isinstance(n,ast.FunctionDef) and n.name==name);g={'os':types.SimpleNamespace(environ=env),'ACTIVE_SECONDS':86368};exec(compile(ast.Module(body=[node],type_ignores=[]),file,'exec'),g);return g[name]
results=[]
for opt,selected in [('0','scalar'),('1','stop-event')]:
 env=load('runner.py','environment',{'C22_STOP_EVENT_OPT_IN':opt})(P)
 env=load('observer.py','fixed_environment',env)(P,str(D/'cache'))
 proc=subprocess.run(['/bin/bash',str(D/'fixture_offline.sh'),'r5-offline-'+selected],env=env,capture_output=True,text=True,timeout=30)
 result={'clock_client':selected,'returncode':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr,'native_launched':False};results.append(result);(D/'results.json').write_text(json.dumps(results,indent=2)+'\n')
 assert proc.returncode==0,result
 output=json.loads((P/('runs/r5-offline-'+selected+'/OFFLINE-PREPARED.json')).read_text());assert output['clock_client']==selected and output['native_launched'] is False
 print(selected,'actual offline preparation OK')
