"""Build own ARM Linux ioctl verifier for input ABS_X/Y ranges; never execute."""
import struct
def build():
 words=[];fix=[];labels={};branches=[]
 def emit(v):words.append(v)
 def mov(r,v):
  if isinstance(v,int) and 0<=v<=255:emit(0xe3a00000|(r<<12)|v)
  else:fix.append((len(words),r,v));emit(0)
 def syscall(n):mov(7,n);emit(0xef000000)
 def branch(cond,target):branches.append((len(words),cond,target));emit(0)
 def eqfail():branch(1,'fail')
 mov(0,'path');mov(1,0);syscall(5);emit(0xe3500000);branch(4,'fail');emit(0xe1a04000)
 for code,maximum in [(0x80184540,479),(0x80184541,319)]:
  emit(0xe1a00004);mov(1,code);mov(2,'buf');syscall(54);emit(0xe3500000);branch(4,'fail')
  mov(2,'buf');emit(0xe5920004);emit(0xe3500000);eqfail()
  emit(0xe5920008);mov(1,maximum);emit(0xe1500001);eqfail()
 mov(0,1);mov(1,'ok');mov(2,len(b'TOUCH_RANGE_VERIFIED\n'));syscall(4);mov(0,0);syscall(1)
 labels['fail']=len(words);mov(0,1);syscall(1)
 base=0x10100;pool=base+len(words)*4
 payload=b'/tmp/diagnostic-event\0';payload+=bytes((-len(payload))%4)
 data={'path':pool+len(fix)*4,'buf':pool+len(fix)*4+len(payload)};payload+=bytes(24);data['ok']=pool+len(fix)*4+len(payload);payload+=b'TOUCH_RANGE_VERIFIED\n'
 literals=[]
 for i,r,v in fix:
  delta=pool+len(literals)*4-(base+i*4+8);assert 0<=delta<=4095
  words[i]=0xe59f0000|(r<<12)|delta;literals.append(data[v] if isinstance(v,str) else v)
 for i,c,target in branches:words[i]=(c<<28)|0x0a000000|((labels[target]-i-2)&0xffffff)
 body=struct.pack('<'+'I'*len(words),*words)+struct.pack('<'+'I'*len(literals),*literals)+payload
 h=b'\x7fELF'+bytes([1,1,1])+bytes(9)+struct.pack('<HHIIIIIHHHHHH',2,40,1,base,52,0,0x5000200,52,32,1,0,0,0)
 h+=struct.pack('<8I',1,0,0x10000,0x10000,256+len(body),256+len(body),7,4096)
 return h+bytes(256-len(h))+body
