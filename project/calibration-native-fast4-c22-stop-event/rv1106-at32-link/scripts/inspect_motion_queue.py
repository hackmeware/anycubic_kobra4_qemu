#!/usr/bin/env python3
"""Read-only observation of original main MCU mode-2 motor commands.
Counts transmitted requests, NOT accepted/executed motion or a completed print.
"""
import argparse,hashlib,json,struct
from pathlib import Path
from decode_motor_frames import decode
AXES={0:('x',3200/39,True),1:('y',3200/39,False),2:('z',400,False)}
def inspect(data):
 directions={};events=[];totals={a:{'transmitted_step_count':0,'signed_steps_with_known_direction':0,'steps_with_unknown_direction':0} for a,_,_ in AXES.values()}
 for frame in decode(data,False):
  command=frame['command'];p=bytes.fromhex(frame['payload_hex']);base={'offset':frame['offset'],'command':command}
  if command not in (4,5,17):continue
  expected={4:2,5:13,17:1}[command]
  if len(p)!=expected:raise ValueError(f'Unexpected command {command} payload length {len(p)}')
  index=p[0]
  if index not in AXES:raise ValueError(f'Unknown motor index {index}')
  axis,scale,invert=AXES[index];base.update(axis=axis,motor_index=index)
  if command==4:
   if p[1] not in (0,1):raise ValueError('Unexpected direction encoding')
   directions[index]=bool(p[1]);base.update(kind='direction_request',direction_level=p[1])
  elif command==17:
   base.update(kind='clock_reset_request')
  else:
   _,interval,count,add,clock=struct.unpack('<BIHhI',p)
   base.update(kind='queue_request',interval_ticks=interval,count=count,interval_add_ticks=add,main_clock_sample=clock)
   totals[axis]['transmitted_step_count']+=count
   if index in directions:
    signed=count*(1 if directions[index]^invert else -1)
    totals[axis]['signed_steps_with_known_direction']+=signed
    base.update(signed_steps=signed,requested_travel_mm=signed/scale)
   else:totals[axis]['steps_with_unknown_direction']+=count
  events.append(base)
 return {'capture_sha256':hashlib.sha256(data).hexdigest(),'scope':'Transmitted motor requests only. No acknowledgement, execution, enable, homing, synchronization or physical movement inferred. Retransmissions are not deduplicated.','axis_mapping_source':'Native console OIDs9/12/15=X/Y/Z and initialized main object+0x45 motor indices0/1/2','totals':totals,'events':events}
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('capture',type=Path);a=p.parse_args();print(json.dumps(inspect(a.capture.read_bytes()),indent=2))
