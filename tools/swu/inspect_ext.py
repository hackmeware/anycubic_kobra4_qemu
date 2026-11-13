"""Read-only bounded ext filesystem inventory; never mounts or executes guest code."""
import hashlib,json,math,struct
from pathlib import Path
class ExtError(ValueError): pass
def u16(b,o):return struct.unpack_from('<H',b,o)[0]
def u32(b,o):return struct.unpack_from('<I',b,o)[0]
class Ext:
 def __init__(self,image,offset,length):
  self.f=open(image,'rb');self.base=offset;self.length=length
  s=self.read(1024,1024)
  if u16(s,56)!=0xef53:raise ExtError('not ext')
  self.bs=1024<<u32(s,24);self.inodes=u32(s,0);self.blocks=u32(s,4)
  self.ipg=u32(s,40);self.bpg=u32(s,32);self.isize=u16(s,88) or 128
  self.incompat=u32(s,96);self.compat=u32(s,92);self.ro=u32(s,100)
  self.desc=max(32,u16(s,254)) if self.incompat&0x80 else 32
  if self.bs not in (1024,2048,4096) or self.isize<128 or self.isize>self.bs:raise ExtError('unsupported geometry')
  if self.incompat&(0x10|0x8000):raise ExtError('meta_bg/inline_data unsupported')
  if self.incompat&0x80:self.blocks|=u32(s,336)<<32
  self.summary={'block_size':self.bs,'blocks':self.blocks,'inode_size':self.isize,'inodes':self.inodes,'features_compat':hex(self.compat),'features_incompat':hex(self.incompat),'features_ro':hex(self.ro),'uuid':s[104:120].hex(),'label':s[120:136].rstrip(b'\0').decode('utf8','replace'),'created_time':u32(s,264),'last_write_time':u32(s,48),'mount_count':u16(s,52),'state':u16(s,58)}
 def read(self,offset,n):
  if offset<0 or n<0 or offset+n>self.length:raise ExtError('out of bounds')
  self.f.seek(self.base+offset);b=self.f.read(n)
  if len(b)!=n:raise ExtError('truncated')
  return b
 def block(self,b):
  if b>=self.blocks:raise ExtError('block outside filesystem')
  return self.read(b*self.bs,self.bs)
 def inode(self,n):
  if n<1 or n>self.inodes:raise ExtError('inode out of range')
  g,i=divmod(n-1,self.ipg);gd=self.read((2 if self.bs==1024 else 1)*self.bs+g*self.desc,self.desc)
  table=u32(gd,8)
  if self.desc>=64:table|=u32(gd,40)<<32
  b=self.read(table*self.bs+i*self.isize,self.isize);mode=u16(b,0);size=u32(b,4)
  if mode&0xf000==0x8000:size|=u32(b,108)<<32
  return {'ino':n,'mode':mode,'size':size,'flags':u32(b,32),'uid':u16(b,2)|(u16(b,120)<<16),'gid':u16(b,24)|(u16(b,122)<<16),'mtime':u32(b,16),'links':u16(b,26),'raw':b}
 def extents(self,data,depthlimit=6):
  if u16(data,0)!=0xf30a:raise ExtError('bad extent magic')
  n,maxn,depth=u16(data,2),u16(data,4),u16(data,6)
  if depth>depthlimit or n>maxn or 12+12*n>len(data):raise ExtError('bad extent header')
  result=[]
  for i in range(n):
   p=12+12*i;logical=u32(data,p)
   if depth:
    physical=u32(data,p+4)|(u16(data,p+8)<<32)
    result.extend(self.extents(self.block(physical),depth-1))
   else:
    length=u16(data,p+4);unwritten=length>32768
    if unwritten:length-=32768
    physical=u32(data,p+8)|(u16(data,p+6)<<32)
    result.append((logical,length,physical,unwritten))
  return result
 def chunks(self,node):
  size=node['size'];b=node['raw']
  if size>self.length:raise ExtError('file too large')
  if node['mode']&0xf000==0xa000 and size<=60 and u32(b,28)==0:
   yield b[40:40+size];return
  if node['flags']&0x80000:
   ext=sorted(self.extents(b[40:100]))
   pos=0
   for logical,count,physical,unwritten in ext:
    start=logical*self.bs
    if start<pos:raise ExtError('overlap')
    if start>=size:break
    while pos<start:
     n=min(self.bs,start-pos,size-pos);yield bytes(n);pos+=n
    for k in range(count):
     if pos>=size:break
     block=bytes(self.bs) if unwritten else self.block(physical+k)
     n=min(self.bs,size-pos);yield block[:n];pos+=n
   while pos<size:
    n=min(self.bs,size-pos);yield bytes(n);pos+=n
  else:
   pointers=list(struct.unpack('<15I',b[40:100]))
   needed=(size+self.bs-1)//self.bs
   if needed>12+self.bs//4:raise ExtError('legacy doubly indirect not supported')
   mapping=pointers[:12]
   if needed>12 and pointers[12]:mapping+=list(struct.unpack('<'+'I'*(self.bs//4),self.block(pointers[12])))
   pos=0
   for physical in mapping[:needed]:
    data=self.block(physical) if physical else bytes(self.bs);n=min(self.bs,size-pos);yield data[:n];pos+=n
   if pos!=size:raise ExtError('legacy map short')
 def data(self,node,maxsize=16*1024*1024):
  if node['size']>maxsize:raise ExtError('buffered file too large')
  return b''.join(self.chunks(node))
 def children(self,node):
  data=self.data(node);out=[]
  for blockoff in range(0,len(data),self.bs):
   p=blockoff;end=min(blockoff+self.bs,len(data))
   while p+8<=end:
    ino=u32(data,p);rec=u16(data,p+4);ln=data[p+6]
    if rec<8 or rec%4 or p+rec>end or ln>rec-8:raise ExtError('bad directory record')
    name=data[p+8:p+8+ln]
    if ino and name not in (b'.',b'..'):
     if b'/' in name or b'\0' in name:raise ExtError('bad directory name')
     out.append((name.decode('utf8','surrogateescape'),ino))
    p+=rec
  return out
 def inventory(self):
  rows=[];seen_dirs=set();stack=[('',2)]
  while stack:
   path,ino=stack.pop();n=self.inode(ino);typ=n['mode']&0xf000
   r={k:v for k,v in n.items() if k!='raw'};r['path']=path;r['type']={0x4000:'dir',0x8000:'file',0xa000:'symlink'}.get(typ,'special')
   if typ==0x4000:
    if ino in seen_dirs:raise ExtError('directory loop')
    seen_dirs.add(ino)
    for name,child in reversed(self.children(n)):stack.append((path+'/'+name if path else name,child))
   elif typ==0x8000:
    h=hashlib.sha256()
    for b in self.chunks(n):h.update(b)
    r['sha256']=h.hexdigest()
   elif typ==0xa000:r['target']=self.data(n).decode('utf8','surrogateescape')
   rows.append(r)
   if len(rows)>100000:raise ExtError('inventory limit')
  return rows
if __name__=='__main__':
 root=Path('kobra_compact_20261112/recovered/project/calibration-native-fast4-c22-stop-event/inputs')
 layout=json.loads((root/'disk-layout.json').read_text());out=Path('kobra_compact_20261112/importer_work/next')
 report={}
 for p in layout['partitions']:
  if not str(p.get('source')).endswith('.ext4'):continue
  ext=Ext(root/'offline-emmc.img',p['start_sector']*512,p['sectors']*512);rows=ext.inventory()
  result={'partition':p,'superblock':ext.summary,'entries':rows}
  (out/(p['name']+'-inventory.json')).write_text(json.dumps(result,indent=2,ensure_ascii=True)+'\n')
  report[p['name']]={'summary':ext.summary,'entries':len(rows),'regular_files':sum(r['type']=='file' for r in rows),'payload_bytes':sum(r['size'] for r in rows if r['type']=='file'),'top_level':[(r['path'],r['type'],r['size']) for r in rows if '/' not in r['path']]}
 (out/'EXT-SUMMARY.json').write_text(json.dumps(report,indent=2))
 print(json.dumps(report))
