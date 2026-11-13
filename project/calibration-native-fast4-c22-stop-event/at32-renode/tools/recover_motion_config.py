#!/usr/bin/env python3
"""Read-only, hash-bound extraction of motion configuration from a known native RAM capture.
Only motion/driver settings are emitted. Does not change firmware/configuration.
"""
import argparse,collections,hashlib,json,struct
from pathlib import Path
EXPECTED='915424f5dc77b05510509d78b9eab3ad602e6ed6ea2ae707df67bbc02d1ecfaa'
HEADERS={'x':0x1bbb07c,'y':0x1b5a14c,'z':0x1bb677c,'extruder':0x1bb6ea4,'kinematics':0x1bb2274,'tmc_x':0x1b5b904,'tmc_y':0x1bb95cc}
COPIES={'x':[0x1bbe76c,0x1bb2cdc],'y':[0x1bbe3ec,0x1bb0674],'z':[0x1badd04,0x1bbf7b4],'extruder':[0x1baed34,0x1bbfedc],'kinematics':[0x1badbe4,0x1bb5f34]}
def recover(path):
 b=Path(path).read_bytes();digest=hashlib.sha256(b).hexdigest()
 if digest!=EXPECTED:raise ValueError('Unknown RAM capture: this extractor is bound to a verified input hash')
 votes=collections.defaultdict(collections.Counter)
 # ARM libstdc++ inline strings carry a pointer to their own +8 payload.
 # Such a pointer supplies virtual/physical page correspondence, not a fixed RAM delta.
 for p in range(0,len(b)-24,4):
  ptr,n=struct.unpack_from('<II',b,p)
  if not (0x1b50000<=ptr<0x1c00000 and 1<=n<=15 and ptr&4095==(p+8)&4095):continue
  if b[p+8+n]==0 and all(32<=c<127 for c in b[p+8:p+8+n]):votes[ptr>>12][p>>12]+=1
 pages={}
 for vp,counts in votes.items():
  ranked=counts.most_common()
  if ranked[0][1]>=2 and (len(ranked)==1 or ranked[0][1]>ranked[1][1]):pages[vp]=ranked[0][0]
 def off(a):return pages[a>>12]*4096+(a&4095)
 def u(a):return struct.unpack_from('<I',b,off(a))[0]
 def string(a):
  ptr,n=u(a),u(a+4)
  if n>256:raise ValueError('Unexpected string size')
  v=bytes(b[off(ptr+i)] for i in range(n))
  if not all(32<=c<127 for c in v):raise ValueError('Unexpected string bytes')
  return v.decode()
 def tree(header):
  result={};evidence=[];seen=set()
  def walk(a,parent):
   if a==0:return
   if a in seen or u(a)>1 or u(a+4)!=parent:raise ValueError('Invalid map tree')
   seen.add(a);walk(u(a+8),a)
   if u(a+40)&255!=3:raise ValueError('Nonstring map value')
   k=string(a+16);v=string(u(a+48))
   if k in result:raise ValueError('Duplicate key')
   result[k]=v;evidence.append({'node_virtual':hex(a),'node_file_offset':hex(off(a)),'key':k,'value':v})
   walk(u(a+12),a)
  walk(u(header+4),header)
  if len(result)!=u(header+16) or list(result)!=sorted(result):raise ValueError('Map count/order mismatch')
  return result,evidence
 sections={}
 for name,header in HEADERS.items():
  values,evidence=tree(header);checked=[]
  for other in COPIES.get(name,[]):
   duplicate,_=tree(other)
   if duplicate!=values:raise ValueError('Independent configuration copy differs: '+name)
   checked.append(hex(other))
  sections[name]={'header_virtual':hex(header),'values':values,'nodes':evidence,'matching_copy_headers':checked}
 return {'ram_sha256':digest,'method':'SSO self-pointer page mapping + validated ordered parent-linked map trees + matching independent copies','sections':sections,'page_map':{hex(k*4096):hex(v*4096) for k,v in sorted(pages.items())},'scope':'Original host configuration, not measured physical machine calibration or successful motion'}
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('ram',type=Path);a=p.parse_args();print(json.dumps(recover(a.ram),indent=2))
