#!/usr/bin/env python3
"""CPU-free equation/timer tests against an isolated proposed core extension."""
import hashlib,json,os,pathlib,subprocess,tempfile
from prepare_core import prepare
base=pathlib.Path(__file__).resolve().parent;root=base.parents[2]
out=root/'evidence/synthetic-z-bed-contact';out.mkdir(parents=True,exist_ok=True)
renode=root/'at32-runtime/renode_1.17.0-portable/renode'
original=root/'motor-renode/peripherals/GenericStepperElectromechanical.cs'
original_hash=hashlib.sha256(original.read_bytes()).hexdigest()
with tempfile.TemporaryDirectory(prefix='z-bed-unit-') as folder:
 d=pathlib.Path(folder);(d/'home/.config').mkdir(parents=True)
 core=d/'GenericStepperElectromechanical.cs';manifest=prepare(core)
 env=dict(os.environ,HOME=str(d/'home'),XDG_CONFIG_HOME=str(d/'home/.config'),TMPDIR=str(d))
 def run(label,source,include,commands):
  script=d/(label+'.resc')
  lines=[f'include @{root}/motor-renode/peripherals/AT32F403A_System.cs',
         f'include @{root}/motor-renode/peripherals/AT32F403A_Timer.cs',f'include @{source}']
  lines += [f'include @{x}' for x in include]
  lines += ['mach create "isolated_z_fixture"']+commands+['quit']
  script.write_text('\n'.join(lines)+'\n')
  r=subprocess.run([str(renode),'--disable-gui','--console',str(script)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=60)
  (out/(label+'.log')).write_text(r.stdout)
  if r.returncode!=0 or 'TESTS PASS:' not in r.stdout or ('There was an error' in r.stdout):
   raise RuntimeError(r.stdout[-10000:])
  return [x for x in r.stdout.splitlines() if 'TESTS PASS:' in x]
 regression=root/'motor-renode/tests/GenericElectromechanicalTests.cs'
 commands=['machine LoadPlatformDescriptionFromString "tests: AT32Tests.GenericElectromechanicalTests @ sysbus"','sysbus.tests Run']
 manifest['original_core_regression']=run('original-core-regression',original,[regression],commands)
 manifest['extended_core_regression']=run('extended-core-regression',core,[regression],commands)
 cmds=['machine LoadPlatformDescriptionFromString "tests: MotorExperimental.VirtualZBedContactTests @ sysbus 0x60000000"',
       'sysbus.tests RunEquations','sysbus.tests StartContactDrive','emulation RunFor "0.001"','sysbus.tests CheckContact',
       'sysbus.tests StartDisableTiming','emulation RunFor "0.000001"','sysbus.tests CheckDisableTiming']
 manifest['fixture_tests']=run('fixture-tests',core,[base/'VirtualZBedContactFixture.cs',base/'VirtualZBedContactTests.cs'],cmds)
 assert hashlib.sha256(original.read_bytes()).hexdigest()==original_hash,'Production source unexpectedly changed'
 manifest['scope']='CPU-free Renode equations and real timer events only; isolated patched core; no firmware, native app, GPIO probe, heavy native run, or production file modifications.'
 manifest['sources']={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(base.iterdir()) if p.is_file()}
 (out/'test-summary.json').write_text(json.dumps(manifest,indent=2)+'\n')
 for key in ['original_core_regression','extended_core_regression','fixture_tests']:
  for line in manifest[key]:print(line)
