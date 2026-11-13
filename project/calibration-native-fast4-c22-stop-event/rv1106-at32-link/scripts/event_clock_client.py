"""Client for explicitly enabled, event-driven QEMU virtual-deadline stops."""
import os,stat,time
from diagnostic_timer_clock import QMPStream,StreamPair,ClockError

class EventClockClient(QMPStream):
    def __init__(self,reader,writer,timeout=3):
        super().__init__(StreamPair(reader,writer,timeout))
        self.timeout=timeout
        if self.get('virtual-deadline-enabled') is not True:
            raise ClockError('QEMU virtual deadline mode was not explicitly enabled')
        self.epoch=self.get('virtual-clock-epoch')
        if not isinstance(self.epoch,int) or isinstance(self.epoch,bool) or self.epoch<0:
            raise ClockError('Invalid QEMU clock epoch')
        self.last_deadline=None;self.last_stop=None;self.last_fired=None
    @classmethod
    def from_pipes(cls,base,timeout=3):
        return open_clock_pipes(cls,base,timeout)
    def get(self,name):return self.call('qom-get',{'path':'/machine','property':name})
    def now(self):
        if self.get('virtual-clock-epoch')!=self.epoch:
            raise ClockError('QEMU clock epoch changed')
        value=self.get('virtual-time-ns')
        if not isinstance(value,int) or isinstance(value,bool) or value<0:
            raise ClockError('Invalid QEMU virtual-time telemetry')
        return value
    def run_until(self,deadline):
        if not isinstance(deadline,int) or isinstance(deadline,bool):
            raise ClockError('Deadline must be integer nanoseconds')
        if self.call('query-status').get('running') is not False:
            raise ClockError('Deadline must be armed while paused')
        if deadline<=self.now():raise ClockError('Deadline is not in the future')
        self.call('qom-set',{'path':'/machine','property':'virtual-deadline-ns','value':deadline})
        if self.get('virtual-deadline-armed') is not True:
            raise ClockError('QEMU did not arm virtual deadline')
        self.call('cont');limit=time.monotonic()+self.timeout
        while self.call('query-status').get('running'):
            if time.monotonic()>limit:
                self.call('stop')
                raise ClockError('QEMU did not stop at armed virtual deadline')
            time.sleep(.0005)
        if self.get('virtual-deadline-fired') is not True or self.get('virtual-deadline-armed') is not False:
            raise ClockError('Unexpected pause without completed virtual deadline')
        stop=self.get('virtual-deadline-stop-ns');now=self.now()
        if not isinstance(stop,int) or isinstance(stop,bool) or stop<deadline or stop!=now:
            raise ClockError('Invalid deadline stop telemetry')
        fired=self.get('virtual-deadline-fired-ns')
        if not isinstance(fired,int) or isinstance(fired,bool) or not deadline<=fired<=stop:
            raise ClockError('Invalid deadline callback telemetry')
        self.last_deadline=deadline;self.last_stop=stop;self.last_fired=fired
        return now
    def close(self):self.stream.close()


def open_clock_pipes(client_class,base,timeout=3):
    """Share FIFO validation and failure cleanup across explicit clock clients."""
    streams=[]
    try:
        for suffix in ('.out','.in'):
            path=str(base)+suffix
            if not stat.S_ISFIFO(os.stat(path).st_mode):raise ClockError('QMP endpoint is not a FIFO')
            fd=os.open(path,os.O_RDWR|os.O_NONBLOCK)
            if not stat.S_ISFIFO(os.fstat(fd).st_mode):os.close(fd);raise ClockError('QMP endpoint changed')
            streams.append(os.fdopen(fd,'r+b',buffering=0))
        return client_class(*streams,timeout=timeout)
    except Exception:
        for stream in streams:stream.close()
        raise
