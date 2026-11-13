#!/usr/bin/env python3
"""Replay captured native motor frames unchanged and observe current/faults. No firmware writes."""
import argparse,json,pathlib,subprocess,struct
p=argparse.ArgumentParser();p.add_argument('--capture',type=pathlib.Path,default=pathlib.Path('rv1106-at32-link/test-results/three-mcu-electrical/main-motor-decoded.json'));p.add_argument('--output',type=pathlib.Path,default=pathlib.Path('motor-renode/tests/results/current-loop'));p.add_argument('--count',type=int,default=71);p.add_argument('--run',action='store_true');p.add_argument('--tail',type=float,default=.1);p.add_argument('--gap',type=float,default=.002);a=p.parse_args()
root=pathlib.Path(__file__).resolve().parents[1];out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
frames=json.loads(a.capture.read_text())['frames'][:a.count]
lines=['include @scripts/load.resc','include @scripts/board-clock-and-rtc.resc','include @scripts/generic-stationary-rl.resc','include @peripherals/AT32F403A_VirtualSerialWire.cs','include @tests/CurrentLoopTrace.cs','machine LoadPlatformDescriptionFromString "wire: AT32.AT32VirtualSerialWire @ sysbus { uart: usart2; baud: 576000 }"','machine LoadPlatformDescriptionFromString "trace: AT32Tests.CurrentLoopTrace @ sysbus { plant: rlPlant; tmr1: tmr1; tmr3: tmr3; tmr4: tmr4; tmr8: tmr8 }"','sysbus LoadBinary @/workspace/shared/kobra4-firmware/payload/motor_firmware_v1.6.01_20260313.bin 0x08008000','cpu VectorTableOffset 0x08008000',f'sysbus.usart2 CreateFileBackend @{out}/responses.bin','emulation RunFor "1"','sysbus.trace Start']
for index,frame in enumerate(frames):
 lines.extend(f'sysbus.wire WriteChar {b}' for b in bytes.fromhex(frame['frame_hex']))
 lines.extend([f'emulation RunFor "{a.gap}"',f'dump_file 0x20000c00 48 @{out}/faults-{index:03}.bin',f'dump_file 0x2000070c 96 @{out}/config-{index:03}.bin'])
lines.extend([f'emulation RunFor "{a.tail}"',f'dump_file 0x20000c00 48 @{out}/faults-final.bin',f'sysbus.trace Save "{out}/currents.csv"',f'dump_file 0x20004180 324 @{out}/control-final.bin',f'dump_file 0x20002038 1500 @{out}/measurement-final.bin','quit'])
script=out/'replay.resc';script.write_text('\n'.join(lines)+'\n');(out/'frames.json').write_text(json.dumps(frames,indent=2))
if not a.run: print(script);raise SystemExit
with (out/'renode.log').open('wb') as log: subprocess.run([str(root.parent/'at32-runtime/run-renode'),'--disable-xwt','--console',str(script)],cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=180,check=True)
for index,frame in enumerate(frames):
 data=(out/f'faults-{index:03}.bin').read_bytes();faults=[struct.unpack_from('<H',data,16*i)[0] for i in range(3)]
 if any(faults): print(index,frame['command'],frame['payload_hex'],[hex(f) for f in faults])
print('Final:',[hex(struct.unpack_from('<H',(out/'faults-final.bin').read_bytes(),16*i)[0]) for i in range(3)])
