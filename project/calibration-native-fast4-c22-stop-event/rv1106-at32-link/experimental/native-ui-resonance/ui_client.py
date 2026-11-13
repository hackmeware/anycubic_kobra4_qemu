#!/usr/bin/env python3
"""Actual local VNC pixels and one visually chosen, frame-verified touchscreen click.

Does not launch emulators, issue RPC/G-code, access guest RAM, or control clocks.
All interaction uses the existing VNC -> touch JSON -> run_link -> uinput path.
"""
import argparse,fcntl,hashlib,json,os,socket,struct,time
from pathlib import Path

def receive(sock,n):
    out=bytearray()
    while len(out)<n:
        chunk=sock.recv(n-len(out))
        if not chunk:raise EOFError('VNC disconnected')
        out.extend(chunk)
    return bytes(out)

class Client:
    def __init__(self,endpoint):
        data=json.loads(endpoint.read_text())
        if data.get('host')!='127.0.0.1' or data.get('loopback_only') is not True:raise ValueError('Only restored loopback VNC is accepted')
        self.s=socket.create_connection(('127.0.0.1',int(data['port'])),timeout=5);self.s.settimeout(5)
        if receive(self.s,12)!=b'RFB 003.008\n':raise ValueError('Unexpected VNC protocol')
        self.s.sendall(b'RFB 003.008\n')
        if receive(self.s,2)!=b'\1\1':raise ValueError('Unexpected security types')
        self.s.sendall(b'\1')
        if receive(self.s,4)!=b'\0'*4:raise ValueError('VNC auth failed')
        self.s.sendall(b'\1');init=receive(self.s,24)
        self.width,self.height=struct.unpack_from('>HH',init)
        if (self.width,self.height)!=(480,320):raise ValueError('Unexpected UI resolution')
        if init[4:20]!=struct.pack('>BBBBHHHBBB3x',32,24,0,1,255,255,255,16,8,0):raise ValueError('Unexpected pixel format')
        self.name=receive(self.s,struct.unpack_from('>I',init,20)[0]).decode()
        self.s.sendall(struct.pack('>BBHi',2,0,1,0))
    def frame(self):
        self.s.sendall(struct.pack('>BBHHHH',3,0,0,0,480,320))
        if receive(self.s,4)!=b'\0\0\0\1':raise ValueError('Expected one framebuffer rectangle')
        rect=struct.unpack('>HHHHi',receive(self.s,12))
        if rect!=(0,0,480,320,0):raise ValueError('Unexpected framebuffer rectangle')
        return receive(self.s,480*320*4)
    def click(self,x,y,stop_request):
        if type(x) is not int or type(y) is not int or not (0<=x<480 and 0<=y<320):raise ValueError('Outside framebuffer')
        if stop_request.exists():raise SystemExit('Run already stopping')
        self.s.sendall(struct.pack('>BBHH',5,1,x,y));time.sleep(.15)
        self.s.sendall(struct.pack('>BBHH',5,0,x,y));time.sleep(.15)
    def close(self):self.s.close()

def digest(data):return hashlib.sha256(data).hexdigest()
def ppm(raw):
    rgb=bytearray()
    for n in range(0,len(raw),4):rgb.extend((raw[n+2],raw[n+1],raw[n]))
    return b'P6\n480 320\n255\n'+rgb

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--endpoint',type=Path,required=True)
    sub=p.add_subparsers(dest='action',required=True)
    c=sub.add_parser('capture');c.add_argument('--name',required=True)
    c=sub.add_parser('click');c.add_argument('--observed',type=Path,required=True);c.add_argument('--x',type=int,required=True);c.add_argument('--y',type=int,required=True);c.add_argument('--visible-label',required=True)
    a=p.parse_args();endpoint=a.endpoint.resolve();run=endpoint.parent
    if (run/'stop-request').exists():raise SystemExit('Run already stopping')
    # Only one approved client can control this diagnostic session at a time.
    with (run/'ui-control.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (run/'stop-request').exists():raise SystemExit('Run already stopping')
        client=Client(endpoint)
        try:
            raw=client.frame();now=time.time();sha=digest(raw)
            if (run/'stop-request').exists():raise SystemExit('Run already stopping')
            if a.action=='capture':
                if not a.name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in a.name):raise ValueError('Safe capture name required')
                folder=run/'ui-captures';folder.mkdir(exist_ok=True);path=folder/(a.name+'.ppm');meta=folder/(a.name+'.json')
                with path.open('xb') as stream:stream.write(ppm(raw))
                record={'actual_vnc_pixels':True,'frame_sha256':sha,'ppm_sha256':digest(path.read_bytes()),'host_time':now,'endpoint':str(endpoint),'image':str(path),'width':480,'height':320,'ui_label_inferred':False}
                with meta.open('x') as stream:json.dump(record,stream,indent=2);stream.write('\n')
                print(json.dumps(record))
            else:
                observed=a.observed.resolve()
                if observed.parent!=run/'ui-captures':raise ValueError('Observation must belong to this run')
                old=json.loads(observed.read_text())
                if old.get('endpoint')!=str(endpoint) or not old.get('actual_vnc_pixels'):raise ValueError('Wrong observed session')
                if not 0<=now-old['host_time']<=120:raise ValueError('Observation too old; capture and inspect again')
                if old['frame_sha256']!=sha:raise ValueError('Visible framebuffer changed; capture and inspect again')
                image=Path(old['image'])
                if image.parent!=observed.parent or digest(image.read_bytes())!=old['ppm_sha256']:raise ValueError('Observed pixels changed')
                if not a.visible_label.strip():raise ValueError('Describe the actually observed control')
                event={'host_time':now,'action':'pointer_down_up','x':a.x,'y':a.y,'visible_label':a.visible_label,'observation':str(observed),'frame_sha256':sha,'no_rpc':True}
                # Atomic, persistent one-use claim. Even an uncertain failed send
                # consumes this inspected frame; a new capture is then required.
                consumed=observed.with_suffix('.consumed.json')
                try:
                    with consumed.open('x') as stream:
                        json.dump({**event,'state':'consumed_before_send'},stream)
                        stream.write('\n');stream.flush();os.fsync(stream.fileno())
                except FileExistsError:
                    raise ValueError('Observation already consumed; capture and inspect again')
                with (run/'ui-actions.jsonl').open('a') as stream:stream.write(json.dumps({**event,'state':'before_send'})+'\n')
                client.click(a.x,a.y,run/'stop-request')
                with (run/'ui-actions.jsonl').open('a') as stream:stream.write(json.dumps({**event,'state':'sent_not_yet_observed'})+'\n')
                print(json.dumps(event))
        finally:client.close()
if __name__=='__main__':main()
