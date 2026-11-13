import struct
from pathlib import Path
b=bytearray(0x100);struct.pack_into('<II',b,0,0x20001000,0x08000101)
code=[];pool=[];fix=[]
def load(reg,v):fix.append((len(code),reg,len(pool)));code.append(0);pool.append(v)
def write(a,v):load(0,a);load(1,v);code.append(0x6001)
write(0x40010804,0x44444441);write(0x4000440c,0x2008);write(0x40010810,0x100);write(0x40004404,0x5a)
code.append(0xe7fe)
if len(code)%2:code.append(0xbf00)
for i,r,p in fix:
 pc=(0x100+i*2+4)&~3;addr=0x100+len(code)*2+p*4;code[i]=0x4800|(r<<8)|((addr-pc)//4)
b.extend(struct.pack('<'+'H'*len(code),*code));b.extend(struct.pack('<'+'I'*len(pool),*pool));Path(__file__).with_name('wire-smoke.bin').write_bytes(b)
