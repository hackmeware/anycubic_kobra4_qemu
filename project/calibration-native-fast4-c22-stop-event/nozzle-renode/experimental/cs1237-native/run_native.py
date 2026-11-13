#!/usr/bin/env python3
"""Short isolated ORIGINAL nozzle boot plus captured startup prefix. No Z request."""
import pathlib,subprocess,tempfile,os,hashlib,json,argparse
p=argparse.ArgumentParser();p.add_argument("--mode",choices=["passive","strict","host-priority"],default="strict");p.add_argument("--mips",type=int,default=100);p.add_argument("--baseline",type=int,default=123456);a=p.parse_args()
base=pathlib.Path(__file__).resolve().parent;root=base.parents[2];out=root/'evidence/cs1237-native-startup';out=out/(a.mode+'-'+str(a.mips)+('' if a.baseline==123456 else '-sample'+str(a.baseline)));out.mkdir(exist_ok=True,parents=True)
capture=root/'runs/native-home-x-heater/rv-nozzle-tx.bin';sys=__import__('sys');sys.path.insert(0,str(root/'rv1106-at32-link/scripts'));from decode_frames import crc16
body=bytes.fromhex('08184d0901');plain=body+crc16(body).to_bytes(2,'big')+b'\x7e';wire=bytes((((x<<1)|(x>>7))&255)^0x8d for x in plain)
prefix=capture.read_bytes()[:503]+wire;(out/'startup-prefix.bin').write_bytes(prefix)
with tempfile.TemporaryDirectory(prefix='cs1237-native-') as f:
 d=pathlib.Path(f);(d/'home/.config').mkdir(parents=True)
 repl=(root/'nozzle-renode/platforms/nozzle-f1-provisional.repl').read_text().replace('gpioA: AT32.AT32GPIO','gpioA: NozzleExperimental.Cs1237NativeGpio')
 if a.mode!='passive':repl+='\nsensor: NozzleExperimental.Cs1237NativeAdapter @ sysbus\n    port: gpioA\n    syntheticBaseline: '+str(a.baseline)+'\n    allowHostPriorityOverlap: '+('true' if a.mode=='host-priority' else 'false')+'\n'
 repl+='\nreplay: NozzleExperimental.CapturedStartupReplay @ sysbus\n    uart: usart1\n';(d/'native.repl').write_text(repl)
 names=['AT32F403A_System.cs','AT32F403A_IO.cs','AT32F403A_Bus.cs','AT32F403A_DWT.cs','AT32F403A_Extras.cs','F1BootFlash.cs','ClockedSTM32Timer.cs']
 lines=[f'include @{root}/nozzle-renode/peripherals/{n}' for n in names]+[f'include @{base}/Cs1237NativeGpio.cs',f'include @{base}/CapturedStartupReplay.cs',f'include @{base}/Cs1237NativeProtocol.cs',f'include @{base}/Cs1237NativeAdapter.cs','mach create "isolated_nozzle"','emulation SetGlobalQuantum "0.000001"',f'machine LoadPlatformDescription @{d}/native.repl',f'cpu PerformanceInMips {a.mips}',f'sysbus LoadBinary @{root}/inputs/nozzle.bin 0x08004000','cpu VectorTableOffset 0x08004000','emulation RunFor "0.4"',f'sysbus.replay Begin "{out}/startup-prefix.bin"','emulation RunFor "0.25"',f'sysbus.gpioA WriteTrace "{out}/passive-gpio.csv"','sysbus.replay BytesSent','sysbus.gpioA Dropped',f'sysbus.replay DumpMemory "{out}/passive-sram.bin"','sysbus ReadDoubleWord 0xE000ED28','sysbus ReadDoubleWord 0xE000ED2C',]
 if a.mode!='passive':lines +=[f'sysbus.sensor WriteTrace "{out}/sensor.csv"',f'sysbus.sensor WriteStatus "{out}/sensor-status.json"']
 lines+=['quit']
 (d/'native.resc').write_text('\n'.join(lines)+'\n')
 env=dict(os.environ,HOME=str(d/'home'),XDG_CONFIG_HOME=str(d/'home/.config'),TMPDIR=str(d))
 r=subprocess.run([str(root/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(d/'native.resc')],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=90)
 (out/'passive-run.log').write_text(r.stdout);print(r.stdout[-5000:]);assert r.returncode==0 and (out/'passive-sram.bin').exists() and 'There was an error' not in r.stdout and 'Errors during compilation' not in r.stdout

metadata={'scope':'Original nozzle image only, no main/motor/host emulator, force model, Z/arm request or PA7/PB2 writes.','mode':a.mode,'mips':a.mips,'synthetic_baseline':a.baseline,'boot_seconds':0.4,'run_end_seconds':0.65,'interbyte_microseconds':200,'output_delay_ns':500,'firmware_sha256':hashlib.sha256((root/'inputs/nozzle.bin').read_bytes()).hexdigest(),'capture_prefix_sha256':hashlib.sha256(prefix).hexdigest(),'capture_prefix_bytes':503,'appended_request':'ordinary command77 args9,1, enable sampling only; no command78 phase/arm','source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in base.glob('*.cs')}}
(out/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
if a.mode!='passive':
 status=json.loads((out/'sensor-status.json').read_text());print(json.dumps(status))
 if a.mode=='host-priority' and a.mips==8:
  assert status['config']==60 and status['config_writes']==1 and status['read_words']>100 and status['protocol_errors']==status['adapter_errors']==0,status
