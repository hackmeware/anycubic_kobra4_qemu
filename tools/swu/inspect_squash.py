"""Bounded read-only SquashFS4/XZ inventory. No mounting or guest execution."""
import hashlib,json,lzma,struct
from pathlib import Path
def u16(b,o):return struct.unpack_from('<H',b,o)[0]
def u32(b,o):return struct.unpack_from('<I',b,o)[0]
def u64(b,o):return struct.unpack_from('<Q',b,o)[0]
class SquashError(ValueError):pass
class Squash:
 def __init__(self,path,base=0,length=None):
  self.f=open(path,'rb');self.base=base;self.length=length or Path(path).stat().st_size
  h=self.read(0,96)
  if h[:4]!=b'hsqs' or u16(h,28)!=4 or u16(h,20)!=4:raise SquashError('only SquashFS4/XZ supported')
  self.inodes=u32(h,4);self.bs=u32(h,12);self.fragments=u32(h,16);self.root=u64(h,32);self.used=u64(h,40)
  self.it=u64(h,64);self.dt=u64(h,72);self.ft=u64(h,80)
  if self.used>self.length or self.bs>1024*1024:raise SquashError('size bound')
  self.cache={}
 def read(self,o,n):
  if o<0 or n<0 or o+n>self.length:raise SquashError('read outside image')
  self.f.seek(self.base+o);b=self.f.read(n)
  if len(b)!=n:raise SquashError('short read')
  return b
 def unpack(self,b,limit):
  obj=lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=64*1024*1024)
  out=obj.decompress(b,max_length=limit+1)
  if not obj.eof or obj.unused_data or len(out)>limit:raise SquashError('XZ bound/trailing data')
  return out
 def meta(self,absolute):
  if absolute in self.cache:return self.cache[absolute]
  h=u16(self.read(absolute,2),0);size=h&0x7fff
  if not size or size>8192:raise SquashError('metadata block bound')
  data=self.read(absolute+2,size);data=data if h&0x8000 else self.unpack(data,8192)
  result=(data,absolute+2+size);self.cache[absolute]=result;return result
 def mread(self,table,block,offset,size):
  if size<0 or size>16*1024*1024:raise SquashError('metadata request bound')
  result=[];absolute=table+block
  while size:
   data,nxt=self.meta(absolute)
   if offset>len(data):raise SquashError('metadata offset')
   n=min(size,len(data)-offset)
   if n==0:raise SquashError('metadata progress')
   result.append(data[offset:offset+n]);size-=n;offset=0;absolute=nxt
  return b''.join(result)
 def inode(self,ref):
  block,off=ref>>16,ref&0xffff;b=self.mread(self.it,block,off,16);typ=u16(b,0)
  r={'ref':ref,'kind':typ,'mode':u16(b,2),'uid_index':u16(b,4),'gid_index':u16(b,6),'mtime':u32(b,8),'ino':u32(b,12)}
  if typ in (1,8):
   b=self.mread(self.it,block,off,32 if typ==1 else 40)
   r.update(type='dir',start=u32(b,16 if typ==1 else 24),offset=u16(b,26 if typ==1 else 34),size=u16(b,24) if typ==1 else u32(b,20))
  elif typ in (2,9):
   b=self.mread(self.it,block,off,32 if typ==2 else 56)
   r.update(type='file',start=u32(b,16) if typ==2 else u64(b,16),size=u32(b,28) if typ==2 else u64(b,24),fragment=u32(b,20 if typ==2 else 44),fragment_offset=u32(b,24 if typ==2 else 48))
   n=r['size']//self.bs+(1 if r['fragment']==0xffffffff and r['size']%self.bs else 0)
   if n>self.length//self.bs+1:raise SquashError('block count')
   bs=self.mread(self.it,block,off+(32 if typ==2 else 56),n*4)
   r['blocks']=list(struct.unpack('<'+'I'*n,bs))
  elif typ in (3,10):
   b=self.mread(self.it,block,off,24);size=u32(b,20)
   if size>4096:raise SquashError('symlink size')
   r.update(type='symlink',target=self.mread(self.it,block,off+24,size).decode('utf8','surrogateescape'),size=size)
  else:r.update(type='special',size=0)
  return r
 def datablk(self,absolute,size):
  n=size&0xffffff
  if n>self.bs:raise SquashError('data block size')
  b=self.read(absolute,n)
  return b if size&0x1000000 else self.unpack(b,self.bs)
 def chunks(self,r):
  pos=r['start'];left=r['size']
  for size in r['blocks']:
   if size==0:b=bytes(min(left,self.bs))
   else:b=self.datablk(pos,size);pos+=size&0xffffff
   if len(b)>left:raise SquashError('data too long')
   yield b;left-=len(b)
  if left:
   index=r['fragment']
   if index>=self.fragments:raise SquashError('fragment index')
   pointer=u64(self.read(self.ft+(index*16//8192)*8,8),0)
   b=self.mread(pointer,0,index*16%8192,16);frag=self.datablk(u64(b,0),u32(b,8));start=r['fragment_offset']
   if start+left>len(frag):raise SquashError('fragment range')
   yield frag[start:start+left]
 def children(self,r):
  b=self.mread(self.dt,r['start'],r['offset'],r['size']-3);p=0;out=[]
  while p<len(b):
   if p+12>len(b):raise SquashError('dir header short')
   count=u32(b,p)+1;start=u32(b,p+4);p+=12
   if count>256:raise SquashError('dir count')
   for _ in range(count):
    if p+8>len(b):raise SquashError('dir entry short')
    off=u16(b,p);size=u16(b,p+6)+1;p+=8
    name=b[p:p+size];p+=size
    if len(name)!=size or b'/' in name or name in (b'',b'.',b'..') or b'\0' in name:raise SquashError('dir name')
    out.append((name.decode('utf8','surrogateescape'),(start<<16)|off))
  return out
 def inventory(self):
  stack=[('',self.root)];rows=[];dirs=set()
  while stack:
   path,ref=stack.pop();r=self.inode(ref);r['path']=path
   if r['type']=='dir':
    if ref in dirs:raise SquashError('dir loop')
    dirs.add(ref)
    for name,child in reversed(self.children(r)):stack.append((path+'/'+name if path else name,child))
   elif r['type']=='file':
    h=hashlib.sha256();size=0
    for b in self.chunks(r):h.update(b);size+=len(b)
    if size!=r['size']:raise SquashError('file size mismatch')
    r['sha256']=h.hexdigest()
   rows.append(r)
   if len(rows)>100000:raise SquashError('inventory limit')
  return rows
if __name__=='__main__':
 base=Path('kobra_compact_20261112/importer_work/next');source=Path('kobra_compact_20261112/recovered/project/calibration-native-fast4-c22-stop-event/inputs/offline-emmc.img')
 sq=Squash(source,45056*512,32768*512);rows=sq.inventory()
 (base/'system-r9-inventory.json').write_text(json.dumps(rows,indent=2))
 print('inodes',sq.inodes,'entries',len(rows))
 for r in rows:
  if r['path']=='emulation-init.sh':
   data=b''.join(sq.chunks(r));(base/'original-diagnostic-emulation-init.sh.txt').write_bytes(data);print('emulation-init.sh',r['size'],r['sha256'])
