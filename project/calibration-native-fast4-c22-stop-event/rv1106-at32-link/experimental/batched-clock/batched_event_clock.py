"""Client for explicitly enabled, event-driven QEMU virtual-deadline stops."""
import os,stat,time,json,threading
from diagnostic_timer_clock import QMPStream,StreamPair,ClockError

class BatchedEventClockClient(QMPStream):
    def __init__(self,reader,writer,timeout=3):
        self.request_lock=threading.Lock()
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
        streams=[]
        try:
            for suffix in ('.out','.in'):
                path=str(base)+suffix
                if not stat.S_ISFIFO(os.stat(path).st_mode):raise ClockError('QMP endpoint is not a FIFO')
                fd=os.open(path,os.O_RDWR|os.O_NONBLOCK)
                if not stat.S_ISFIFO(os.fstat(fd).st_mode):os.close(fd);raise ClockError('QMP endpoint changed')
                streams.append(os.fdopen(fd,'r+b',buffering=0))
            return cls(*streams,timeout=timeout)
        except Exception:
            for stream in streams:stream.close()
            raise
    def call(self,command,arguments=None):
        if not self.request_lock.acquire(blocking=False):raise ClockError('QMP request already pending')
        try:return super().call(command,arguments)
        finally:self.request_lock.release()
    def batch(self, requests):
        """Pipeline read-only queries; no concurrent owner or unresolved replies."""
        if not requests or any(c not in ('qom-get','query-status') for c,a in requests):
            raise ClockError('Batch requires nonempty read-only queries')
        if self.invalid:raise ClockError('QMP connection invalidated')
        if not self.request_lock.acquire(blocking=False):raise ClockError('QMP request already pending')
        try:
            pending={};wire=[];values=[None]*len(requests)
            for i,(command,args) in enumerate(requests):
                self.serial+=1;pending[self.serial]=i
                request={'execute':command,'id':self.serial}
                if args is not None:request['arguments']=args
                wire.append(json.dumps(request)+'\n')
            self.stream.write(''.join(wire).encode());self.stream.flush()
            limit=time.monotonic()+self.timeout;old_timeout=self.stream.timeout
            try:
                while pending:
                    remaining=limit-time.monotonic()
                    if remaining<=0:raise ClockError('QMP batch timed out with pending requests')
                    self.stream.timeout=remaining
                    reply=self._read()
                    if reply.get('event') in ('RESET','SHUTDOWN','GUEST_PANICKED'):
                        raise ClockError('QMP lifecycle event invalidated clock: '+reply['event'])
                    if 'event' in reply:continue
                    ident=reply.get('id')
                    if type(ident) is not int or ident not in pending:raise ClockError('Unexpected or duplicate QMP reply id')
                    if 'error' in reply or 'return' not in reply:raise ClockError('QMP batch command failed: '+str(reply))
                    values[pending.pop(ident)]=reply['return']
            finally:self.stream.timeout=old_timeout
            return values
        except Exception:
            self.invalid=True
            raise
        finally:self.request_lock.release()
    def properties(self,names):
        return self.batch([('qom-get',{'path':'/machine','property':name}) for name in names])
    def paused_now(self):
        status,epoch,value=self.batch([('query-status',None)]+[
            ('qom-get',{'path':'/machine','property':p}) for p in ('virtual-clock-epoch','virtual-time-ns')])
        if status.get('running') is not False:raise ClockError('QEMU unexpectedly running')
        self.validate_clock(epoch,value)
        return value
    def validate_clock(self,epoch,value):
        if type(epoch) is not int or epoch!=self.epoch:raise ClockError('QEMU clock epoch changed')
        if type(value) is not int or value<0:raise ClockError('Invalid QEMU virtual-time telemetry')
    def get(self,name):return self.call('qom-get',{'path':'/machine','property':name})
    def now(self):
        epoch,value=self.properties(['virtual-clock-epoch','virtual-time-ns'])
        self.validate_clock(epoch,value)
        return value
    def run_until(self,deadline):
        phase_start=time.monotonic()
        if not isinstance(deadline,int) or isinstance(deadline,bool):
            raise ClockError('Deadline must be integer nanoseconds')
        if deadline<=self.paused_now():raise ClockError('Deadline is not in the future')
        self.call('qom-set',{'path':'/machine','property':'virtual-deadline-ns','value':deadline})
        if self.get('virtual-deadline-armed') is not True:
            raise ClockError('QEMU did not arm virtual deadline')
        armed_at=time.monotonic()
        self.call('cont');limit=time.monotonic()+self.timeout
        while self.call('query-status').get('running'):
            if time.monotonic()>limit:
                self.call('stop')
                raise ClockError('QEMU did not stop at armed virtual deadline')
            time.sleep(.0005)
        stopped_at=time.monotonic()
        fired_flag,armed,stop,epoch,now,fired=self.properties([
            'virtual-deadline-fired','virtual-deadline-armed','virtual-deadline-stop-ns',
            'virtual-clock-epoch','virtual-time-ns','virtual-deadline-fired-ns'])
        self.validate_clock(epoch,now)
        if fired_flag is not True or armed is not False:
            raise ClockError('Unexpected pause without completed virtual deadline')
        if type(stop) is not int or stop<deadline or stop!=now:
            raise ClockError('Invalid deadline stop telemetry')
        if type(fired) is not int or not deadline<=fired<=stop:
            raise ClockError('Invalid deadline callback telemetry')
        self.last_phase_wall_s={'arming':armed_at-phase_start,'execution_wait':stopped_at-armed_at,'final_checks':time.monotonic()-stopped_at}
        self.last_deadline=deadline;self.last_stop=stop;self.last_fired=fired
        return now
    def close(self):self.stream.close()
