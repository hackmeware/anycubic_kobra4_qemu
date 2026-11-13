"""Bound QEMU virtual-time advance to measured shared Renode time.
A diagnostic co-simulation gate, not a fixed rate multiplier or cycle-accurate bus.
"""
import json,os,pathlib,signal,socket,threading,time
class QMP:
 def __init__(self,path):
  self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(2);self.sock.connect(str(path));self.file=self.sock.makefile('rwb',buffering=0);self.serial=0
  json.loads(self.file.readline());self.call('qmp_capabilities')
 def call(self,name,arguments=None):
  self.serial+=1;ident=self.serial;command={'execute':name,'id':ident}
  if arguments is not None:command['arguments']=arguments
  self.file.write((json.dumps(command)+'\n').encode())
  while True:
   line=self.file.readline()
   if not line:raise RuntimeError('QMP connection closed')
   result=json.loads(line)
   if result.get('id')!=ident:continue
   if 'error' in result:raise RuntimeError(str(result['error']))
   return result.get('return')
 def now(self):return self.call('qom-get',{'path':'/machine','property':'virtual-time-ns'})
 def close(self):self.file.close();self.sock.close()
class ClockCoordinator:
 def __init__(self,qmp_path,telemetry,process,output,max_lead_ns=5000000,qmp_client=None,pulse_mode=False,event_mode=False):
  self.process=process;self.path=pathlib.Path(telemetry);self.output=pathlib.Path(output);self.max_lead_ns=max_lead_ns
  self.pulse_mode=pulse_mode
  self.event_mode=event_mode
  if pulse_mode and event_mode:raise ValueError('Choose pulse or native-event clock gating')
  self.zero_progress_pulses=0
  self.error=None;self.stopped=threading.Event();self.started=time.monotonic();self.samples=[];self.max_lead=0;self.max_lag=0;self.transitions=0;self.running=False
  deadline=time.monotonic()+10
  while qmp_client is None and not pathlib.Path(qmp_path).exists():
   if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('QMP clock endpoint unavailable')
   time.sleep(.01)
  self.qmp=qmp_client if qmp_client is not None else QMP(qmp_path);self.qmp.call('stop');self.q0=self.qmp.now()
  d=self.read();self.r0=d['virtual_time_ns'];self.epoch=d['epoch'];self.sequence=d['sequence'];self.last_update=time.monotonic();self.previous_q=self.q0;self.previous_r=self.r0
  self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
 def read(self):
  d=json.loads(self.path.read_text())
  if not d.get('enabled') or d.get('time_went_backwards'):raise RuntimeError('Renode clock telemetry disabled or reset')
  return d
 def run(self):
  next_sample=0
  try:
   while not self.stopped.is_set():
    d=self.read();now=time.monotonic();r=d['virtual_time_ns']
    if d['epoch']!=self.epoch or r<self.previous_r:raise RuntimeError('Renode clock epoch changed or time regressed')
    if d['sequence']!=self.sequence:self.sequence=d['sequence'];self.last_update=now
    if now-self.last_update>2:raise RuntimeError('Renode clock telemetry stale for2wallseconds')
    q=self.qmp.now()
    if q<self.previous_q:raise RuntimeError('QEMU virtual clock regressed')
    self.previous_q=q;self.previous_r=r;skew=(q-self.q0)-(r-self.r0)
    self.max_lead=max(self.max_lead,skew);self.max_lag=max(self.max_lag,-skew)
    if skew>self.max_lead_ns:raise RuntimeError(f'QEMU exceeded measured virtual-time lead bound: {skew}ns')
    if self.event_mode and skew<=-1000000:
     self.running=True
     q=self.qmp.run_until(self.q0+(r-self.r0))
     self.running=False;self.transitions+=2
     if q<self.previous_q:raise RuntimeError('QEMU virtual clock regressed after deadline')
     self.previous_q=q;skew=(q-self.q0)-(r-self.r0)
     self.max_lead=max(self.max_lead,skew);self.max_lag=max(self.max_lag,-skew)
     if skew>self.max_lead_ns:raise RuntimeError(f'QEMU exceeded measured virtual-time lead bound after deadline: {skew}ns')
    elif self.pulse_mode and skew<=-1000000:
     # A multi-register MMIO observation is too slow to leave QEMU running.
     # Actuate one cont/stop pair, then measure and reject any overshoot.
     # OS/QMP scheduling means this cannot prevent an overlong pulse.
     # while paused. No wall-clock rate multiplier or relaxed lead bound.
     self.qmp.call('cont');self.running=True;self.transitions+=1
     self.qmp.call('stop');self.running=False;self.transitions+=1
     q=self.qmp.now()
     if q<self.previous_q:raise RuntimeError('QEMU virtual clock regressed after pulse')
     self.zero_progress_pulses=self.zero_progress_pulses+1 if q==self.previous_q else 0
     if self.zero_progress_pulses>=16:raise RuntimeError('QEMU diagnostic clock made no progress over 16 pulses')
     self.previous_q=q;skew=(q-self.q0)-(r-self.r0)
     self.max_lead=max(self.max_lead,skew);self.max_lag=max(self.max_lag,-skew)
     if skew>self.max_lead_ns:raise RuntimeError(f'QEMU exceeded measured virtual-time lead bound after pulse: {skew}ns')
    elif not self.pulse_mode and not self.event_mode and self.running and skew>=0:
     self.qmp.call('stop');self.running=False;self.transitions+=1
    elif not self.pulse_mode and not self.event_mode and not self.running and skew<=-1000000:
     self.qmp.call('cont');self.running=True;self.transitions+=1
    if now>=next_sample:
     self.samples.append({'wall_s':time.monotonic()-self.started,'qemu_delta_ns':q-self.q0,'renode_delta_ns':r-self.r0,'measured_skew_ns':skew,'qemu_running':self.running,**({'last_deadline_ns':self.qmp.last_deadline,'last_callback_ns':self.qmp.last_fired,'last_stop_ns':self.qmp.last_stop} if self.event_mode else {})});next_sample=now+.01
    self.stopped.wait(.0005 if self.running else .001)
  except Exception as e:
   self.error=str(e)
  finally:
   try:self.qmp.call('stop')
   except Exception:
    if self.process.poll() is None:self.process.send_signal(signal.SIGSTOP)
   self.running=False
 def close(self):
  self.stopped.set();self.thread.join(4)
  if self.thread.is_alive():
   self.error=self.error or 'Clock coordinator did not stop';self.process.send_signal(signal.SIGSTOP)
  report={'mode':'actual virtual-time QMP gating','pulse_mode':self.pulse_mode,'event_mode':self.event_mode,'clock_frequency_modified':False,'configured_max_lead_ns':self.max_lead_ns,'telemetry_period_ns':1000000,'max_measured_qemu_lead_ns':self.max_lead,'max_measured_qemu_lag_ns':self.max_lag,'transitions':self.transitions,'wall_seconds':time.monotonic()-self.started,'error':self.error,'samples':self.samples}
  self.output.write_text(json.dumps(report,indent=2)+'\n')
  self.qmp.close()
