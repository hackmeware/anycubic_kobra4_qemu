import ast,tempfile,unittest
from pathlib import Path
T=Path(__file__).resolve().parent;E=T/'sensor_run_check/native-fast4-c22-stop-event'
NAMES=['preflight_c22.py','owner_control.py','owner_watch.py','checkpoint_raw.py','audit_final.py','launch_namespace.py','shared-file-ui/shared_ui_client.py','shared-file-ui/shared_ui_client_held_growth.py']
VARS={'ROOT','PROFILE','RUN','EVIDENCE','W','P','E','R','H','S','HOST','CONTROL_ROOT'}
def paths(name,fake):
 tree=ast.parse((E/name).read_text());nodes=[n for n in tree.body if isinstance(n,ast.Assign) and all(isinstance(x,ast.Name) and x.id in VARS for x in n.targets)]
 g={'Path':Path,'__file__':str(fake)};exec(compile(ast.Module(body=nodes,type_ignores=[]),'path-assignments-only','exec'),g)
 return {k:v for k,v in g.items() if k in VARS and isinstance(v,Path)}
class Isolation(unittest.TestCase):
 def test_static_no_old_control_roots(self):
  for name in NAMES:
   for n in ast.walk(ast.parse((E/name).read_text())):
    if isinstance(n,ast.Constant) and isinstance(n.value,str):
     self.assertNotEqual(n.value,'calibration-native-fast4-c22',name)
     self.assertFalse('sensor_run_check/native-fast4-c22/' in n.value,name)
     self.assertFalse(n.value.startswith('/workspace/scratch'),name)
 def test_dynamic_two_dummy_instances(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);old=base/'calibration-native-fast4-c22';old.mkdir();sentinel=old/'untouched';sentinel.write_bytes(b'original')
   for inst in ['one','two']:
    root=base/inst;control=root/'sensor_run_check/native-fast4-c22-stop-event';control.mkdir(parents=True)
    for name in NAMES:
     fake=control/name;fake.parent.mkdir(parents=True,exist_ok=True);fake.write_text('# dummy, never executed\n')
     result=paths(name,fake)
     for k,v in result.items():self.assertTrue(v.is_relative_to(root),(name,k,v))
     prof=result.get('P',result.get('PROFILE'));self.assertEqual(prof,root/'calibration-native-fast4-c22-stop-event')
     if name=='owner_control.py':self.assertEqual(result['E'],control/'run-c23')
     if name.startswith('shared-file-ui'):self.assertEqual(result['EVIDENCE'],control/'shared-file-ui')
     # Exercise file read/write using actual evaluated evidence paths, only in dummy trees.
     evidence=result.get('EVIDENCE',result.get('HOST',result.get('E',control)));evidence.mkdir(parents=True,exist_ok=True);p=evidence/'isolation-probe';p.write_bytes(inst.encode());self.assertEqual(p.read_bytes(),inst.encode())
   self.assertEqual(sentinel.read_bytes(),b'original')
 def test_resource_paths_and_exact_profile_guards(self):
  P=T/'calibration-native-fast4-c22-stop-event'
  rel='rv1106-at32-link/experimental/native-ui-resonance/job_resources.py'
  tree=ast.parse((P/rel).read_text());names={'PROFILE_ROOT','NATIVE_RUN','OWNER_ROOT','EVIDENCE_ROOT','RUNTIME_TMP'}
  nodes=[n for n in tree.body if isinstance(n,ast.Assign) and all(isinstance(x,ast.Name) and x.id in names for x in n.targets)]
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);profile=root/'calibration-native-fast4-c22-stop-event';g={'Path':Path,'__file__':str(profile/rel)}
   exec(compile(ast.Module(body=nodes,type_ignores=[]),'resource-paths-only','exec'),g)
   self.assertEqual(g['OWNER_ROOT'],root/'sensor_run_check/native-fast4-c22-stop-event/run-c23')
   for name in names:self.assertTrue(g[name].is_relative_to(root))
  for rel in ['rv1106-at32-link/scripts/pid_thermal_profile_selection.py','rv1106-at32-link/scripts/native_dual_lis_selection.py','rv1106-at32-link/experimental/native-ui-resonance/prepare_capture_commands.py']:
   constants=[n.value for n in ast.walk(ast.parse((P/rel).read_text())) if isinstance(n,ast.Constant) and isinstance(n.value,str)]
   self.assertNotIn('calibration-native-fast4-c22',constants)
   self.assertIn('calibration-native-fast4-c22-stop-event',constants)
 def test_launcher_closed(self):
  self.assertTrue((E/'launch_c22.sh').read_text().rstrip().endswith('exit 78'))
if __name__=='__main__':unittest.main()
