from pathlib import Path
import ast,types,json,subprocess
T=Path(__file__).resolve().parent;P=T/'calibration-native-fast4-c22-stop-event';R=P/'rv1106-at32-link/experimental/native-ui-resonance';D=T/'short-harness';D.mkdir(exist_ok=False)
s=(R/'run_ui_fixture.sh').read_text();lines=s.splitlines();lines[3]='ROOT='+str(P);s='\n'.join(lines)+'\n';old='exec "$ROOT/rv1106-at32-link/scripts/run_combined.sh"';assert old in s;s=s.replace(old,f'exec /bin/sh {D}/run_combined_capture.sh');(D/'fixture_capture.sh').write_text(s)
s=(P/'rv1106-at32-link/scripts/run_combined.sh').read_text();lines=s.splitlines();lines[3]='HERE='+str(P/'rv1106-at32-link');s='\n'.join(lines)+'\n';old='exec python3 "$HERE/scripts/run_link.py"';assert old in s;s=s.replace(old,f'exec python3 {D}/capture.py');(D/'run_combined_capture.sh').write_text(s)
(D/'capture.py').write_text('import pathlib,json,sys,os\np=pathlib.Path(__file__).parent\n(p/"captured.json").write_text(json.dumps({"argv":sys.argv[1:],"env":dict(os.environ)},indent=2)+"\\n")\n')
node=next(n for n in ast.parse((R/'runner.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='environment');g={'os':types.SimpleNamespace(environ={})};exec(compile(ast.Module(body=[node],type_ignores=[]),'environment','exec'),g);env=g['environment'](P);env['RUN_SECONDS']='20'
proc=subprocess.run(['/bin/bash',str(D/'fixture_capture.sh'),'native-short-001'],env=env,capture_output=True,text=True,timeout=30);assert proc.returncode==0,proc.stderr
print('Captured actual short native argv without launching an emulator')
