#!/usr/bin/env python3
"""CPU-free fractional callback reproduction and post-fix negative time-contract checks."""
import argparse,hashlib,importlib.util,json,os
from pathlib import Path
import subprocess,tempfile
ROOT=Path(__file__).resolve().parents[4];base=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--expect-pre-fix-failure',action='store_true');p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve()
if out.exists():raise SystemExit('New evidence directory required')
out.mkdir(parents=True)
spec=importlib.util.spec_from_file_location('prepare_z_core',ROOT/'motor-renode/experimental/z-bed-contact/prepare_core.py');helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
with tempfile.TemporaryDirectory(prefix='z-fractional-')as folder:
 d=Path(folder);(d/'home/.config').mkdir(parents=True);core=d/'GenericStepperElectromechanical.cs';core.write_text(helper.extended((ROOT/'motor-renode/peripherals/GenericStepperElectromechanical.cs').read_text()))
 sources=[ROOT/'motor-renode/peripherals/AT32F403A_System.cs',ROOT/'motor-renode/peripherals/AT32F403A_Timer.cs',ROOT/'nozzle-renode/peripherals/AT32F403A_IO.cs',core,
 ROOT/'motor-renode/experimental/z-bed-contact/VirtualZBedContactFixture.cs',base.parent/'ZForceHistory.cs',base.parent/'MotorZForceSource.cs',
 ROOT/'nozzle-renode/experimental/cs1237-native/Cs1237NativeGpio.cs',ROOT/'nozzle-renode/experimental/cs1237-functional/Cs1237FunctionalProtocol.cs',ROOT/'nozzle-renode/experimental/cs1237-functional/Cs1237FunctionalAdapter.cs',
 base.parent/'Cs1237ZForceBinding.cs',base.parent/'ZForceIntegrationTests.cs',base/'FractionalBindingTest.cs']
 if not a.expect_pre_fix_failure:sources+=[base/'ConsumerClockGuardTests.cs']
 lines=[f'include @{s}'for s in sources]+['emulation SetGlobalQuantum "0.000001"','mach create "motor"','machine LoadPlatformDescriptionFromString "motorLab: PrinterExperimental.ZForceMotorLab @ sysbus"','mach create "nozzle"','machine LoadPlatformDescriptionFromString "fractional: PrinterExperimental.FractionalBindingTest @ sysbus"','emulation RunFor "0.000003"',f'sysbus.fractional Report {str(not a.expect_pre_fix_failure).lower()}']
 if not a.expect_pre_fix_failure:lines+=['machine LoadPlatformDescriptionFromString "guards: PrinterExperimental.ConsumerClockGuardTests @ sysbus"','sysbus.guards RunAll']
 lines+=['quit'];script=d/'test.resc';script.write_text('\n'.join(lines)+'\n');(out/'test.resc.txt').write_text(script.read_text())
 env=dict(os.environ,HOME=str(d/'home'),XDG_CONFIG_HOME=str(d/'home/.config'),TMPDIR=str(d));r=subprocess.run([str(ROOT/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(script)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=90)
 (out/'renode.log').write_text(r.stdout);marker='Z FRACTIONAL BINDING TEST EXPECTED PRE-FIX FAILURE'if a.expect_pre_fix_failure else'Z FRACTIONAL BINDING TEST PASS'
 ok=r.returncode==0 and marker in r.stdout and'There was an error'not in r.stdout and (a.expect_pre_fix_failure or'Z CONSUMER CLOCK GUARD TESTS PASS:'in r.stdout)
 summary={'passed':ok,'expected_pre_fix_failure':a.expect_pre_fix_failure,'source_sha256':{str(s.relative_to(ROOT)) if s!=core else'isolated_core':hashlib.sha256(s.read_bytes()).hexdigest()for s in sources},'results':[line for line in r.stdout.splitlines() if'BINDING TEST'in line or'CLOCK GUARD TESTS'in line]};(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
 print('\n'.join(summary['results']))
 if not ok:raise RuntimeError(r.stdout[-12000:])
