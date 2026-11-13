"""Explicit paused Renode RunFor/actual-time acknowledgement handshake."""
import json
import pathlib
import signal
import threading
import time

class StepError(RuntimeError):
    pass

class RenodeStepper:
    def __init__(self, process, ack_path, send_callback, timeout=10):
        self.process=process
        self.path=pathlib.Path(ack_path).resolve()
        if any(c in str(self.path) for c in '\n\r"\\'):
            raise ValueError('Unsafe Renode acknowledgement path')
        if timeout<=0:raise ValueError('Positive step timeout required')
        self.send_callback=send_callback;self.timeout=timeout
        self.lock=threading.Lock();self.failed=False;self.step_id=0
        self.epoch=None;self.time_ns=None
        ack=self._wait(0,initial=True)
        self.epoch=ack['epoch'];self.time_ns=ack['virtual_time_ns']
        self.initial_time_ns=self.time_ns

    def _read(self):
        try:
            value=json.loads(self.path.read_text())
        except FileNotFoundError:return None
        except Exception as exc:raise StepError('Malformed Renode step acknowledgement') from exc
        if not isinstance(value,dict):raise StepError('Step acknowledgement must be an object')
        for key in ('step_id','virtual_time_ns'):
            if type(value.get(key)) is not int or value[key]<0:
                raise StepError('Invalid step acknowledgement '+key)
        if (value.get('schema')!=1 or value.get('source')!='renode-shared-mcu-step'
            or value.get('enabled') is not True or value.get('paused') is not True
            or value.get('time_went_backwards') is not False
            or not isinstance(value.get('epoch'),str) or not value['epoch']):
            raise StepError('Invalid or unpaused Renode step acknowledgement')
        return value

    def _wait(self, expected, initial=False):
        deadline=time.monotonic()+self.timeout
        while True:
            if self.process.poll() is not None:raise StepError('Renode process exited')
            value=self._read()
            if value is not None:
                if not initial and value['epoch']!=self.epoch:
                    raise StepError('Renode step epoch changed')
                if value['step_id']==expected:return value
                if initial or value['step_id']!=expected-1:
                    raise StepError('Renode step id mismatch')
                if value['virtual_time_ns']!=self.time_ns:
                    raise StepError('Previous step acknowledgement changed')
            if time.monotonic()>=deadline:raise StepError('Renode step acknowledgement timed out')
            time.sleep(.001)

    def step(self,duration_ns=1000000):
        if type(duration_ns) is not int or duration_ns<=0 or duration_ns%1000:
            raise ValueError('Renode slice must be a positive whole number of microseconds')
        with self.lock:
            if self.failed:raise StepError('Renode stepper previously failed')
            try:
                old=self._read()
                if old is None or old['epoch']!=self.epoch or old['step_id']!=self.step_id or old['virtual_time_ns']!=self.time_ns:
                    raise StepError('Renode acknowledgement changed outside coordinator')
                expected=self.step_id+1
                seconds=f'{duration_ns//1000000000}.{duration_ns%1000000000:09d}'
                command=(f'mach set "main"\nemulation RunFor "{seconds}"\n'
                         f'sysbus.timeTelemetry PublishStep "{self.path}" {expected}\n')
                self.send_callback(command.encode())
                ack=self._wait(expected)
                if ack['virtual_time_ns']!=self.time_ns+duration_ns:
                    raise StepError('Renode actual step delta differs from requested slice')
                self.step_id=expected;self.time_ns=ack['virtual_time_ns']
                return self.time_ns
            except Exception as error:
                self.failed=True
                try:
                    self.pause(force=True)
                except Exception as pause_error:
                    error.add_note('Renode forced pause failed: '+str(pause_error))
                raise

    def pause(self,force=False):
        if self.process.poll() is not None:return
        if force:
            self.process.send_signal(signal.SIGSTOP)
            return
        self.send_callback(b'pause\n')
