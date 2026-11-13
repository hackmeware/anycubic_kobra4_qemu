import os
from pathlib import Path
import struct, ctypes, sys, json, os
ram_mb=int(os.environ.get("RV1106_RAM_MB", "64"))
assert ram_mb in (64,128,256)
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root.parent/'rv1106-qemu/tools'))
from rv1106_image import fdt
p=(Path(os.environ['RV_INPUTS'])/'kernel-board-dtb.dtb')
nodes,_=fdt(p.read_bytes())
nodes['/memory@0']={'device_type':b'memory\0','reg':struct.pack('>II',0,ram_mb*1024*1024)}
nodes['/chosen']['bootargs']=b'earlycon=,mmio32,0xff4c0000 console=ttyS2,115200n8 cma=8M loglevel=8 ignore_loglevel initcall_debug root=/dev/mmcblk0p8 rootfstype=squashfs rootwait ro fw_devlink=off deferred_probe_timeout=1 init=/emulation-init.sh\0'
layout=json.loads((Path(os.environ['RV_INPUTS'])/'disk-layout.json').read_text())
parts=','.join(str(p['sectors']*512//1024)+'K@'+str(p['start_sector']*512//1024)+'K('+p['name']+')' for p in layout['partitions'])
nodes['/chosen']['bootargs']=nodes['/chosen']['bootargs'][:-1]+(' blkdevparts=mmcblk0:'+parts).encode()+b'\0'
# Reduced diagnostic board: explicitly remove unsupported devices from discovery.
keep = {'/clocks','/timer','/interrupt-controller@ff1f0000','/clock-controller@ff3a0000','/syscon@ff000000','/syscon@ff388000','/syscon@ff538000','/pinctrl','/serial@ff4a0000','/serial@ff4c0000','/serial@ff4d0000','/mmc@ffa90000','/display-subsystem','/vop@ff990000','/backlight','/pwm@ff350010'}
for path,props in nodes.items():
 if path.count('/') == 1 and 'compatible' in props and path not in keep:
  props['status']=b'disabled\0'
 if path.startswith('/cpus/cpu@'):
  props.pop('operating-points-v2',None)
uart=nodes['/serial@ff4c0000']; uart['status']=b'okay\0'
for key in ['dmas','dma-names']: uart.pop(key,None)
nozzle_uart=nodes['/serial@ff4a0000']; nozzle_uart['status']=b'okay\0'
for key in ['dmas','dma-names']: nozzle_uart.pop(key,None)
mcu_uart=nodes['/serial@ff4d0000']; mcu_uart['status']=b'okay\0'
for key in ['dmas','dma-names']: mcu_uart.pop(key,None)
mmc=nodes['/mmc@ffa90000']; mmc['status']=b'okay\0'
for key in ['mmc-ddr-1_8v','mmc-hs200-1_8v']: mmc.pop(key,None)
mmc['max-frequency']=struct.pack('>I',25000000)
mmc['compatible']=b'snps,dw-mshc\0'
nodes['/emmc-fixed-clock']={'compatible':b'fixed-clock\0','#clock-cells':struct.pack('>I',0),'clock-frequency':struct.pack('>I',50000000),'phandle':struct.pack('>I',501)}
mmc['clocks']=struct.pack('>2I',501,501)
mmc['clock-names']=b'biu\0ciu\0'
panel=nodes['/syscon@ff000000/rgb/mcu-panel']
for key in ['enable-gpios']: panel.pop(key,None)
nodes['/display-subsystem'].pop('memory-region',None)
nodes['/display-subsystem'].pop('memory-region-names',None)
nodes['/chosen']['stdout-path']=b'/serial@ff4c0000:115200n8\0'
nodes['/timer']['interrupts']=struct.pack('>3I',1,14,0x104)
names=b''; offsets={}; tree={}
for path, props in nodes.items():
 for name in props:
  if name not in offsets: offsets[name]=len(names);names+=name.encode()+b'\0'
 for part in path.split('/')[1:]:pass

def pad(b):return b+b'\0'*((-len(b))%4)
def emit(path):
 name=path.rsplit('/',1)[-1].encode(); out=struct.pack('>I',1)+pad(name+b'\0')
 for k,v in nodes[path].items():out+=struct.pack('>III',3,len(v),offsets[k])+pad(v)
 for child in nodes:
  if child and child.rsplit('/',1)[0]==path:out+=emit(child)
 return out+struct.pack('>I',2)
b=emit('')+struct.pack('>I',9)
dtb=struct.pack('>10I',0xd00dfeed,56+len(b)+len(names),56,56+len(b),40,17,16,0,len(names),len(b))+b'\0'*16+b+names
(root/'linux-test.dtb').write_bytes(dtb)
# ARM little endian: r0=0; r1=-1; r2=DTB; branch kernel. Linux standard boot ABI.
(root/'boot-trampoline.bin').write_bytes(struct.pack('<6I',0xe3a00000,0xe3e01000,0xe59f2000,0xe59ff000,0x3000000,0x800000))
print('Patched DTB and trampoline only; original inputs untouched.')
segments=[(0x200000,(root/'boot-trampoline.bin').read_bytes()),(0x800000,(Path(os.environ['RV_INPUTS'])/'kernel-zImage').read_bytes()),(0x3000000,dtb)]
header=b'\x7fELF'+bytes([1,1,1])+bytes(9)+struct.pack('<HHIIIIIHHHHHH',2,40,1,0x200000,52,0,0x5000200,52,32,len(segments),0,0,0)
off=52+32*len(segments); ph=b'';body=b''
for addr,data in segments:
 ph+=struct.pack('<8I',1,off,addr,addr,len(data),len(data),7,4);body+=data;off+=len(data)
(root/'linux-test.elf').write_bytes(header+ph+body)
