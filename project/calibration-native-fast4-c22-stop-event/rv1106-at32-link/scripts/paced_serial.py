"""Optional host-wall-clock diagnostic pacing; not cycle/baud accurate."""
import os, pty, select, threading, time, tty
from collections import deque

class PacedSerial:
    def __init__(self, renode_path, delay):
        self.master,self.slave=pty.openpty()
        tty.setraw(self.slave)
        self.path=os.ttyname(self.slave)
        self.renode=os.open(renode_path,os.O_RDWR|os.O_NOCTTY)
        tty.setraw(self.renode)
        self.delay=delay; self.error=None; self.stopped=threading.Event()
        self.thread=threading.Thread(target=self._run,daemon=True)
        self.thread.start()
    def _run(self):
        pending=deque(); next_byte=0
        try:
            while not self.stopped.is_set():
                ready,_,_=select.select([self.master,self.renode],[],[],.001)
                for fd in ready:
                    data=os.read(fd,4096)
                    if not data: raise OSError('Serial endpoint closed')
                    if fd==self.master:
                        pending.extend(data)
                        if len(pending)>1024*1024: raise OSError('Pacing queue exceeded 1 MiB')
                    else:
                        while data:
                            data=data[os.write(self.master,data):]
                now=time.monotonic()
                if pending and now>=next_byte:
                    os.write(self.renode,bytes([pending.popleft()]))
                    next_byte=now+self.delay
        except Exception as e: self.error=str(e)
    def close(self):
        self.stopped.set(); self.thread.join(timeout=2)
        for fd in [self.master,self.slave,self.renode]: os.close(fd)
