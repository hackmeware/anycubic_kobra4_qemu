#!/usr/bin/env python3
"""CPU-free causal probe-wire and known connector limitation tests. No native replay."""
import argparse, hashlib, json, os, pathlib, re, subprocess, tempfile
from prepare_wire import connect_commands
base=pathlib.Path(__file__).resolve().parent; root=base.parents[2]
p=argparse.ArgumentParser();p.add_argument('--shared-namespaces',action='store_true');p.add_argument('--negative-reselect',action='store_true');a=p.parse_args()
out=root/'evidence/z-probe-wire';out.mkdir(parents=True,exist_ok=True)
label=('shared-' if a.shared_namespaces else '')+('negative-' if a.negative_reselect else '')
with tempfile.TemporaryDirectory(prefix='probe-wire-') as td:
 d=pathlib.Path(td);(d/'home/.config').mkdir(parents=True)
 sources=[root/'nozzle-renode/peripherals/AT32F403A_IO.cs',root/'nozzle-renode/experimental/cs1237-native/Cs1237NativeGpio.cs',base/'ProbeWireTests.cs']
 if a.shared_namespaces:sources.insert(0,root/'at32-renode/peripherals/AT32F403A_IO.cs')
 inc=[];compiled_hashes={}
 for i,src in enumerate(sources):
  text=src.read_text()
  if a.shared_namespaces:
   ns='PrinterMain' if src.parts[-3]=='at32-renode' else 'PrinterNozzle'
   text=text.replace('Antmicro.Renode.Peripherals.AT32','Antmicro.Renode.Peripherals.'+ns)
  target=d/(str(i)+'-'+src.name);target.write_text(text);inc.append(f'include @{target}');compiled_hashes[str(src.relative_to(root))]=hashlib.sha256(text.encode()).hexdigest()
 ns='PrinterMain' if a.shared_namespaces else 'AT32'
 lines=inc+[
 'emulation SetGlobalQuantum "0.00001"',
 'mach create "nozzle"',
 f'machine LoadPlatformDescriptionFromString "gpioA: NozzleExperimental.Cs1237NativeGpio @ sysbus 0x40010800 {{ portIndex: 0 }}; sourceWatch: PrinterExperimental.ProbeWireTests @ sysbus {{ gpio: gpioA; pin: 7 }}; sourceOther: PrinterExperimental.ProbeWireTests @ sysbus {{ gpio: gpioA; pin: 6 }}"',
 # Initial levels genuinely established in GPIO before cable attachment.
 'sysbus.gpioA WriteDoubleWord 0 0x22444444','sysbus.gpioA WriteDoubleWord 12 0x80',
 'sysbus.sourceWatch Check true "source preexisting high"','sysbus.sourceOther Check false "source preexisting low"',
 'mach create "main"',
 f'machine LoadPlatformDescriptionFromString "gpioB: {ns}.AT32GPIO @ sysbus 0x40010c00 {{ portIndex: 1 }}; targetWatch: PrinterExperimental.ProbeWireTests @ sysbus {{ gpio: gpioB; pin: 2 }}; targetOther: PrinterExperimental.ProbeWireTests @ sysbus {{ gpio: gpioB; pin: 3 }}; targetGuard: PrinterExperimental.ProbeWireTests @ sysbus {{ gpio: gpioB; pin: 4 }}"',
 'sysbus.gpioB WriteDoubleWord 0 0x44488844','sysbus.gpioB WriteDoubleWord 12 0x1C',
 'sysbus.targetWatch Check true "unconnected PB2 pullup"','sysbus.targetOther Check true "unconnected PB3 pullup"','sysbus.targetGuard Check true "unselected PB4 pullup"',
 ]+connect_commands('assumedZProbe','main')+[
 'emulation CreateGPIOConnector "initialLowControl"','connector Connect sysbus.gpioB initialLowControl','initialLowControl SelectDestinationPin sysbus.gpioB 3',
 'mach set "nozzle"','connector Connect sysbus.gpioA initialLowControl','initialLowControl SelectSourcePin sysbus.gpioA 6',
 'emulation RunFor "0.001"','mach set "main"',
 'sysbus.targetWatch Check true "destination-first initial high preserved"','sysbus.targetOther Check false "destination-first initial low overrides pullup"','sysbus.targetGuard Check true "no unselected destination fanout"',
 'mach set "nozzle"','sysbus.sourceWatch Status "fanout-after-attach"',
 'sysbus.gpioA WriteDoubleWord 20 0x80','emulation RunFor "0.001"','mach set "main"',
 'sysbus.targetWatch Check false "noninverting genuine low reaches PB2"','sysbus.targetOther Check false "low transition does not change PB3"',
 'mach set "nozzle"','sysbus.gpioA WriteDoubleWord 16 0x80','emulation RunFor "0.001"','mach set "main"',
 'sysbus.targetWatch Check true "noninverting genuine high reaches PB2"','sysbus.targetGuard Check true "selected transition leaves PB4 alone"',
 'mach set "nozzle"','sysbus.sourceWatch CheckEdges 3 "source observer survives connector fanout"',
 'sysbus.gpioA WriteDoubleWord 16 0x40','emulation RunFor "0.001"','mach set "main"',
 'sysbus.targetWatch Check true "unselected PA6 high cannot trigger PB2"','sysbus.targetOther Check true "independent PA6 control line rises"',
 'mach set "nozzle"','sysbus.gpioA WriteDoubleWord 20 0x40','emulation RunFor "0.001"','mach set "main"',
 'sysbus.targetWatch Check true "unselected PA6 low cannot clear PB2"','sysbus.targetOther Check false "independent PA6 control line falls"',
 # Same-level writes do not manufacture edges, including external input overridden by push-pull.
 'sysbus.targetWatch Status "before-same-level"','mach set "nozzle"',
 'sysbus.gpioA WriteDoubleWord 16 0x80','sysbus.gpioA OnGPIO 7 false','emulation RunFor "0.001"','mach set "main"',
 'sysbus.targetWatch Status "after-same-level"','sysbus.targetWatch Check true "wire follows resolved pad not external or latch input"',
 # Source GPIO reset really lowers its resolved pin; wire forwards that actual level.
 'mach set "nozzle"','sysbus.gpioA Reset','emulation RunFor "0.001"','mach set "main"',
 'sysbus.targetWatch Check false "source reset low propagates without fabricated trigger"',
 # Destination-only reset loses externally supplied state in AT32GPIO. Characterize, do not hide.
 'sysbus.gpioB Reset','sysbus.gpioB WriteDoubleWord 0 0x44488844','sysbus.gpioB WriteDoubleWord 12 0x1C','emulation RunFor "0.001"',
 'sysbus.targetWatch Check true "known target-reset limitation: pullup replaces unchanged source low"',
 # Use a NEW destination-first connector at this paused boundary. Never re-select a source.
 
 'assumedZProbe DetachFrom sysbus.gpioB','emulation CreateGPIOConnector "assumedZProbeReconnected"',
 'connector Connect sysbus.gpioB assumedZProbeReconnected','assumedZProbeReconnected SelectDestinationPin sysbus.gpioB 2',
 'mach set "nozzle"','connector Connect sysbus.gpioA assumedZProbeReconnected','assumedZProbeReconnected SelectSourcePin sysbus.gpioA 7',
 'emulation RunFor "0.001"','mach set "main"','sysbus.targetWatch Check false "fresh destination-first attachment restores actual low after target reset"',
 # Characterize detach and stale pad, then explicit physical release while paused.
 'mach set "nozzle"','sysbus.gpioA WriteDoubleWord 0 0x22444444','sysbus.gpioA WriteDoubleWord 12 0',
 'emulation RunFor "0.001"','mach set "main"','sysbus.targetWatch Check false "pre-disconnect source low"',
 'assumedZProbeReconnected DetachFrom sysbus.gpioB','emulation RunFor "0.001"','sysbus.targetWatch Status "after-detach-before-release"',
 'sysbus.gpioB ReleasePin 2','sysbus.targetWatch Check true "explicit unplug releases target to configured pullup"',
 'mach set "nozzle"','sysbus.gpioA WriteDoubleWord 16 0x80','sysbus.gpioA WriteDoubleWord 20 0x80','emulation RunFor "0.001"','mach set "main"',
 'sysbus.targetWatch Check true "disconnected PA7 edges do not drive PB2"',
 'mach set "nozzle"','sysbus.sourceWatch Check false "disconnect preserves source resolved level"','sysbus.sourceWatch Status "observer-after-disconnect"','sysbus.sourceWatch CheckEdges 6 "destination-only disconnect preserves source fanout"',
 'echo "SOURCE_SYNCHRONIZATIONS"','sysbus.gpioA Synchronizations','sysbus.sourceWatch Result',
 'mach set "main"','sysbus.targetWatch Result','sysbus.targetOther Result','sysbus.targetGuard Result']
 if a.negative_reselect:
  lines += [
   'mach set "nozzle"','sysbus.gpioA WriteDoubleWord 16 0x80',
   'emulation CreateGPIOConnector "sourceFirstNegative"','connector Connect sysbus.gpioA sourceFirstNegative','sourceFirstNegative SelectSourcePin sysbus.gpioA 7',
   'mach set "main"','connector Connect sysbus.gpioB sourceFirstNegative','sourceFirstNegative SelectDestinationPin sysbus.gpioB 2',
   'emulation RunFor "0.001"','sysbus.targetWatch Check false "known source-first limitation loses preexisting high"',
   'mach set "nozzle"','sysbus.sourceWatch CheckEdges 7 "negative precondition: existing observers intact"',
   'sourceFirstNegative SelectSourcePin sysbus.gpioA 7',
   'sysbus.gpioA WriteDoubleWord 20 0x80','sysbus.gpioA WriteDoubleWord 16 0x80','emulation RunFor "0.001"',
   'sysbus.sourceWatch CheckEdges 7 "known reselection limitation disconnects other source observers"',
   'mach set "main"','sysbus.targetWatch Check true "reselected connector itself continues forwarding later edges"'
  ]
 lines += ['quit']
 script='\n'.join(lines)+'\n'; (d/'test.resc').write_text(script)
 # Save reproducible generated script with persistent original source includes.
 persisted=script
 for i,src in enumerate(sources):
  saved=out/(label+'compiled')/(str(i)+'-'+src.name);saved.parent.mkdir(exist_ok=True);saved.write_bytes((d/(str(i)+'-'+src.name)).read_bytes());persisted=persisted.replace(str(d/(str(i)+'-'+src.name)),str(saved))
 (out/(label+'test.resc')).write_text(persisted)
 env=dict(os.environ,HOME=str(d/'home'),XDG_CONFIG_HOME=str(d/'home/.config'),TMPDIR=str(d))
 r=subprocess.run([str(root/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(d/'test.resc')],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=60)
 (out/(label+'test.log')).write_text(r.stdout)
 clean=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',r.stdout)
 print(clean[-15000:])
 if r.returncode!=0 or clean.count('PROBE WIRE TESTS PASS:')!=4 or 'There was an error' in clean:raise RuntimeError('Probe wire test did not finish cleanly')
 before=re.search('WIRE STATUS: before-same-level[^\n]+',clean)[0].split(' calls=')[1].split(' ns=')[0]
 after=re.search('WIRE STATUS: after-same-level[^\n]+',clean)[0].split(' calls=')[1].split(' ns=')[0]
 assert before==after, 'Same-level source write made a target edge'
 assert re.search(r'SOURCE_SYNCHRONIZATIONS\s+0x0+\s',clean), 'Unexpected source SyncTime request'
 manifest={'shared_namespaces':a.shared_namespaces,'negative_reselect':a.negative_reselect,'compiled_source_sha256':compiled_hashes,'scope':'CPU-free, two-machine synthetic electrical fixture only; no firmware, force/plant, physical cable claim or native replay','checks':len(re.findall('WIRE CHECK PASS:',clean))+2,'source_sha256':{str(s.relative_to(root)):hashlib.sha256(s.read_bytes()).hexdigest() for s in sources+[base/'prepare_wire.py',base/'run_tests.py']},'statuses':re.findall(r'WIRE STATUS:[^\n]+',clean),'synchronizations':0}
 (out/(label+'test-summary.json')).write_text(json.dumps(manifest,indent=2)+'\n')
