#!/usr/bin/env python3
"""Loopback-only RFB/VNC server for actual RV1106 guest framebuffer memory.

No remote bind option, clipboard sharing, shell access, or keyboard injection.
Security type None is restricted to 127.0.0.1: local processes can view/control.
"""
import argparse,array,hashlib,json,mmap,select,signal,socket,struct,sys,time
from pathlib import Path
from live_view import read_config,pixels
HOST='127.0.0.1'
DEFAULT_FORMAT=struct.pack('>BBBBHHHBBB3x',32,24,0,1,255,255,255,16,8,0)

class ProtocolError(Exception):pass

def receive(sock,n):
    data=bytearray()
    while len(data)<n:
        b=sock.recv(n-len(data))
        if not b:raise EOFError()
        data.extend(b)
    return bytes(data)

def validate_format(data):
    bpp,depth,big,true,rmax,gmax,bmax,rs,gs,bs=struct.unpack('>BBBBHHHBBB3x',data)
    if bpp not in (8,16,32) or not 0<depth<=bpp or not true or big not in (0,1):raise ProtocolError('Unsupported pixel format')
    masks=[]
    for maximum,shift in [(rmax,rs),(gmax,gs),(bmax,bs)]:
        if not 0<maximum<=255 or maximum&(maximum+1) or shift+maximum.bit_length()>bpp:raise ProtocolError('Invalid color mask')
        masks.append(maximum<<shift)
    if any(masks[i]&masks[j] for i in range(3) for j in range(i)):raise ProtocolError('Overlapping color masks')
    if sum(x.bit_count() for x in masks)>depth:raise ProtocolError('Color masks exceed depth')
    return bpp,depth,big,true,rmax,gmax,bmax,rs,gs,bs

def encode(raw,pf):
    bpp,depth,big,true,rmax,gmax,bmax,rs,gs,bs=pf
    if bpp==32 and not big and (rmax,gmax,bmax,rs,gs,bs)==(255,255,255,16,8,0):return raw
    values=[]
    for off in range(0,len(raw),4):
        b,g,r=raw[off:off+3]
        values.append(((r*rmax//255)<<rs)|((g*gmax//255)<<gs)|((b*bmax//255)<<bs))
    out=array.array({8:'B',16:'H',32:'I'}[bpp],values)
    if bpp>8 and bool(big)!=(sys.byteorder=='big'):out.byteswap()
    return out.tobytes()

def touch_write(path,event):
    if path:
        with path.open('a') as f:f.write(json.dumps(event)+'\n')

class FrameSource:
    def __init__(self,ram,vop,width=480,height=320):
        self.file=ram.open('rb');self.ram=mmap.mmap(self.file.fileno(),0,access=mmap.ACCESS_READ);self.vop=vop;self.width=width;self.height=height;self.last=bytes(width*height*4);self.valid=False
    def frame(self):
        try:
            cfg=read_config(self.vop,len(self.ram))
            if cfg[:2]!=(self.width,self.height):raise ProtocolError('Guest changed resolution')
            self.last=pixels(self.ram,cfg);self.valid=True
        except (FileNotFoundError,ValueError,struct.error):pass
        return self.last
    def close(self):self.ram.close();self.file.close()

def handshake(client,width,height):
    client.settimeout(5);client.sendall(b'RFB 003.008\n');version=receive(client,12)
    if version not in (b'RFB 003.003\n',b'RFB 003.007\n',b'RFB 003.008\n'):raise ProtocolError('Unsupported RFB version')
    if version==b'RFB 003.003\n':client.sendall(struct.pack('>I',1))
    else:
        client.sendall(b'\x01\x01')
        if receive(client,1)!=b'\x01':raise ProtocolError('Unsupported security type')
        if version==b'RFB 003.008\n':client.sendall(struct.pack('>I',0))
    receive(client,1)
    name=b'RV1106 native framebuffer (diagnostic touch; localhost only)'
    client.sendall(struct.pack('>HH',width,height)+DEFAULT_FORMAT+struct.pack('>I',len(name))+name)
    client.settimeout(2)

def serve_client(client,source,touch,stopping,end,fps,stats):
    handshake(client,source.width,source.height);stats['handshakes']+=1
    pf=validate_format(DEFAULT_FORMAT);pending=None;last_hash=None;last_send=0;next_frame=0;held=False;last_pos=(0,0)
    try:
        while not stopping[0] and (not end or time.monotonic()<end):
            now=time.monotonic()
            ready,_,_=select.select([client],[],[],.02)
            if ready:
                kind=receive(client,1)[0]
                if kind==0:
                    receive(client,3);pf=validate_format(receive(client,16));last_hash=None
                elif kind==2:
                    count=struct.unpack('>xH',receive(client,3))[0]
                    if count>256:raise ProtocolError('Too many encodings')
                    receive(client,count*4) # Raw is always supported by RFB clients.
                elif kind==3:
                    inc,x,y,w,h=struct.unpack('>BHHHH',receive(client,9))
                    if x>=source.width or y>=source.height or w==0 or h==0:
                        client.sendall(b'\0\0\0\0');continue
                    w=min(w,source.width-x);h=min(h,source.height-y)
                    if pending:
                        oldinc,ox,oy,ow,oh=pending;right=max(x+w,ox+ow);bottom=max(y+h,oy+oh);x=min(x,ox);y=min(y,oy);w=right-x;h=bottom-y;inc=inc and oldinc
                    pending=(inc,x,y,w,h)
                elif kind==4:receive(client,7) # Keyboard injection intentionally unavailable.
                elif kind==5:
                    buttons,x,y=struct.unpack('>BHH',receive(client,5));down=bool(buttons&1);x=min(x,source.width-1);y=min(y,source.height-1)
                    if down or held:
                        touch_write(touch,{'x':x,'y':y,'down':down});stats['pointer_events']+=1
                    held=down;last_pos=(x,y)
                elif kind==6:
                    length=struct.unpack('>3xI',receive(client,7))[0]
                    if length>1024*1024:raise ProtocolError('Clipboard message exceeds limit')
                    receive(client,length) # Discard; never share either clipboard.
                else:raise ProtocolError('Unsupported client message')
            if pending and now>=next_frame:
                inc,x,y,w,h=pending;raw=source.frame();stride=source.width*4
                crop=b''.join(raw[row*stride+x*4:row*stride+(x+w)*4] for row in range(y,y+h));digest=hashlib.sha256(crop).digest()
                if not inc or digest!=last_hash:
                    payload=encode(crop,pf);client.sendall(struct.pack('>BBHHHHHi',0,0,1,x,y,w,h,0)+payload)
                    stats['updates']+=1;stats['valid_guest_updates']+=int(source.valid);last_hash=digest;pending=None;last_send=now
                elif now-last_send>2:
                    client.sendall(b'\0\0\0\0');pending=None;last_send=now
                next_frame=now+1/fps
    finally:
        if held:touch_write(touch,{'x':last_pos[0],'y':last_pos[1],'down':False});stats['disconnect_releases']+=1

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ram',type=Path,required=True);p.add_argument('--vop',type=Path,required=True);p.add_argument('--touch-output',type=Path);p.add_argument('--port',type=int,default=5900);p.add_argument('--seconds',type=float,default=0);p.add_argument('--fps',type=float,default=10);p.add_argument('--endpoint',type=Path,required=True);p.add_argument('--report',type=Path);p.add_argument('--ppm',type=Path);a=p.parse_args()
    if not 0<=a.port<=65535 or a.seconds<0 or a.fps<=0:p.error('Invalid port, duration or fps')
    stopping=[False]
    def stop(*unused):stopping[0]=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    source=FrameSource(a.ram,a.vop);stats={'handshakes':0,'updates':0,'valid_guest_updates':0,'pointer_events':0,'disconnect_releases':0,'client_errors':0,'loopback_only':True,'auth':'None; local processes only','source':'actual guest framebuffer; no recreated UI'}
    end=time.monotonic()+a.seconds if a.seconds else None
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);server.bind((HOST,a.port));server.listen(1);server.settimeout(.2)
            address=server.getsockname();endpoint_tmp=a.endpoint.with_suffix(a.endpoint.suffix+'.tmp');endpoint_tmp.write_text(json.dumps({'host':address[0],'port':address[1],'loopback_only':True,'security':'None','warning':'Any process on this computer can connect. Do not forward this port to an untrusted network.'})+'\n');endpoint_tmp.replace(a.endpoint)
            print(f'VNC listening only on {address[0]}:{address[1]} (no password; local processes only).',flush=True)
            while not stopping[0] and (not end or time.monotonic()<end):
                try:client,peer=server.accept()
                except socket.timeout:continue
                with client:
                    if peer[0]!=HOST:continue
                    client.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
                    try:serve_client(client,source,a.touch_output,stopping,end,a.fps,stats)
                    except (EOFError,ConnectionError,socket.timeout,ProtocolError,OSError) as error:
                        if not isinstance(error,(EOFError,ConnectionResetError)):
                            stats['client_errors']+=1
                        if not isinstance(error,(EOFError,ConnectionResetError)):print('Client disconnected: '+type(error).__name__,flush=True)
            if a.ppm:
                raw=source.frame();rgb=bytearray()
                for i in range(0,len(raw),4):rgb.extend((raw[i+2],raw[i+1],raw[i]))
                a.ppm.write_bytes(f'P6\n{source.width} {source.height}\n255\n'.encode()+rgb)
    finally:
        source.close()
        if a.report:a.report.write_text(json.dumps(stats,indent=2)+'\n')
if __name__=='__main__':main()
