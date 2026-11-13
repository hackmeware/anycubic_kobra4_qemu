#!/usr/bin/env python3
"""CPU-free, experimental history and two-machine force->ADC integration only."""
import argparse,hashlib,importlib.util,json,os,pathlib,subprocess,tempfile
base=pathlib.Path(__file__).resolve().parent;root=base.parents[2]
parser=argparse.ArgumentParser();parser.add_argument('--shared-namespaces',action='store_true');args=parser.parse_args()
prefix='shared-' if args.shared_namespaces else ''
out=root/'evidence/z-force-cs1237-binding';out.mkdir(parents=True,exist_ok=True)
core_path=root/'motor-renode/peripherals/GenericStepperElectromechanical.cs';before=hashlib.sha256(core_path.read_bytes()).hexdigest()
spec=importlib.util.spec_from_file_location('prepare_z_core',root/'motor-renode/experimental/z-bed-contact/prepare_core.py');helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
with tempfile.TemporaryDirectory(prefix='z-force-bind-unit-')as folder:
 d=pathlib.Path(folder);(d/'home/.config').mkdir(parents=True)
 core=d/'GenericStepperElectromechanical.cs';core.write_text(helper.extended(core_path.read_text()))
 sources=[root/'motor-renode/peripherals/AT32F403A_System.cs',root/'motor-renode/peripherals/AT32F403A_Timer.cs',root/'nozzle-renode/peripherals/AT32F403A_IO.cs',core,
  root/'motor-renode/experimental/z-bed-contact/VirtualZBedContactFixture.cs',base/'ZForceHistory.cs',base/'MotorZForceSource.cs',
  root/'nozzle-renode/experimental/cs1237-native/Cs1237NativeGpio.cs',root/'nozzle-renode/experimental/cs1237-functional/Cs1237FunctionalProtocol.cs',root/'nozzle-renode/experimental/cs1237-functional/Cs1237FunctionalAdapter.cs',
  base/'Cs1237ZForceBinding.cs',base/'ZForceHistoryTests.cs',base/'ZForceIntegrationTests.cs']
 source_hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()for p in sources if p!=core}
 compiled=[];compiled_hashes={}
 for i,p in enumerate(sources):
  text=p.read_text()
  if args.shared_namespaces:
   namespace='PrinterNozzle' if str(p).startswith(str(root/'nozzle-renode')) else 'PrinterMotor'
   text=text.replace('Antmicro.Renode.Peripherals.AT32','Antmicro.Renode.Peripherals.'+namespace)
  target=d/(str(i)+'-'+p.name);target.write_text(text);compiled.append(target)
  compiled_hashes[str(p.relative_to(root)) if p!=core else 'isolated_extended_core']=hashlib.sha256(target.read_bytes()).hexdigest()
 lines=[f'include @{p}'for p in compiled]+[
 'emulation SetGlobalQuantum "0.000001"','mach create "motor-history-test"',
 'machine LoadPlatformDescriptionFromString "historyTests: PrinterExperimental.ZForceHistoryTests @ sysbus"','sysbus.historyTests RunAll',
 'machine LoadPlatformDescriptionFromString "motorLab: PrinterExperimental.ZForceMotorLab @ sysbus"',
 'mach create "nozzle-conversion-test"','machine LoadPlatformDescriptionFromString "nozzleLab: PrinterExperimental.ZForceNozzleLab @ sysbus"',
 'emulation RunFor "0.303"','sysbus.nozzleLab VerifyContactConversion',
 'mach set "motor-history-test"','sysbus.motorLab VerifyPhysicalInvariance','sysbus.motorLab DisableFixtures',
 'emulation RunFor "0.100"','mach set "nozzle-conversion-test"','sysbus.nozzleLab VerifyDisabledConversion','sysbus.nozzleLab VerifyTemporalGuardRejections',
 'mach set "motor-history-test"','sysbus.motorLab VerifyPhysicalInvariance','sysbus.motorLab StopAdcTriggers',
 f'sysbus.motorLab WriteTrace "{out}/{prefix}conversion-force-trace.csv"','emulation RunFor "0.100"',
 'mach set "nozzle-conversion-test"','sysbus.nozzleLab VerifyStaleFault','quit']
 (d/'test.resc').write_text('\n'.join(lines)+'\n')
 env=dict(os.environ,HOME=str(d/'home'),XDG_CONFIG_HOME=str(d/'home/.config'),TMPDIR=str(d))
 r=subprocess.run([str(root/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(d/'test.resc')],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=90)
 (out/(prefix+'unit-tests.log')).write_text(r.stdout)
 expected=['Z FORCE HISTORY TESTS PASS:','Z FORCE CROSS-MACHINE CONTACT TESTS PASS:','Z FORCE PHYSICS INVARIANCE TESTS PASS:','Z FORCE DISABLED CONVERSION TESTS PASS:','Z FORCE STALE FAIL-CLOSED TESTS PASS:','Z FORCE CROSS-MACHINE TEMPORAL NEGATIVES PASS:']
 if r.returncode!=0 or not all(x in r.stdout for x in expected):raise RuntimeError(r.stdout[-14000:])
 assert hashlib.sha256(core_path.read_bytes()).hexdigest()==before,'Production core changed during isolated tests'
 manifest={'shared_namespaces':args.shared_namespaces,'compiled_source_sha256':compiled_hashes,'scope':'Two CPU-free Renode machines; real motor timer/contact and ADC conversion deadlines; no firmware image, native CPU, GPIO probe writes, production edits or physical hardware. Proposed core extension is isolated in temporary file.',
  'core_source_sha256':before,'extended_core_sha256':hashlib.sha256(core.read_bytes()).hexdigest(),
  'passes':[x for x in r.stdout.splitlines()if 'TESTS PASS:'in x or 'TEMPORAL NEGATIVES PASS:'in x],
  'source_sha256':source_hashes,
  'inputs_unchanged_after_test':all(hashlib.sha256((root/p).read_bytes()).hexdigest()==h for p,h in source_hashes.items())}
 (out/(prefix+'test-summary.json')).write_text(json.dumps(manifest,indent=2)+'\n')
 print('\n'.join(manifest['passes']))
