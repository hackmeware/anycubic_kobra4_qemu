#!/usr/bin/env python3
"""Query status from the original motor image with an explicit stationary-current plant.
No firmware or state bytes are patched. This validates replies, not a healthy motor.
"""
import argparse, hashlib, json, os, pathlib, struct, subprocess, tempfile
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('firmware',type=pathlib.Path)
p.add_argument('--renode',type=pathlib.Path,default=pathlib.Path(__file__).resolve().parents[2]/'at32-runtime/run-renode')
p.add_argument('--output',type=pathlib.Path,default=pathlib.Path(__file__).resolve().parent/'status-results')
p.add_argument('--no-idle',action='store_true',help='Do not inject an explicit UART idle event')
p.add_argument('--electrical',action='store_true',help='Use generic parameterized stationary RL plant, not constant zero-current fixture')
a=p.parse_args();fw=a.firmware.resolve();root=pathlib.Path(__file__).resolve().parents[1];out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
expected='76b439293ab08207317007f5179243a0684c1b27668442781bcb2e201ff62661'
if hashlib.sha256(fw.read_bytes()).hexdigest()!=expected:raise SystemExit('Firmware hash does not match the analyzed motor image')
if any(c.isspace() for c in str(fw)+str(out)):raise SystemExit('Use paths without whitespace')
def crc16(data):
 c=65535
 for v in data:
  v^=c&255;v^=(v&15)<<4;c=(((v<<8)|(c>>8))^(v>>4)^(v<<3))&65535
 return c
lines=['include @scripts/load.resc','include @scripts/board-clock-and-rtc.resc','include @scripts/generic-stationary-rl.resc' if a.electrical else 'include @scripts/stationary-current-plant.resc','include @peripherals/AT32F403A_VirtualSerialWire.cs','machine LoadPlatformDescriptionFromString "motorWire: AT32.AT32VirtualSerialWire @ sysbus { uart: usart2; baud: 576000 }"',f'sysbus LoadBinary @{fw} 0x08008000','cpu VectorTableOffset 0x08008000',f'sysbus.usart2 CreateFileBackend @{out}/uart-replies.bin','emulation RunFor "1"' if a.electrical else 'emulation RunFor "0.5"']
for seq,mask in enumerate([1,2,4,7]):
 frame=bytes([126,seq,37,2,2,mask]);frame+=crc16(frame).to_bytes(2,'little')
 lines += [f'sysbus.motorWire WriteChar {b}' for b in frame]
 lines += ['emulation RunFor "0.001"']
 if not a.no_idle: lines += ['sysbus.usart2 SignalIdle']
 lines += ['emulation RunFor "0.002"']
lines += [f'dump_file 0x20000C00 0x30 @{out}/motor-status.bin',f'dump_file 0xE000ED28 8 @{out}/cpu-faults.bin','quit']
resc=out/'query.resc';resc.write_text('\n'.join(lines)+'\n')
env=dict(os.environ,TMPDIR=tempfile.mkdtemp(prefix='motor-status-'))
with (out/'renode.log').open('wb') as log:
 subprocess.run([str(a.renode.resolve()),'--disable-gui','--console',str(resc)],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=120,check=True)
data=(out/'uart-replies.bin').read_bytes();frames=[];i=0
while i<len(data):
 assert data[i]==126,('invalid header',i)
 length=data[i+2]+5;frame=data[i:i+length]
 assert len(frame)==length and crc16(frame[:-2])==int.from_bytes(frame[-2:],'little'),'bad response CRC'
 frames.append((frame[1],frame[3:-2]));i+=length
status=(out/'motor-status.bin').read_bytes();words=[struct.unpack_from('<H',status,n*16)[0] for n in range(3)]
responses=[payload for command,payload in frames if command==0x26]
assert len(responses)==4,frames
for payload,mask in zip(responses,[1,2,4,7]):
 selected=[words[n] for n in range(3) if mask&(1<<n)]
 assert payload==bytes([2,mask])+b''.join(struct.pack('<H',v) for v in selected),(payload,mask,words)
assert len([1 for command,_ in frames if command==0x12])==4,'missing ACK'
assert (out/'cpu-faults.bin').read_bytes()==bytes(8),'CPU fault'
result={'firmware_sha256':expected,'original_firmware_executed':True,'request_command':37,'response_command':38,'masks':[1,2,4,7],'status_words':words,'response_crc_verified':True,'responses_match_runtime_status':True,'cpu_faults':False,'healthy_motor_claim':False,'explicit_idle_notification':not a.no_idle,'plant':'generic_stationary_RL' if a.electrical else 'stationary_zero_current','assumptions':['AT32-compatible register hypothesis, exact FCES silicon unverified','24MHz HEXT and pre-enabled low-speed RTC oscillator','generic stationary RL coils: 24V, 2ohm, 3mH, 500ADC counts/A, no rotor/mechanical dynamics' if a.electrical else 'stationary zero-current ADC inputs 2048, no encoder or mechanical plant']}
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2));print('PASS: original motor replies match actual runtime status; status is not forced healthy.')
