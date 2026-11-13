#!/usr/bin/env python3
"""Run original RV1106 UI with live shared-memory SDL2 viewer and uinput touch.

This diagnostic launcher does not start or connect printer MCUs.
"""
import argparse,json,os,struct,subprocess,sys,tempfile,time,math,signal
from pathlib import Path
R=Path(__file__).resolve().parent

def event_command(event):
    x=int(event['x']);y=int(event['y']);down=bool(event['down'])
    if not (0<=x<480 and 0<=y<320):raise ValueError('Touch outside framebuffer')
    data=b''.join(struct.pack('<IIHHi',0,0,t,c,v) for t,c,v in [(3,0,x),(3,1,y),(1,330,int(down)),(0,0,0)])
    return ("printf '"+''.join('\\%03o'%b for b in data)+"' > /tmp/touch-events\n").encode()

def main():
    def terminate(*unused):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,terminate)
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--qemu',type=Path,default=R.parent/'rv1106-qemu/bin/qemu-system-arm-display');p.add_argument('--kernel',type=Path,default=R/'linux-test.elf');p.add_argument('--disk',type=Path,required=True);p.add_argument('--memory',type=int,choices=[64,128,256],default=64);p.add_argument('--commands',type=Path,default=R/'ui-touch.commands');p.add_argument('--seconds',type=float,default=0);p.add_argument('--headless',action='store_true');p.add_argument('--vnc',action='store_true',help='Serve VNC only on127.0.0.1 instead of SDL2');p.add_argument('--vnc-port',type=int,default=5900);p.add_argument('--touch-replay',type=Path,help='Optional JSON array of diagnostic touches with at seconds, x, y and down');p.add_argument('--output',type=Path,default=R/'live-results');a=p.parse_args()
    for path in [a.qemu,a.kernel,a.disk,a.commands]:
        if not path.is_file():p.error('Missing file '+str(path))
    if not 0<=a.vnc_port<=65535:p.error('Invalid VNC port')
    if a.vnc and a.headless:p.error('Choose --vnc or --headless')
    if a.seconds<0 or (a.headless and a.seconds==0):p.error('Headless mode requires --seconds >0')
    if any(',' in str(x.resolve()) for x in [a.disk,a.output]):p.error('Paths cannot contain commas')
    a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=True)
    if a.vnc:(a.output/'vnc-endpoint.json').unlink(missing_ok=True)
    replay=json.loads(a.touch_replay.read_text()) if a.touch_replay else []
    if not isinstance(replay,list):p.error('Touch replay must be a JSON array')
    for event in replay:
        event_command(event)
        if not isinstance(event.get('down'),bool) or not isinstance(event.get('at'),(int,float)) or not math.isfinite(event['at']) or event['at']<0:p.error('Invalid replay event')
    replay.sort(key=lambda event:event['at'])
    children=[];fds=[]
    with tempfile.TemporaryDirectory(prefix='rv1106-live-') as td:
        tmp=Path(td);ram=tmp/'guest-ram.bin';vop=tmp/'vop.bin';touch=tmp/'touch.jsonl';touch.write_text('');mon=tmp/'monitor'
        for suffix in ['.in','.out']:
            os.mkfifo(str(mon)+suffix);fds.append(os.open(str(mon)+suffix,os.O_RDWR|os.O_NONBLOCK))
        logs=[]
        try:
            console=(a.output/'console.log').open('wb');qlog=(a.output/'qemu.log').open('wb');logs.extend([console,qlog])
            args=[str(a.qemu.resolve()),'-M','rv1106,memory-backend=displayram','-m',str(a.memory)+'M','-object',f'memory-backend-file,id=displayram,size={a.memory}M,mem-path={ram},share=on','-cpu','cortex-a7,has_el3=off','-display','none','-monitor','pipe:'+str(mon),'-serial','stdio','-kernel',str(a.kernel.resolve()),'-drive',f'if=sd,index=0,file={a.disk.resolve()},format=raw,snapshot=on']
            q=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=console,stderr=qlog);children.append(q)
            until=time.monotonic()+10
            while not ram.exists() or ram.stat().st_size != a.memory*1024*1024:
                if q.poll() is not None or time.monotonic()>until:raise RuntimeError('QEMU did not create shared RAM; see qemu.log')
                time.sleep(.05)
            viewargs=[sys.executable,str(R/('vnc_view.py' if a.vnc else 'live_view.py')),'--ram',str(ram),'--vop',str(vop),'--touch-output',str(touch),'--seconds',str(a.seconds),'--report',str(a.output/'viewer.json'),'--ppm',str(a.output/'last-frame.ppm')]
            if a.vnc:viewargs+=['--port',str(a.vnc_port),'--endpoint',str(a.output/'vnc-endpoint.json')]
            if a.headless:viewargs+=['--headless']
            viewlog=(a.output/'viewer.log').open('wb');logs.append(viewlog)
            viewer=subprocess.Popen(viewargs,stdout=viewlog,stderr=subprocess.STDOUT);children.append(viewer)
            pending=a.commands.read_bytes()+b'\n';replay_start=time.monotonic();started=False;next_chunk=0;next_regs=0;touch_offset=0
            with (a.output/'monitor.log').open('wb') as mlog:
                while viewer.poll() is None:
                    if q.poll() is not None:raise RuntimeError('QEMU exited; see qemu.log')
                    now=time.monotonic()
                    if a.vnc and (a.output/'vnc-endpoint.json').exists() and not getattr(a,'vnc_announced',False):
                        ep=json.loads((a.output/'vnc-endpoint.json').read_text());print(f"VNC: {ep['host']}:{ep['port']} (local only; no password).",flush=True);a.vnc_announced=True
                    if not started and b'RV1106_OFFLINE_USERSPACE_READY' in (a.output/'console.log').read_bytes():started=True
                    if started and pending and now>=next_chunk:
                        newline=pending.find(b'\n');count=min(64,newline+1 if newline>=0 else len(pending));chunk=pending[:count];pending=pending[count:]
                        q.stdin.write(chunk);q.stdin.flush();next_chunk=now+(.1 if chunk.endswith(b'\n') else .01)
                    if now>=next_regs:
                        os.write(fds[0],f'pmemsave 0xff990000 0x200 "{vop}"\n'.encode());next_regs=now+.5
                    try:
                        while True:mlog.write(os.read(fds[1],65536))
                    except BlockingIOError:pass
                    if started and not pending:
                        while replay and now-replay_start>=replay[0]['at']:
                            with touch.open('a') as tf:tf.write(json.dumps(replay.pop(0))+'\n')
                        with touch.open('r') as tf:
                            tf.seek(touch_offset)
                            while True:
                                before=tf.tell();line=tf.readline()
                                if not line or not line.endswith('\n'):
                                    touch_offset=before;break
                                pending+=event_command(json.loads(line))
                                touch_offset=tf.tell()
                    time.sleep(.01)
            if viewer.returncode:raise RuntimeError('Viewer failed; see viewer.log')
            print('Live session ended. Evidence: '+str(a.output))
        finally:
            for child in reversed(children):
                if child.poll() is None:child.terminate()
            for child in children:
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.wait()
            for f in logs:f.close()
            for fd in fds:os.close(fd)
if __name__=='__main__':main()
