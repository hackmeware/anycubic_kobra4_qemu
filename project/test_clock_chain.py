"""Execute real shell selection chain in dummy profile; terminal transport is mocked.
Never import/run emulator owner main, firmware, native helper or QEMU/Renode.
"""
import ast,json,os,pathlib,shutil,subprocess,tempfile,types,unittest
T=pathlib.Path(__file__).resolve().parent;P=T/'calibration-native-fast4-c22-stop-event';R=P/'rv1106-at32-link/experimental/native-ui-resonance'
def load_function(path,name,env,**extra):
 tree=ast.parse(path.read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
 g={'os':types.SimpleNamespace(environ=env),**extra};exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),g);return g[name]
def fixture(tmp):
 root=pathlib.Path(tmp)/'calibration-native-fast4-c22-stop-event';r=root/'rv1106-at32-link/experimental/native-ui-resonance';r.mkdir(parents=True)
 s=(R/'run_ui_fixture.sh').read_text();assert str(P) in s;s=s.replace(str(P),str(root));f=r/'run_ui_fixture.sh';f.write_text(s);f.chmod(0o700)
 scripts=root/'rv1106-at32-link/scripts';scripts.mkdir();f=scripts/'run_combined.sh';f.write_bytes((P/'rv1106-at32-link/scripts/run_combined.sh').read_bytes());f.chmod(0o700)
 tests=root/'rv1106-at32-link/tests';tests.mkdir()
 for n in ['assumed-centered-xy-contact.commands','nozzle-ntc-tmc.commands','main-virtual-ntc.commands']:(tests/n).write_text('# dummy\n')
 (root/'build-deps').mkdir();(root/'build-deps/env.sh').write_text(':\n')
 (r/'prepare_capture_commands.py').write_text("import pathlib,sys\np=pathlib.Path(sys.argv[sys.argv.index('--output')+1]);p.mkdir()\nfor n in ['main','nozzle','motor','final']:(p/(n+'-passive.commands')).write_text('')\n")
 for name in ['z_probe_selection.py','pid_thermal_profile_selection.py','native_dual_lis_selection.py','cartridge_thermal_profile_selection.py','thermal_profile_selection.py']:(scripts/name).write_bytes((P/'rv1106-at32-link/scripts'/name).read_bytes())
 (scripts/'thermal-pid-contract').mkdir();(scripts/'thermal-pid-contract/source-pins.json').write_bytes((P/'rv1106-at32-link/scripts/thermal-pid-contract/source-pins.json').read_bytes())
 shutil.copytree(P/'rv1106-at32-link/scripts/native-long-contract',scripts/'native-long-contract')
 source=P/'rv1106-at32-link/scripts/run_link.py';tree=ast.parse(source.read_text());selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ['parser','execution_args','open_deadline_client','renode_host_environment']]
 mock="""import argparse,pathlib,sys,json,types
ROOT=pathlib.Path(__file__).resolve().parents[1]
scalar=type('Scalar',(),{'from_pipes':classmethod(lambda cls,*a,**kw:'scalar')})
stop=type('Stop',(),{})
m=types.ModuleType('event_clock_client');m.EventClockClient=scalar;m.open_clock_pipes=lambda cls,*a,**kw:'stop-event' if cls is stop else 'unexpected';sys.modules[m.__name__]=m
m=types.ModuleType('stop_event_clock');m.StopEventClockClient=stop;sys.modules[m.__name__]=m
"""
 mock += ast.unparse(ast.Module(body=selected,type_ignores=[]))
 mock += "\na=parser().parse_args();value=open_deadline_client(a.clock_client,'unused-mock');(ROOT.parent/'CAPTURE.json').write_text(json.dumps({'selected':value,'clock_client':a.clock_client,'icount':a.qemu_icount_shift,'lockstep':a.clock_lockstep,'host_jit':a.renode_host_jit,'renode_env':renode_host_environment({'KEEP':'same'},a.renode_host_jit)}))\n"
 (scripts/'run_link.py').write_text(mock)
 return root,r/'run_ui_fixture.sh'
class Chain(unittest.TestCase):
 def test_real_shell_chain_default_and_optin(self):
  for opt,expected in [(None,'scalar'),('0','scalar'),('1','stop-event')]:
   with self.subTest(opt=opt),tempfile.TemporaryDirectory() as tmp:
    root,script=fixture(tmp);initial={} if opt is None else {'C22_STOP_EVENT_OPT_IN':opt}
    renv=load_function(R/'runner.py','environment',initial)(root)
    env=load_function(R/'observer.py','fixed_environment',renv,ACTIVE_SECONDS=86368)(root,str(root/'cache'))
    proc=subprocess.run(['/bin/bash',str(script),'offline-selection-only'],env=env,capture_output=True,text=True,timeout=10)
    self.assertEqual(proc.returncode,0,proc.stderr + ((root/'runs/offline-selection-only/launcher.log').read_text() if (root/'runs/offline-selection-only/launcher.log').exists() else ''))
    got=json.loads((root/'CAPTURE.json').read_text());self.assertEqual(got,{'selected':expected,'clock_client':expected,'icount':0,'lockstep':True,'host_jit':'default','renode_env':{'KEEP':'same'}})
 def test_host_jit_entire_selection_chain(self):
  for clock in ['0','1']:
   for host in ['default','single-tier']:
    with self.subTest(clock=clock,host=host),tempfile.TemporaryDirectory() as tmp:
     root,script=fixture(tmp)
     renv=load_function(R/'runner.py','environment',{'C22_STOP_EVENT_OPT_IN':clock,'RENODE_HOST_JIT':host})(root)
     env=load_function(R/'observer.py','fixed_environment',renv,ACTIVE_SECONDS=86368)(root,str(root/'cache'))
     proc=subprocess.run(['/bin/bash',str(script),'host-selection'],env=env,capture_output=True,text=True,timeout=10)
     self.assertEqual(proc.returncode,0,proc.stderr)
     got=json.loads((root/'CAPTURE.json').read_text());self.assertEqual(got['host_jit'],host)
     self.assertEqual(got['selected'],'scalar' if clock=='0' else 'stop-event')
     self.assertEqual(got['icount'],0);self.assertTrue(got['lockstep'])
     self.assertEqual(got['renode_env'],{'KEEP':'same',**({'DOTNET_TieredCompilation':'0'} if host=='single-tier' else {})})
 def test_host_jit_bad_values_fail_before_run(self):
  for host in ['', '0','off','unknown']:
   for file,name,args in [('runner.py','environment',(P,)),('observer.py','fixed_environment',(P,'unused'))]:
    with self.assertRaises(ValueError):load_function(R/file,name,{'RENODE_HOST_JIT':host},ACTIVE_SECONDS=86368)(*args)
   with tempfile.TemporaryDirectory() as tmp:
    root,script=fixture(tmp);proc=subprocess.run(['/bin/bash',str(script),'reject-host'],env={'PATH':'/usr/bin:/bin','RENODE_HOST_JIT':host},capture_output=True,timeout=10)
    self.assertNotEqual(proc.returncode,0);self.assertFalse((root/'runs').exists())
 def test_child_environment_isolated_and_conflicts_rejected(self):
  f=load_function(P/'rv1106-at32-link/scripts/run_link.py','renode_host_environment',{})
  env={'KEEP':'same'};self.assertEqual(f(env,'single-tier'),{'KEEP':'same','DOTNET_TieredCompilation':'0'});self.assertEqual(env,{'KEEP':'same'})
  self.assertEqual(f({'DOTNET_TieredCompilation':'1'},'default'),{'DOTNET_TieredCompilation':'1'})
  for name in ['DOTNET_TieredCompilation','COMPlus_TieredCompilation']:
   with self.assertRaises(ValueError):f({name:'1'},'single-tier')
  with self.assertRaises(ValueError):f({},'unknown')
 def test_real_renode_popen_uses_private_environment(self):
  tree=ast.parse((P/'rv1106-at32-link/scripts/run_link.py').read_text())
  assignments=[n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='renode_env' for t in n.targets)]
  self.assertEqual(len(assignments),1);self.assertEqual(ast.unparse(assignments[0].value),'renode_host_environment(env, a.renode_host_jit)')
  launch=[n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='r' for t in n.targets) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='subprocess.Popen']
  self.assertEqual(len(launch),1);self.assertEqual(next(ast.unparse(k.value) for k in launch[0].value.keywords if k.arg=='env'),'renode_env')
 def test_python_layers_reject_invalid_or_conflicting(self):
  for env in [{'C22_STOP_EVENT_OPT_IN':'bad'},{'C22_STOP_EVENT_OPT_IN':''},{'CLOCK_CLIENT':'snapshot'},{'CLOCK_CLIENT':'stop-event'},{'C22_STOP_EVENT_OPT_IN':'1','CLOCK_CLIENT':'scalar'}]:
   for file,name,args in [('runner.py','environment',(P,)),('observer.py','fixed_environment',(P,'unused'))]:
    with self.subTest(env=env,file=file),self.assertRaises(ValueError):load_function(R/file,name,env,ACTIVE_SECONDS=86368)(*args)
 def test_shell_rejects_before_creating_run(self):
  for overrides in [{'C22_STOP_EVENT_OPT_IN':'bad'},{'C22_STOP_EVENT_OPT_IN':''},{'CLOCK_CLIENT':'snapshot'},{'CLOCK_CLIENT':'stop-event'},{'C22_STOP_EVENT_OPT_IN':'1','CLOCK_CLIENT':'scalar'}]:
   with self.subTest(env=overrides),tempfile.TemporaryDirectory() as tmp:
    root,script=fixture(tmp);env={'PATH':'/usr/bin:/bin',**overrides};p=subprocess.run(['/bin/bash',str(script),'rejected'],env=env,capture_output=True,timeout=10)
    self.assertNotEqual(p.returncode,0);self.assertFalse((root/'runs').exists());self.assertFalse((root/'CAPTURE.json').exists())
if __name__=='__main__':unittest.main()
