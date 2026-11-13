#!/usr/bin/env python3
"""Extract only heater configuration evidence from an existing local runtime RAM capture.
No process modification, decryption, firmware patching, or host communication.
Page mappings are validated by the target STL key and remain page-local.
"""
import argparse, hashlib, json, pathlib, struct
p=argparse.ArgumentParser();p.add_argument('capture',type=pathlib.Path);p.add_argument('--output',type=pathlib.Path);a=p.parse_args();b=a.capture.read_bytes()
pages={0x1b5a000:0x15d6000,0x1b5b000:0x1d7b000}
def offset(v):
    page=v&~4095
    if page not in pages:raise ValueError(f'unverified page: {page:x}')
    return pages[page]+(v&4095)
def u(v):return struct.unpack_from('<I',b,offset(v))[0]
def string(v):
    ptr,n=u(v),u(v+4)
    if n>100:raise ValueError('unexpected string length')
    off=offset(ptr)
    if (ptr&4095)+n>4096:raise ValueError('cross-page string refused')
    return b[off:off+n].decode('ascii')
def node(addr,key):
    assert string(addr+16)==key,(hex(addr),key)
    assert u(addr+40)&255==3,'not a string variant'
    return dict(key=key,value=string(u(addr+48)),node_virtual=f'0x{addr:x}',node_file_offset=f'0x{offset(addr):x}')
result={'source':str(a.capture),'sha256':hashlib.sha256(b).hexdigest(),'method':'Page-local STL string nodes; firmware/application runtime data, not physical board calibration','bed':[node(0x1b5b208,'heater_pin'),node(0x1b5b280,'sensor_type'),node(0x1b5b2e0,'sensor_pin'),node(0x1b5b778,'max_safe_temp'),node(0x1b5b7d8,'max_temp')],'nozzle':[node(0x1b5acb0,'heater_pin'),node(0x1b5ad50,'sensor_type'),node(0x1b5ad90,'sensor_pin')],'limitations':['Section identification is corroborated by bed/nozzle pin and sensor names, with tree reconstruction performed separately.','No thermistor coefficients for the custom nozzle NTC or board pullup resistance are recovered here.','Causal command-to-GPIO validation is still required before connecting a thermal plant.']}
s=json.dumps(result,indent=2)+'\n'
if a.output:a.output.write_text(s)
else:print(s,end='')
