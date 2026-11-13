#!/usr/bin/env python3
import pathlib,tempfile,subprocess,os,json,hashlib
base=pathlib.Path(__file__).resolve().parent;root=base.parents[2];adapter=base.parent/'cs1237-native';out=root/'evidence/cs1237-native-steps'
with tempfile.TemporaryDirectory(prefix='cs1237-ownership-')as f:
 d=pathlib.Path(f);(d/'home/.config').mkdir(parents=True);repl=''
 for i in range(3):repl+=f'p{i}: NozzleExperimental.Cs1237NativeGpio @ sysbus {hex(0x40000000+i*0x400)}\na{i}: NozzleExperimental.Cs1237NativeAdapter @ sysbus\n    port: p{i}\n    syntheticBaseline: 0\n'
 repl+='tests: NozzleExperimental.Cs1237OwnershipTests @ sysbus\n    port: p0\n    sensor: a0\n    afod: p1\n    afods: a1\n    afpp: p2\n    afpps: a2\n';(d/'test.repl').write_text(repl)
 sources=[root/'nozzle-renode/peripherals/AT32F403A_IO.cs']+[adapter/(n+'.cs')for n in ['Cs1237NativeProtocol','Cs1237NativeGpio','Cs1237NativeAdapter']]+[base/'Cs1237OwnershipTests.cs']
 lines=[f'include @{p}'for p in sources]+['mach create "ownership_no_CPU"',f'machine LoadPlatformDescription @{d}/test.repl','sysbus.tests RunAll','quit'];(d/'test.resc').write_text('\n'.join(lines)+'\n')
 env=dict(os.environ,HOME=str(d/'home'),XDG_CONFIG_HOME=str(d/'home/.config'),TMPDIR=str(d));r=subprocess.run([str(root/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(d/'test.resc')],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=45)
 (out/'ownership-tests.log').write_text(r.stdout);assert r.returncode==0 and 'CS1237 OWNERSHIP TESTS PASS: 14'in r.stdout,r.stdout;print('CS1237 OWNERSHIP TESTS PASS: 14')
 (out/'ownership-tests.json').write_text(json.dumps({'checks':14,'scope':'CPU-free, no firmware, no virtual time run; explicit host ownership classification','source_hashes':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()for p in sources}},indent=2)+'\n')
