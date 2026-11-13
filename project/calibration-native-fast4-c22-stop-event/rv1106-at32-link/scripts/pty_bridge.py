"""Byte-transparent local bridge; virtual UART endpoints provide baud timing."""
import os,select,threading,tty,time
class PtyBridge:
    def __init__(self,left,right):
        self.fds=[os.open(str(p),os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK) for p in (left,right)]
        for fd in self.fds: tty.setraw(fd)
        self.events=[];self.timing_dropped=0;self.started=time.monotonic();self.error=None;self.stop=threading.Event();self.counts=[0,0]
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def run(self):
        pending=[bytearray(),bytearray()]
        try:
            while not self.stop.is_set():
                rd,wr,_=select.select(self.fds,[fd for i,fd in enumerate(self.fds) if pending[i]],[],.05)
                for i,fd in enumerate(self.fds):
                    if fd in rd:
                        data=os.read(fd,65536);pending[1-i].extend(data)
                        if len(self.events)<1000000:self.events.append({'wall_elapsed_s':time.monotonic()-self.started,'direction':i,'offset':self.counts[i],'length':len(data)})
                        else:self.timing_dropped+=1
                        self.counts[i]+=len(data)
                        if len(pending[1-i])>1048576: raise RuntimeError('Motor bridge queue overflow')
                    if fd in wr:
                        n=os.write(fd,pending[i]);del pending[i][:n]
        except Exception as e:self.error=str(e)
    def close(self):
        self.stop.set();self.thread.join(1)
        for fd in self.fds:os.close(fd)
