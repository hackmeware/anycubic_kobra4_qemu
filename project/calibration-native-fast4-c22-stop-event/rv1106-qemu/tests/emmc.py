#!/usr/bin/env python3
"""DW-MSHC/eMMC PIO and chained IDMAC read/write regression (temporary disk)."""
import pathlib, subprocess, tempfile, sys, struct
qemu=str(pathlib.Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory() as tmp:
    disk=pathlib.Path(tmp)/'card.img'
    with disk.open('wb') as f:
        f.truncate(64*1024*1024)
        f.seek(512); f.write(bytes(range(256))*2)
    p=subprocess.Popen([qemu,'-accel','qtest','-M','rv1106','-cpu','cortex-a7,has_el3=off','-m','64M','-display','none','-serial','null','-monitor','none','-qtest','stdio','-qtest-log',tmp+'/qtest.log','-drive',f'if=sd,index=0,file={disk},format=raw'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    def q(s):
        p.stdin.write(s+'\n');p.stdin.flush()
        r=p.stdout.readline().strip();assert r.startswith('OK'),(s,r)
        return int(r.split()[1],0) if ' ' in r else None
    def w(a,v):q(f'writel {a:#x} {v:#x}')
    def r(a):return q(f'readl {a:#x}')
    base=0xffa90000
    def cmd(n,arg=0,flags=0x40):
        w(base+0x44,0xffffffff);w(base+0x28,arg);w(base+0x2c,0x80000000|flags|n);q('clock_step 1000000')
        assert not r(base+0x44)&0x100,(n,hex(r(base+0x44)))
        return r(base+0x30)
    try:
        assert r(base+0x50)==0
        cmd(0,flags=0); assert cmd(1,0)==0x80ff8080
        assert cmd(1,0x40ff8000)&0x80000000
        cmd(2,flags=0xc0);cmd(3,1<<16);cmd(9,1<<16,0xc0);cmd(7,1<<16);cmd(16,512)
        w(base+0x1c,512);w(base+0x20,512)
        cmd(17,512,0x240)
        data=b''.join(struct.pack('<I',r(base+0x200)) for _ in range(128))
        assert data==bytes(range(256))*2
        assert r(base+0x44)&8
        # DMA sector read, ownership clearing and completion status.
        w(0x10000,0x8000001c);w(0x10004,512);w(0x10008,0x20000);w(0x1000c,0)
        w(base,1<<25);w(base+0x88,0x10000);cmd(17,512,0x240)
        assert r(0x20000)==0x03020100 and r(0x201fc)==0xfffefdfc
        assert not r(0x10000)&0x80000000
        assert r(base+0x8c)&0x102==0x102
        # DMA sector write followed by readback.
        w(0x10000,0x8000001c);w(0x20000,0xfeedface)
        cmd(24,1024,0x640)
        w(0x10000,0x8000001c);w(0x20000,0)
        cmd(17,1024,0x240);assert r(0x20000)==0xfeedface
        # Two chained descriptors, multiple block read, automatic CMD12.
        w(base+0x20,1024)
        w(0x10000,0x80000018);w(0x1000c,0x10010)
        w(0x10010,0x80000014);w(0x10014,512);w(0x10018,0x21000);w(0x1001c,0)
        cmd(18,512,0x1240)
        assert r(0x20000)==0x03020100 and r(0x21000)==0xfeedface
        assert not r(0x10010)&0x80000000
        assert r(base+0x44)&0x4008==0x4008
        # Actual SPI48 delivery through GIC, using vendor AIAR/AEOIR aliases.
        w(0xff1f1000,1);w(0xff1f2000,1);w(0xff1f2004,0xff)
        w(0xff1f1108,1<<16);w(0xff1f1850,1)
        w(base+0x8c,0xffffffff);w(base+0x24,4);w(base,0x10)
        cmd(13,1<<16)
        assert r(0xff1f2020)==80
        w(base+0x44,0xffffffff);w(0xff1f2024,80)
        assert r(0xff1f2020)==1023
        print('PASS: eMMC enumeration, PIO read, IDMAC read/write, descriptor ownership, interrupts')
    finally:
        p.terminate();o,e=p.communicate(timeout=5)
        if e:print(e[-1000:],file=sys.stderr)
