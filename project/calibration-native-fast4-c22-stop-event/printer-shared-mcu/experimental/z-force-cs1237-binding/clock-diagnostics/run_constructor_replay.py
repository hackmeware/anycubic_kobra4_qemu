#!/usr/bin/env python3
"""Short three-MCU constructor-only UART replay, with no phase-arm, homing, heat or print commands."""
import argparse, hashlib, json, os
from pathlib import Path
import subprocess, sys
ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(ROOT/'rv1106-at32-link/scripts'),str(ROOT/'rv1106-at32-link/tests')]
from shared_mcu import prepare
from test_z_probe_profile import arguments
from z_probe_selection import final_commands
from decode_frames import frames
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--require-healthy',action='store_true');a=p.parse_args();require_healthy=a.require_healthy;out=a.output.resolve()
if out.exists():raise SystemExit('New output directory required')
out.mkdir(parents=True);work=out/'executor';work.mkdir();(work/'home/.config').mkdir(parents=True)
a=arguments(work);a.log_dir=out;a.nozzle_tmc_model='autobaud'
script,_=prepare(a,work,[],['emulation SetGlobalQuantum "0.000001"'])
setup=script.read_text().split('emulation RunFor "1"')[0]
capture=ROOT/'runs/native-ready-synthetic-z/rv-nozzle-tx.bin';data=capture.read_bytes()[:494]
decoded=list(frames(data));assert decoded[-1]['offset']==481 and decoded[-1]['length']==13 and decoded[-1]['decoded_hex']=='0d1750090706053cf650109d7e' and all(f['crc_valid'] for f in decoded)
(out/'captured-startup-through-constructor.bin').write_bytes(data)
replay_source=ROOT/'nozzle-renode/experimental/cs1237-native/CapturedStartupReplay.cs'
replay=work/'CapturedStartupReplay.cs';replay.write_text(replay_source.read_text().replace('Antmicro.Renode.Peripherals.AT32','Antmicro.Renode.Peripherals.PrinterNozzle'))
lines=[setup,'mach set "nozzle"',f'include @{replay}','machine LoadPlatformDescriptionFromString "constructorReplay: NozzleExperimental.CapturedStartupReplay @ sysbus { uart: usart1; interByteMicroseconds: 200 }"',
'emulation RunFor "0.4"',f'sysbus.constructorReplay Begin "{out}/captured-startup-through-constructor.bin"','emulation RunFor "0.13"',
f'sysbus.zForceBinding WriteStatus "{out}/z-binding-status.json"',final_commands(a),'echo "CONSTRUCTOR ONLY REPLAY COMPLETE"','quit']
script=work/'constructor.resc';script.write_text('\n'.join(lines)+'\n')
metadata={'scope':'Original3-MCU short standalone startup plus verbatim prefix of failing readiness UART through CS1237 constructor only; no phase-arm/home/heater/print. Does NOT replay original host timing.',
'capture_source':str(capture.relative_to(ROOT)),'capture_source_sha256':hashlib.sha256(capture.read_bytes()).hexdigest(),'selected_byte_range':[0,494],
'replay_sha256':hashlib.sha256(data).hexdigest(),'replay_begin_ns':400000000,'inter_byte_ns':200000,'first_byte_ns':400200000,'last_byte_ns':498800000,'end_ns':530000000,
'last_frame':decoded[-1],'binding_sha256':hashlib.sha256((ROOT/'printer-shared-mcu/experimental/z-force-cs1237-binding/Cs1237ZForceBinding.cs').read_bytes()).hexdigest(),
'replay_helper_source_sha256':hashlib.sha256(replay_source.read_bytes()).hexdigest(),'script_sha256':hashlib.sha256(script.read_bytes()).hexdigest()}
(out/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
env=dict(os.environ,HOME=str(work/'home'),XDG_CONFIG_HOME=str(work/'home/.config'),TMPDIR=str(work))
r=subprocess.run([str(ROOT/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(script)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=env,timeout=180)
(out/'renode.log').write_text(r.stdout)
print('Returncode',r.returncode,'completed', 'CONSTRUCTOR ONLY REPLAY COMPLETE' in r.stdout)
for name in ['z-binding-status.json','z-sensor-status.json','z-force-status.json']:
 print(name, (out/name).read_text() if (out/name).exists() else 'MISSING')
if r.returncode or 'CONSTRUCTOR ONLY REPLAY COMPLETE' not in r.stdout or 'There was an error' in r.stdout:raise SystemExit('Replay incomplete; inspect log')

import struct
sensor=json.loads((out/'z-sensor-status.json').read_text());force=json.loads((out/'z-force-status.json').read_text());binding=json.loads((out/'z-binding-status.json').read_text())
faults=struct.unpack('<II',(out/'final-nozzle-fault-words.bin').read_bytes())
healthy=bool(sensor['config']==60 and sensor['config_writes']==1 and sensor['read_words']>=1 and sensor['conversions']>2 and sensor['provider_calls']==sensor['conversions']
 and sensor['provider_failures']==sensor['protocol_errors']==sensor['adapter_errors']==0 and not force['faulted']
 and force['samples_read']==sensor['conversions'] and binding['first_failure']=='' and faults==(0,0))
(out/'result.json').write_text(json.dumps({'healthy_constructor_gate':healthy,'native_filter_stream_tested':sensor['read_words']>1,'homing_tested':False,'nozzle_cfsr':faults[0],'nozzle_hfsr':faults[1],'sensor':sensor,'force':force,'binding':binding},indent=2)+'\n')
if require_healthy and not healthy:raise SystemExit('Constructor sensor/history/fault gate failed')
