#!/usr/bin/env python3
"""Compile/run only isolated protocol unit tests; no CPUs, firmware, GPIO or native run."""
import hashlib,json,os,pathlib,subprocess,tempfile
base=pathlib.Path(__file__).resolve().parent;root=base.parents[2]
out=root/'evidence/cs1237-protocol';out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='cs1237-unit-') as folder:
 d=pathlib.Path(folder);(d/'home/.config').mkdir(parents=True)
 repl=d/'test.repl';repl.write_text('tests: NozzleExperimental.Cs1237ProtocolTests @ sysbus 0x60000000\n')
 script=d/'test.resc';script.write_text('\n'.join([f'include @{base}/Cs1237Protocol.cs',f'include @{base}/Cs1237ProtocolTests.cs','mach create "isolated_protocol"',f'machine LoadPlatformDescription @{repl}','sysbus.tests RunAll','quit'])+'\n')
 env=dict(os.environ,HOME=str(d/'home'),XDG_CONFIG_HOME=str(d/'home/.config'),TMPDIR=str(d))
 r=subprocess.run([str(root/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(script)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=45)
 (out/'unit-test.log').write_text(r.stdout)
 assert r.returncode==0 and 'CS1237 ISOLATED PROTOCOL TESTS PASS:' in r.stdout,r.stdout[-5000:]
 print(next(x for x in r.stdout.splitlines()if 'CS1237 ISOLATED PROTOCOL TESTS PASS:' in x))
 manifest={'scope':'CPU-free C# tests with explicitly synthetic virtual times and ADC samples only. No GPIO, firmware image, native app or run profile loaded.','returncode':r.returncode,'sources':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in base.glob('*.cs')}}
 (out/'unit-test-summary.json').write_text(json.dumps(manifest,indent=2)+'\n')
