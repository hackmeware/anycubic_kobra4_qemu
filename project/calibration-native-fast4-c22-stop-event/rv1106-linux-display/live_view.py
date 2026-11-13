#!/usr/bin/env python3
"""SDL2 viewer for real guest framebuffer bytes in a shared QEMU RAM file.

No reconstructed UI. Requires system SDL2 (ctypes), not an SDL-enabled QEMU.
Input is optional JSONL output; a launcher may relay it to diagnostic uinput.
"""
import argparse,ctypes as C,ctypes.util,hashlib,json,mmap,os,struct,time,signal
from pathlib import Path

def read_config(path,memory_size):
    v=struct.unpack('<128I',Path(path).read_bytes())
    width=(v[0xa4//4]&0xfff)+1; height=((v[0xa4//4]>>16)&0xfff)+1
    stride=(v[0x98//4]&0x1fff)*4; address=v[0xa0//4]
    fmt=(v[0x90//4]>>4)&7; swap=bool(v[0x90//4]&(1<<12))
    bpp={0:4,1:3,2:2}.get(fmt)
    if not v[0x90//4]&1 or bpp is None or not (0<width<=1280 and 0<height<=1280 and width*bpp<=stride<=8192 and address+stride*height<=memory_size):
        raise ValueError('VOP framebuffer not configured or unsupported')
    return width,height,stride,address,fmt,swap

def pixels(ram,cfg):
    w,h,stride,addr,fmt,swap=cfg
    raw=ram[addr:addr+stride*h]
    if fmt==0 and not swap:
        return b''.join(raw[y*stride:y*stride+w*4] for y in range(h))
    data=bytearray(w*h*4); bpp={0:4,1:3,2:2}[fmt]
    for y in range(h):
        for x in range(w):
            off=y*stride+x*bpp
            if fmt==2:
                z=struct.unpack_from('<H',raw,off)[0]
                r=(z>>11)*255//31;g=((z>>5)&63)*255//63;b=(z&31)*255//31
            else:
                b,g,r=raw[off:off+3]
            if swap:r,b=b,r
            out=(y*w+x)*4;data[out:out+4]=bytes((b,g,r,255))
    return bytes(data)

class SDLView:
    def __init__(self,w,h,scale=2):
        self.s=C.CDLL(ctypes.util.find_library('SDL2') or 'libSDL2-2.0.so.0')
        specs={'SDL_Init':([C.c_uint32],C.c_int),'SDL_GetError':([],C.c_char_p),'SDL_GetCurrentVideoDriver':([],C.c_char_p),
         'SDL_CreateWindow':([C.c_char_p,C.c_int,C.c_int,C.c_int,C.c_int,C.c_uint32],C.c_void_p),
         'SDL_CreateRenderer':([C.c_void_p,C.c_int,C.c_uint32],C.c_void_p),
         'SDL_CreateTexture':([C.c_void_p,C.c_uint32,C.c_int,C.c_int,C.c_int],C.c_void_p),
         'SDL_UpdateTexture':([C.c_void_p,C.c_void_p,C.c_void_p,C.c_int],C.c_int),
         'SDL_RenderClear':([C.c_void_p],C.c_int),
         'SDL_RenderCopy':([C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p],C.c_int),
         'SDL_RenderPresent':([C.c_void_p],None),'SDL_PollEvent':([C.c_void_p],C.c_int),
         'SDL_PushEvent':([C.c_void_p],C.c_int),
         'SDL_RenderReadPixels':([C.c_void_p,C.c_void_p,C.c_uint32,C.c_void_p,C.c_int],C.c_int),
         'SDL_DestroyTexture':([C.c_void_p],None),'SDL_DestroyRenderer':([C.c_void_p],None),
         'SDL_DestroyWindow':([C.c_void_p],None),'SDL_Quit':([],None)}
        for name,(args,result) in specs.items():
            f=getattr(self.s,name);f.argtypes=args;f.restype=result
        self.w=w;self.h=h;self.scale=scale;self.held=False
        if self.s.SDL_Init(0x20):raise RuntimeError(self.error())
        self.window=self.s.SDL_CreateWindow(b'RV1106 native framebuffer | diagnostic touch',0x1fff0000,0x1fff0000,w*scale,h*scale,4)
        if not self.window:raise RuntimeError(self.error())
        self.renderer=self.s.SDL_CreateRenderer(self.window,-1,1)
        if not self.renderer:raise RuntimeError(self.error())
        self.texture=self.s.SDL_CreateTexture(self.renderer,0x16362004,1,w,h)
        if not self.texture:raise RuntimeError(self.error())
    def error(self):return self.s.SDL_GetError().decode(errors='replace')
    def frame(self,data):
        buf=C.create_string_buffer(data)
        if self.s.SDL_UpdateTexture(self.texture,None,buf,self.w*4):raise RuntimeError(self.error())
        self.s.SDL_RenderClear(self.renderer);self.s.SDL_RenderCopy(self.renderer,self.texture,None,None);self.s.SDL_RenderPresent(self.renderer)
    def events(self):
        event=C.create_string_buffer(56);out=[]
        while self.s.SDL_PollEvent(event):
            kind=struct.unpack_from('<I',event.raw)[0]
            if kind==0x100:return None
            if kind in (0x401,0x402):
                if event.raw[16]!=1:continue
                self.held=kind==0x401
            elif kind!=0x400 or not self.held:continue
            x,y=struct.unpack_from('<ii',event.raw,20)
            out.append({'x':max(0,min(self.w-1,x//self.scale)),'y':max(0,min(self.h-1,y//self.scale)),'down':self.held})
        return out
    def close(self):
        self.s.SDL_DestroyTexture(self.texture);self.s.SDL_DestroyRenderer(self.renderer);self.s.SDL_DestroyWindow(self.window);self.s.SDL_Quit()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ram',type=Path,required=True);p.add_argument('--vop',type=Path,required=True);p.add_argument('--touch-output',type=Path);p.add_argument('--scale',type=int,choices=[1,2,3],default=2);p.add_argument('--seconds',type=float,default=0);p.add_argument('--report',type=Path);p.add_argument('--ppm',type=Path);p.add_argument('--fps',type=float,default=15);p.add_argument('--headless',action='store_true');a=p.parse_args()
    if a.fps<=0 or a.seconds<0:p.error('fps must be positive; seconds cannot be negative')
    stopping=[False]
    def stop(*unused):stopping[0]=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    start=time.monotonic();seen=set();frames=0;view=None;last=None;touch=a.touch_output.open('a',buffering=1) if a.touch_output else None
    try:
        with a.ram.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as ram:
            while not stopping[0] and (not a.seconds or time.monotonic()-start<a.seconds):
                try:cfg=read_config(a.vop,len(ram))
                except (ValueError,FileNotFoundError,struct.error):time.sleep(.1);continue
                if view is None and not a.headless:view=SDLView(cfg[0],cfg[1],a.scale)
                data=pixels(ram,cfg);last=(cfg,data);seen.add(hashlib.sha256(data).hexdigest());frames+=1
                if view:
                    if (view.w,view.h)!=cfg[:2]:raise RuntimeError('Guest resolution changed; restart viewer')
                    view.frame(data);events=view.events()
                    if events is None:break
                    if touch:
                        for event in events:touch.write(json.dumps(event)+'\n')
                time.sleep(1/a.fps)
        if last and a.ppm:
            cfg,data=last;rgb=bytearray()
            for i in range(0,len(data),4):rgb.extend((data[i+2],data[i+1],data[i]))
            a.ppm.write_bytes(f'P6\n{cfg[0]} {cfg[1]}\n255\n'.encode()+rgb)
        if a.report:a.report.write_text(json.dumps({'frames':frames,'distinct_frame_hashes':len(seen),'source':'live shared guest RAM; original firmware pixels','window_rendered':view is not None,'video_driver':view.s.SDL_GetCurrentVideoDriver().decode() if view else None},indent=2)+'\n')
        print(f'Viewed {frames} frames; {len(seen)} distinct frame hashes.')
    finally:
        if view:view.close()
        if touch:touch.close()
if __name__=='__main__':main()
