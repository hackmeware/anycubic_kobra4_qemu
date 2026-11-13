#!/usr/bin/env python3
"""Isolated8-MIPS original-nozzle laboratory steps, ordinary sensor-only phase commands."""
import pathlib,sys,subprocess,tempfile,os,json,hashlib,argparse
base=pathlib.Path(__file__).resolve().parent;root=base.parents[2];adapter=base.parent/'cs1237-native';out=root/'evidence/cs1237-functional/native';out.mkdir(exist_ok=True,parents=True)
sys.path.insert(0,str(root/'rv1106-at32-link/scripts'));from decode_frames import crc16
p=argparse.ArgumentParser();p.add_argument('cases',nargs='*',default=['zero_stable','nonzero_stable','zero_subplus','zero_subminus','zero_superplus','zero_superminus','zero_nearplus','zero_nearminus','zero_equalplus','zero_equalminus','nonzero_superplus','nonzero_superminus','source_removed','phase_reset']);a=p.parse_args()
cases={'zero_stable':(0,0),'nonzero_stable':(123456,123456),'zero_subplus':(0,2400),'zero_subminus':(0,-2400),'zero_nearplus':(0,3000),'zero_nearminus':(0,-3000),'zero_equalplus':(0,51200),'zero_equalminus':(0,-51200),'zero_superplus':(0,10000),'zero_superminus':(0,-10000),'nonzero_superplus':(123456,133456),'nonzero_superminus':(123456,113456),'source_removed':(123456,123456),'phase_reset':(0,10000)}
if len(a.cases)>1:
 for name in a.cases:subprocess.run([sys.executable,__file__,name],check=True)
 sys.exit(0)
def frame(seq,payload):
 body=bytes([len(payload)+5,seq])+bytes(payload);plain=body+crc16(body).to_bytes(2,'big')+b'\x7e';return bytes((((x<<1)|(x>>7))&255)^0x8d for x in plain)
with tempfile.TemporaryDirectory(prefix='cs1237-steps-')as f:
 d=pathlib.Path(f);(d/'home/.config').mkdir(parents=True)
 names=['AT32F403A_System.cs','AT32F403A_IO.cs','AT32F403A_Bus.cs','AT32F403A_DWT.cs','AT32F403A_Extras.cs','F1BootFlash.cs','ClockedSTM32Timer.cs']
 lines=[f'include @{root}/nozzle-renode/peripherals/{n}'for n in names]+[f'include @{adapter}/{n}.cs'for n in ['Cs1237NativeGpio','CapturedStartupReplay']]+[f'include @{base}/Cs1237FunctionalProtocol.cs',f'include @{base}/Cs1237FunctionalAdapter.cs',f'include @{base}/Cs1237FunctionalStepFixture.cs',f'include @{base}/Cs1237FunctionalFailureCapture.cs','emulation SetGlobalQuantum "0.000001"']
 for name in a.cases:
  baseline,step=cases[name];dst=out/name;dst.mkdir(exist_ok=True)
  # Never let an old successful export satisfy a later interrupted test.
  for stale in ['final-sram.bin','failure-sram.bin','native-state.csv','stimuli.csv','sensor-status.json','sensor.csv','gpio.csv','failure-time-ns.txt']:
   old=dst/stale
   if old.exists():old.unlink()
  (dst/'startup.bin').write_bytes((root/'runs/native-home-x-heater/rv-nozzle-tx.bin').read_bytes()[:503]+frame(0x18,[77,9,1]))
  (dst/'arm.bin').write_bytes(frame(0x19,[78,9,3]));(dst/'reset.bin').write_bytes(frame(0x1a,[78,9,0]));(dst/'rearm.bin').write_bytes(frame(0x1b,[78,9,3]))
  repl=(root/'nozzle-renode/platforms/nozzle-f1-provisional.repl').read_text().replace('gpioA: AT32.AT32GPIO','gpioA: NozzleExperimental.Cs1237NativeGpio')
  repl+=f'\nsensor: NozzleExperimental.Cs1237FunctionalAdapter @ sysbus\n    port: gpioA\n    syntheticBaseline: {baseline}\n    idealizedElectricalSemantics: true\nreplay: NozzleExperimental.CapturedStartupReplay @ sysbus\n    uart: usart1\nsteps: NozzleExperimental.Cs1237FunctionalStepFixture @ sysbus\n    port: gpioA\n    sensor: sensor\n    baseline: {baseline}\n'
  if name=='source_removed':repl+=f'failure: NozzleExperimental.Cs1237FunctionalFailureCapture @ sysbus\n    port: gpioA\n    sensor: sensor\n    steps: steps\n    directory: "{dst}"\n'
  (dst/'fixture.repl').write_text(repl)
  lines +=[f'mach create "{name}"',f'machine LoadPlatformDescription @{dst}/fixture.repl','cpu PerformanceInMips 100',f'sysbus LoadBinary @{root}/inputs/nozzle.bin 0x08004000','cpu VectorTableOffset 0x08004000',f'sysbus.usart1 CreateFileBackend @{dst}/nozzle-tx.bin',f'sysbus.steps StepAt 650000000 {step}']
  if name=='source_removed':lines+=['sysbus.steps RemoveSourceAt 650000000']
  lines+=['emulation RunFor "0.4"',f'sysbus.replay Begin "{dst}/startup.bin"','emulation RunFor "0.2"',f'sysbus.steps Mark "before-arm"',f'sysbus.replay Begin "{dst}/arm.bin"','emulation RunFor "0.2"']
  if name=='phase_reset':
   lines +=[f'sysbus.replay Begin "{dst}/reset.bin"','emulation RunFor "0.03"','sysbus.steps StepAt 830000000 0','emulation RunFor "0.12"',f'sysbus.replay Begin "{dst}/rearm.bin"','emulation RunFor "0.05"','sysbus.steps StepAt 1000000000 10000','emulation RunFor "0.2"']
  lines +=[f'sysbus.steps WriteTrace "{dst}/native-state.csv"',f'sysbus.steps WriteStimuli "{dst}/stimuli.csv"',f'sysbus.steps Dropped',f'sysbus.sensor WriteStatus "{dst}/sensor-status.json"',f'sysbus.sensor WriteTrace "{dst}/sensor.csv"',f'sysbus.gpioA WriteTrace "{dst}/gpio.csv"',f'sysbus.replay DumpMemory "{dst}/final-sram.bin"','sysbus ReadDoubleWord 0xE000ED28','sysbus ReadDoubleWord 0xE000ED2C']
  sources=[adapter/'Cs1237NativeGpio.cs',adapter/'CapturedStartupReplay.cs']+[base/'Cs1237FunctionalProtocol.cs',base/'Cs1237FunctionalAdapter.cs',base/'Cs1237FunctionalStepFixture.cs']+([base/'Cs1237FunctionalFailureCapture.cs'] if name=='source_removed' else []);(dst/'metadata.json').write_text(json.dumps({'fixture':'explicit-functional100MIPS;no-hardware-timing-fidelity;host-priority;500ns output;200us UART gaps;no force/geometry/Z/PB2','baseline':baseline,'step':step,'step_requested_ns':650000000,'arm_request_start_ns':600000000,'end_ns':1200000000 if name=='phase_reset' else 800000000,'source_hashes':{str(x.relative_to(root)):hashlib.sha256(x.read_bytes()).hexdigest()for x in sources},'nozzle_sha256':hashlib.sha256((root/'inputs/nozzle.bin').read_bytes()).hexdigest()},indent=2)+'\n')
 lines+=['quit'];script=d/'steps.resc';script.write_text('\n'.join(lines)+'\n');(out/'last-generated.resc').write_text(script.read_text())
 env=dict(os.environ,HOME=str(d/'home'),XDG_CONFIG_HOME=str(d/'home/.config'),TMPDIR=str(d));r=subprocess.run([str(root/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(script)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=240)
 (out/('run-'+'-'.join(a.cases)+'.log')).write_text(r.stdout);print(r.stdout[-4000:]);assert ((a.cases==['source_removed'] and 'Native sensor read has no valid electrical level' in r.stdout and r.returncode!=0) or (r.returncode==0 and 'There was an error'not in r.stdout and 'Errors during compilation'not in r.stdout))
 for name in a.cases:assert(out/name/('failure-sram.bin'if name=='source_removed'else'final-sram.bin')).exists(),name
