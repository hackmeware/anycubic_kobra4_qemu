"""Project-owned ARM helper generation; no file writes or guest execution."""
import struct
BASE=0x10000;CODE=BASE+0x100
words=[];literals=[];fixups=[]
def emit(v):words.append(v)
def mov(reg,value):
 if isinstance(value,int) and 0<=value<=255:emit(0xe3a00000|(reg<<12)|value)
 else:
  fixups.append((len(words),reg,value));emit(0)
def syscall(n):mov(7,n);emit(0xef000000)
def ioctl(req,arg):emit(0xe1a00004);mov(1,req);mov(2,arg);syscall(54)
# literal pointers use string labels resolved below
mov(0,'path');mov(1,2|0x800);syscall(5);emit(0xe1a04000)
for typ in [0,1,3]:ioctl(0x40045564,typ)
ioctl(0x40045565,330)
for axis in [0,1]:ioctl(0x40045567,axis)
emit(0xe1a00004);mov(1,'device');mov(2,1116);syscall(4)
ioctl(0x5501,0)
# Read standard Linux input_event records from a guest FIFO and pass through.
mov(0,'fifo');mov(1,2);syscall(5);emit(0xe1a05000)
loop=len(words)
emit(0xe1a00005);mov(1,'event');mov(2,16);syscall(3)
emit(0xe3500010) # cmp r0,#16
branch=len(words);emit(0x1a000000|((loop-branch-2)&0xffffff)) # bne read
emit(0xe1a00004);mov(1,'event');mov(2,16);syscall(4)
branch=len(words);emit(0xea000000|((loop-branch-2)&0xffffff))
code_bytes=len(words)*4;pool_start=CODE+code_bytes
path=b'/dev/uinput\0';path+=b'\0'*((-len(path))%4)
device=bytearray(1116);device[:24]=b'RV1106 diagnostic touch\0';struct.pack_into('<HHHHI',device,80,3,0x1209,0x1106,1,0);struct.pack_into('<ii',device,92,479,319)
fifo=b'/tmp/touch-events\0';fifo+=b'\0'*((-len(fifo))%4)
labels={'path':pool_start+len(fixups)*4,'device':pool_start+len(fixups)*4+len(path)}
labels['fifo']=labels['device']+len(device);labels['event']=labels['fifo']+len(fifo)
for k,(index,reg,val) in enumerate(fixups):
 addr=pool_start+k*4;delta=addr-(CODE+index*4+8);assert 0<=delta<=4095
 words[index]=0xe59f0000|(reg<<12)|delta;literals.append(labels[val] if isinstance(val,str) else val)
body=struct.pack('<'+'I'*len(words),*words)+struct.pack('<'+'I'*len(literals),*literals)+path+device+fifo+bytes(16)
hdr=b'\x7fELF'+bytes([1,1,1])+bytes(9)+struct.pack('<HHIIIIIHHHHHH',2,40,1,CODE,52,0,0x5000200,52,32,1,0,0,0)
ph=struct.pack('<8I',1,0,BASE,BASE,0x100+len(body),0x100+len(body),7,0x1000)
elf=hdr+ph;elf+=bytes(0x100-len(elf))+body

def build():
    return elf
