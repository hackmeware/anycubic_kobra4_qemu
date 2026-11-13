#!/usr/bin/env python3
"""Build a tiny ARM Linux h2c probe for verified diagnostic RPC schemas.
No TLS, no network beyond guest loopback, no generic external client.
"""
import pathlib,struct,argparse
p=argparse.ArgumentParser();p.add_argument('--script',default='M115\nM105');p.add_argument('--timeout-seconds',type=int,choices=range(1,31),default=5);p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--method',choices=['RunGcodeScript','StartPrint','PrinterState','ExtruderPreheating','Homing'],default='RunGcodeScript');p.add_argument('--file-path',default='/data/gcodes');p.add_argument('--file-name',default='diagnostic.gcode');p.add_argument('--temperature-c',type=int,choices=range(0,36),help='ExtruderPreheating diagnostic target only, 0 through 35 C');p.add_argument('--homing-axis',choices=['X','Y'],help='Verified diagnostic normal Homing request, explicit X or Y only');a=p.parse_args()
if a.method=='Homing' and a.homing_axis is None:p.error('Homing requires --homing-axis X or Y')
if a.method!='Homing' and a.homing_axis is not None:p.error('--homing-axis applies only to Homing')
if a.method=='ExtruderPreheating' and a.temperature_c is None:p.error('ExtruderPreheating requires --temperature-c (0 through 35)')
if a.method!='ExtruderPreheating' and a.temperature_c is not None:p.error('--temperature-c applies only to ExtruderPreheating')
def frame(t,flags,stream,data):return len(data).to_bytes(3,'big')+bytes([t,flags])+stream.to_bytes(4,'big')+data
def string(s):
 b=s.encode();assert len(b)<127;return bytes([len(b)])+b
h=b'\x83\x86\x04'+string('/applink.AppLinkService/'+a.method)+b'\x01'+string('127.0.0.1:50051')+b'\x0f\x10'+string('application/grpc')+b'\x00'+string('te')+string('trailers')
pb=(b'\x0a'+string(a.script)) if a.method=='RunGcodeScript' else ((b'\x0a'+string(a.file_path)+b'\x12'+string(a.file_name)) if a.method=='StartPrint' else b'')
# Original protobuf-lite: field 1 bool defaults false (direct native setter),
# field 2 uint32 Celsius. Omit both default-valued fields for target zero.
# Bound is diagnostic policy only; original runtime/firmware guards still apply.
if a.method=='ExtruderPreheating':pb=(b'\x10'+bytes([a.temperature_c])) if a.temperature_c else b''
if a.method=='Homing':pb=b'\x0a\x01'+a.homing_axis.encode('ascii')
grpc=b'\0'+len(pb).to_bytes(4,'big')+pb
packet=b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'+frame(4,0,0,b'')+frame(1,4,1,h)+frame(0,1,1,grpc)
BASE=0x10000;CODE=BASE+0x100;words=[];fix=[]
def emit(x):words.append(x)
def mov(r,v):
 if isinstance(v,int) and v<=255:emit(0xe3a00000|r<<12|v)
 else:fix.append((len(words),r,v));emit(0)
def call(n):mov(7,n);emit(0xef000000)
mov(0,2);mov(1,1);mov(2,0);call(281);emit(0xe1a04000)
emit(0xe1a00004);mov(1,'addr');mov(2,16);call(283)
emit(0xe1a00004);mov(1,'packet');mov(2,len(packet));call(4)
mov(5,0)
loop=len(words)
emit(0xe1a00004);mov(1,'buf');mov(2,4096);call(3)
emit(0xe3500000);branch=len(words);emit(0) # ble exit
emit(0xe1a02000);mov(0,1);mov(1,'buf');call(4)
emit(0xe3550000);skip=len(words);emit(0)
emit(0xe1a00004);mov(1,'ack');mov(2,9);call(4);mov(5,1)
words[skip]=0x1a000000|((len(words)-skip-2)&0xffffff)
b=len(words);emit(0xea000000|((loop-b-2)&0xffffff))
end=len(words);mov(0,0);call(1);words[branch]=0xda000000|((end-branch-2)&0xffffff)
start=CODE+4*(len(words)+len(fix));addr=struct.pack('<H',2)+(50051).to_bytes(2,'big')+bytes([127,0,0,1])+bytes(8)
labels={'addr':start,'packet':start+16,'ack':start+16+len(packet),'buf':start+16+len(packet)+9}
lits=[]
for k,(i,r,v) in enumerate(fix):
 delta=CODE+4*(len(words)+k)-(CODE+4*i+8);words[i]=0xe59f0000|r<<12|delta;lits.append(labels[v] if isinstance(v,str) else v)
body=struct.pack('<'+'I'*(len(words)+len(lits)),*(words+lits))+addr+packet+frame(4,1,0,b'')+bytes(4096)
hdr=b'\x7fELF'+bytes([1,1,1])+bytes(9)+struct.pack('<HHIIIIIHHHHHH',2,40,1,CODE,52,0,0x5000200,52,32,1,0,0,0)
ph=struct.pack('<8I',1,0,BASE,BASE,256+len(body),256+len(body),7,4096);elf=hdr+ph+bytes(256-len(hdr)-len(ph))+body
a.output.write_bytes(elf)
# Zero-filled receive area is materialized by ELF memory size instead of console transfer.
elf=elf[:-4096];elf=bytearray(elf);struct.pack_into('<I',elf,52+16,len(elf))
a.output.write_bytes(elf)
lines=[]
for off in range(0,len(elf),64):lines.append("printf '"+''.join('\\%03o'%b for b in elf[off:off+64])+"' "+('>' if off==0 else '>>')+' /tmp/grpc-probe')
lines+=['chmod +x /tmp/grpc-probe',f'timeout -t {a.timeout_seconds} /tmp/grpc-probe > /tmp/grpc-probe.out','od -v -b /tmp/grpc-probe.out','echo GRPC_PROBE_DONE']
a.output.with_suffix('.commands').write_text('\n'.join(lines)+'\n')
print(len(elf),'bytes')
