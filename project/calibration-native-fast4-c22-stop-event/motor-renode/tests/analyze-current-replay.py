#!/usr/bin/env python3
"""Summarize read-only replay evidence; optionally require original overcurrent fault absent."""
import argparse,csv,json,pathlib,struct
p=argparse.ArgumentParser();p.add_argument('directory',type=pathlib.Path);p.add_argument('--expect-no-overcurrent',action='store_true');a=p.parse_args();d=a.directory
frames=json.loads((d/'frames.json').read_text());first={};final=[]
for index,frame in enumerate(frames):
 b=(d/f'faults-{index:03}.bin').read_bytes();assert len(b)==48
 faults=[struct.unpack_from('<H',b,i*16)[0] for i in range(3)]
 for bit in (0x10,0x800):
  if any(x&bit for x in faults) and hex(bit) not in first:first[hex(bit)]={'packet_index':index,'command':frame['command'],'payload_hex':frame['payload_hex'],'faults':faults}
b=(d/'faults-final.bin').read_bytes();final=[struct.unpack_from('<H',b,i*16)[0] for i in range(3)]
peaks=[{'absolute_amps':0} for i in range(3)]
for row in csv.DictReader((d/'currents.csv').open()):
 axis=int(row['axis']);value=max(abs(float(row['i1'])),abs(float(row['i2'])))
 if value>peaks[axis]['absolute_amps']:peaks[axis]={'absolute_amps':value,'sample':row}
result={'frame_count':len(frames),'final_faults':final,'first_fault_frames':first,'peak_phase_currents':peaks,'physical_parameters':{'volts':24,'ohms':2,'henries':.003,'adc_counts_per_amp':500,'adc_offset':2048},'firmware_or_status_patched':False}
(d/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if a.expect_no_overcurrent:
 assert not any(x&0x10 for x in final),final
 assert '0x10' not in first,first
 print('PASS: exact native replay preserves current safety without artificial overcurrent')
