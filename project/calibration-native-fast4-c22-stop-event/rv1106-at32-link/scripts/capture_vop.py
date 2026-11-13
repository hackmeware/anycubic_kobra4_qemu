"""Capture actual guest VOP DMA pixels through QEMU HMP; no synthetic screen."""
import os,struct,time,json

def capture(fds,tmp,target,log_dir,memory_mb=64):
    logs=bytearray()
    def drain():
        try:
            while True: logs.extend(os.read(fds[1],65536))
        except BlockingIOError: pass
    def command(s):
        os.write(fds[0],(s+'\n').encode());time.sleep(.05);drain()
    def dump(addr,size,path):
        path.unlink(missing_ok=True)
        command(f'pmemsave {addr:#x} {size:#x} "{path}"')
        until=time.monotonic()+5
        while time.monotonic()<until:
            drain()
            if path.exists() and path.stat().st_size==size:return path.read_bytes()
            time.sleep(.02)
        raise RuntimeError('VOP capture dump failed: '+str(path))
    try:
        command('stop')
        regs=dump(0xff990000,512,tmp/'vop.bin')
        v=struct.unpack('<128I',regs)
        width=(v[0xa4//4]&0xfff)+1;height=((v[0xa4//4]>>16)&0xfff)+1
        stride=(v[0x98//4]&0x1fff)*4;addr=v[0xa0//4]
        fmt=(v[0x90//4]>>4)&7;swap=bool(v[0x90//4]&(1<<12));enabled=bool(v[0x90//4]&1)
        bpp={0:4,1:3,2:2}.get(fmt)
        if not enabled or bpp is None or not (0<width<=1280 and 0<height<=1280 and width*bpp<=stride<=8192 and addr+stride*height<=memory_mb*1024*1024):
            raise RuntimeError('Invalid/disabled VOP framebuffer configuration')
        raw=dump(addr,stride*height,tmp/'framebuffer.bin');pixels=bytearray()
        for y in range(height):
            for x in range(width):
                offset=y*stride+x*bpp
                if fmt in (0,1):
                    a,b,c=raw[offset:offset+3];r,g,blue=(a,b,c) if swap else (c,b,a)
                else:
                    z=struct.unpack_from('<H',raw,offset)[0]
                    r=(z>>11)*255//31;g=((z>>5)&63)*255//63;blue=(z&31)*255//31
                    if swap:r,blue=blue,r
                pixels.extend((r,g,blue))
        target.write_bytes(f'P6\n{width} {height}\n255\n'.encode()+pixels)
        (log_dir/'display.json').write_text(json.dumps({'width':width,'height':height,'stride':stride,'address':hex(addr),'format':fmt,'enabled':enabled,'capture':'actual guest VOP DMA buffer; no synthetic UI'},indent=2)+'\n')
        (log_dir/'vop.bin').write_bytes(regs)
    finally:
        drain();(log_dir/'qemu-monitor.log').write_bytes(logs)
