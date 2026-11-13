#!/usr/bin/env python3
"""Read-only main-v1.3.3 configured step/dir objects. No semantic axis inference."""
import argparse, hashlib, json, struct
from pathlib import Path
FIRMWARE_SHA='9bd702c8a076f29c0ac019cc7c8ea6c7afa52d13580fea04e977e3dce0a5d517'
def inspect(firmware,sram):
 f=Path(firmware).read_bytes(); b=Path(sram).read_bytes()
 if hashlib.sha256(f).hexdigest()!=FIRMWARE_SHA: raise ValueError('Unrecognized firmware; refusing offsets')
 if len(b)!=0x18000: raise ValueError('Expected main SRAM base 0x20000000, length 96 KiB')
 def u32(a):
  o=a-0x20000000
  if not 0<=o<=len(b)-4: raise ValueError('Pointer outside SRAM')
  return struct.unpack_from('<I',b,o)[0]
 def pin(base,mask):
  if base not in range(0x40010800,0x40012400,0x400) or mask==0 or mask>0x8000 or mask&(mask-1): raise ValueError('Invalid GPIO descriptor')
  port=(base-0x40010800)//0x400;bit=mask.bit_length()-1
  return dict(pin=f'P{chr(65+port)}{bit}',gpio=hex(base),mask=hex(mask),bonded_in_assumed_RGT7=(port<=2 or port==3 and bit<=2))
 count=b[0x13c];table=u32(0x20000140);objects=[]
 for oid in range(count):
  constructor=u32(table+oid*8)
  if constructor!=0x0800599d: continue
  obj=u32(table+oid*8+4)
  objects.append(dict(oid=oid,address=hex(obj),step=pin(u32(obj+0x20),u32(obj+0x24)),direction=pin(u32(obj+0x28),u32(obj+0x2c)),flags=b[obj-0x20000000+0x44],runtime_mode=b[obj-0x20000000+0x4d],runtime_route={1:"GPIO step path",2:"motor serial command path"}.get(b[obj-0x20000000+0x4d],"unverified"),motor_index=b[obj-0x20000000+0x45] if b[obj-0x20000000+0x4d]==2 else None,semantic_axis=None,steps_per_mm=None,enable_pin=None))
 return dict(firmware_sha256=FIRMWARE_SHA,sram_sha256=hashlib.sha256(b).hexdigest(),oid_count=count,stepper_objects=objects,scope='Configured software GPIO identities; not verified physical board wiring or axis semantics')
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('firmware');p.add_argument('sram');a=p.parse_args();print(json.dumps(inspect(a.firmware,a.sram),indent=2))
