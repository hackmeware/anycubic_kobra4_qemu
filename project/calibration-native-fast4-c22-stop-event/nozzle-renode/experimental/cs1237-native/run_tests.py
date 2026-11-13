#!/usr/bin/env python3
"""CPU-free protocol regression and adapter negative/reset checks."""
import pathlib,tempfile,os,subprocess,json,hashlib
base=pathlib.Path(__file__).resolve().parent;root=base.parents[2];out=root/'evidence/cs1237-native-startup';out.mkdir(exist_ok=True,parents=True)
with tempfile.TemporaryDirectory(prefix='cs1237-adapter-unit-') as f:
 d=pathlib.Path(f);(d/'home/.config').mkdir(parents=True)
 old=(base.parent/'cs1237-protocol/Cs1237ProtocolTests.cs').read_text().replace('Cs1237Protocol','Cs1237NativeProtocol');(d/'CoreTests.cs').write_text(old)
 repl='coreTests: NozzleExperimental.Cs1237NativeProtocolTests @ sysbus 0x60000000\n'
 for i in range(1,8):
  repl+=f'p{i}: NozzleExperimental.Cs1237NativeGpio @ sysbus {hex(0x40000000+i*0x400)}\na{i}: NozzleExperimental.Cs1237NativeAdapter @ sysbus\n    port: p{i}\n    syntheticBaseline: 123456\n    allowHostPriorityOverlap: '+('true'if i in(4,7)else'false')+'\n'
 repl+='checks: NozzleExperimental.Cs1237AdapterTests @ sysbus\n'+''.join(f'    p{i}: p{i}\n    a{i}: a{i}\n'for i in range(1,8));(d/'test.repl').write_text(repl)
 lines=[f'include @{root}/nozzle-renode/peripherals/AT32F403A_IO.cs']+[f'include @{base}/{n}.cs'for n in ['Cs1237NativeProtocol','Cs1237NativeGpio','Cs1237NativeAdapter','Cs1237AdapterTests']]+[f'include @{d}/CoreTests.cs','mach create "CPU-free"',f'machine LoadPlatformDescription @{d}/test.repl','sysbus.coreTests RunAll','sysbus.checks Prepare','emulation RunFor "0.30201"','sysbus.checks Ready','sysbus.checks BeginReset','emulation RunFor "0.000001"','sysbus.checks EndReset','emulation RunFor "0.1"','sysbus.checks Finish','quit'];(d/'test.resc').write_text('\n'.join(lines)+'\n')
 env=dict(os.environ,HOME=str(d/'home'),XDG_CONFIG_HOME=str(d/'home/.config'),TMPDIR=str(d));r=subprocess.run([str(root/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(d/'test.resc')],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=60)
 (out/'unit-tests.log').write_text(r.stdout);assert r.returncode==0 and 'CS1237 ADAPTER TESTS PASS:' in r.stdout and 'CS1237 ISOLATED PROTOCOL TESTS PASS: 1421' in r.stdout,r.stdout[-6000:];print('\n'.join(x for x in r.stdout.splitlines()if 'TESTS PASS:'in x));(out/'unit-tests.json').write_text(json.dumps({'core_assertions':1421,'source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in base.glob('*.cs')}},indent=2)+'\n')
