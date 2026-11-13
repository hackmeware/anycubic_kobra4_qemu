#!/usr/bin/env python3
"""Read ADC configuration objects from a nozzle v1.2.9 20KiB SRAM dump.
Layout established from the supplied image's disassembly, not arbitrary versions.
No memory or firmware is changed. Dumps may contain private configuration.
"""
import argparse, json, struct
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('sram',type=Path);p.add_argument('--main',action='store_true',help='main v1.3.3 96KiB dump');a=p.parse_args()
b=a.sram.read_bytes();base=0x20000000
expected=0x18000 if a.main else 0x5000
if len(b)!=expected: raise SystemExit('Expected '+hex(expected)+' bytes from SRAM base 0x20000000')
def u32(addr):
 o=addr-base
 if not 0<=o<=len(b)-4: raise ValueError('Pointer outside dump: '+hex(addr))
 return struct.unpack_from('<I',b,o)[0]
count=b[0x13c if a.main else 0x70];table=u32(base+(0x140 if a.main else 0x74));out=[]
for oid in range(count):
 entry=table+8*oid
 if u32(entry)!=(0x08006521 if a.main else 0x08006069):continue
 obj=u32(entry+4);o=obj-base
 if not 0<=o<=len(b)-44:raise ValueError('ADC object outside dump')
 channel=u32(obj+0x24)
 pins=['PA'+str(i) for i in range(8)]+['PB0','PB1']+['PC'+str(i) for i in range(6)]+['internal_temperature']
 out.append(dict(oid=oid,address=hex(obj),callback=hex(u32(obj+4)),adc=hex(u32(obj+0x20)),channel=channel,pin=pins[channel] if channel<len(pins) else 'unverified',sample_sum=struct.unpack_from('<H',b,o+0x18)[0],minimum_sum=struct.unpack_from('<H',b,o+0x1a)[0],maximum_sum=struct.unpack_from('<H',b,o+0x1c)[0],error_count=b[o+0x28],error_limit=b[o+0x29],sample_index=b[o+0x2a],sample_count=b[o+0x2b],sample_ticks=u32(obj+0x10),rest_ticks=u32(obj+0xc)))
print(json.dumps(dict(firmware='main_v1.3.3' if a.main else 'nozzle_v1.2.9',oid_count=count,oid_table=hex(table),adc_objects=out),indent=2))
