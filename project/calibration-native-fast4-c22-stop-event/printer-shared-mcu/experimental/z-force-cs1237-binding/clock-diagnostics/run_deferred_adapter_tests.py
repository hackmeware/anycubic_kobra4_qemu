#!/usr/bin/env python3
import argparse,hashlib,json,os
from pathlib import Path
import subprocess,tempfile
ROOT=Path(__file__).resolve().parents[4];base=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--expect-pre-fix-failure',action='store_true');p.add_argument('--adapter-source',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve()
if out.exists():raise SystemExit('New evidence directory required')
out.mkdir(parents=True)
with tempfile.TemporaryDirectory(prefix='adapter-deferred-')as f:
 d=Path(f);(d/'home/.config').mkdir(parents=True)
 sources=[ROOT/'nozzle-renode/peripherals/AT32F403A_IO.cs',ROOT/'nozzle-renode/experimental/cs1237-native/Cs1237NativeGpio.cs',ROOT/'nozzle-renode/experimental/cs1237-functional/Cs1237FunctionalProtocol.cs',ROOT/'nozzle-renode/experimental/cs1237-functional/Cs1237FunctionalAdapter.cs',base/'AdapterDeferredDeadlineTests.cs']
 if a.adapter_source:sources[3]=a.adapter_source.resolve()
 if not a.expect_pre_fix_failure:sources+=[base/'DeadlineSchedulerTests.cs']
 source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()for p in sources}
 compiled=[]
 for original in sources:
  target=d/original.name;target.write_bytes(original.read_bytes());compiled.append(target)
 assert all(hashlib.sha256(p.read_bytes()).hexdigest()==source_hashes[str(original.relative_to(ROOT))] for original,p in zip(sources,compiled))
 lines=[f'include @{p}'for p in compiled]+['emulation SetGlobalQuantum "0.000001"','mach create "deferred-no-CPU"','machine LoadPlatformDescriptionFromString "checks: PrinterExperimental.AdapterDeferredDeadlineTests @ sysbus"','emulation RunFor "0.3020001"',f'sysbus.checks CompleteConversion {str(not a.expect_pre_fix_failure).lower()}']
 if not a.expect_pre_fix_failure:lines+=['machine LoadPlatformDescriptionFromString "schedulerChecks: PrinterExperimental.DeadlineSchedulerTests @ sysbus"','sysbus.schedulerChecks RunAll','emulation RunFor "0.0999999"','sysbus.checks BeginDeferredBit','emulation RunFor "0.0000006"',f'sysbus.checks CompleteBit "{out}/deferred-trace.csv"']
 lines+=['quit'];script=d/'test.resc';script.write_text('\n'.join(lines)+'\n');(out/'test.resc.txt').write_text(script.read_text())
 r=subprocess.run([str(ROOT/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(script)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=dict(os.environ,HOME=str(d/'home'),XDG_CONFIG_HOME=str(d/'home/.config'),TMPDIR=str(d)),timeout=60)
 (out/'renode.log').write_text(r.stdout);expected=['EXPECTED PRE-FIX FAILURE']if a.expect_pre_fix_failure else['DEFERRED CONVERSION TEST PASS:','DEFERRED BIT TEST PASS:','DEADLINE SCHEDULER TESTS PASS:'];ok=r.returncode==0 and all(x in r.stdout for x in expected) and'There was an error'not in r.stdout
 summary={'passed':ok,'expected_pre_fix_failure':a.expect_pre_fix_failure,'sources':source_hashes,'results':[x for x in r.stdout.splitlines()if'ADAPTER DEFERRED'in x or 'DEADLINE SCHEDULER TESTS'in x]};(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print('\n'.join(summary['results']))
 if not ok:raise RuntimeError(r.stdout[-12000:])
