#!/usr/bin/env python3
"""CPU-driven, shared-virtual-time GPIO capture + serial transport regression."""
import json,re,subprocess,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[2];pkg=root/'printer-shared-mcu'
subprocess.run(['python3',str(pkg/'tools/generate.py')],check=True)
subprocess.run(['python3',str(pkg/'tests/make_wire_smoke.py')],check=True)
s=(pkg/'tests/wires.resc').read_text();s=s[s.index('mach set "AT32F403ARGT7"'):]
for old,new in [('AT32F403ARGT7','main'),('Motor-AT32-Provisional','motor'),('Nozzle-F1-Provisional','nozzle')]:s=s.replace(old,new)
s=s.replace('/workspace/scratch/ca95ca5f55d9/printer-shared-mcu',str(pkg))
s='include @'+str(pkg/'generated/shared-load.resc')+'\n'+s
with tempfile.TemporaryDirectory(prefix='shared-wire-') as td:
 f=Path(td)/'test.resc';f.write_text(s)
 p=subprocess.run([str(root/'at32-runtime/run-renode'),'--disable-gui','--console',str(f)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90)
 raw=p.stdout.decode(errors='replace');(pkg/'tests/wires-verified.log').write_text(raw)
 t=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',raw)
 assert p.returncode==0 and 'SHARED WIRE TEST COMPLETE' in t and 'There was an error' not in t,t[-2000:]
 def val(name):return int(re.search(r'Script: '+name+r'\s+0x([0-9A-Fa-f]+)',t)[1],16)
 assert val('CAPTURE')>0,t[-2000:]
 assert val('UART')==0x5a,t[-2000:]
 result=dict(pass_test=True,real_cpu_generated_gpio=True,capture=val('CAPTURE'),uart=val('UART'),scope='Synthetic CPU stimulus, actual shared GPIO connector and virtual UART. Not native host synchronization validation.')
 (pkg/'tests/wires-result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
