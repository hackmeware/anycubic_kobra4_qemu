#!/usr/bin/env python3
"""One native G28 X request, optionally followed by guarded Y after native X completion.
No retries, factory mode, homed-state writes, or synthetic completion.
"""
import argparse,json,os,pathlib,re,subprocess,sys,time
ROOT=pathlib.Path(__file__).resolve().parents[2]
def lines_marker(text,marker):return re.search(r'(?:^|\n)'+re.escape(marker)+r'\r?\n',text) is not None
def state_response(text):
 data=bytearray()
 for line in text.splitlines():
  if re.fullmatch(r'[0-7]{7,}\s+(?:[0-7]{3}\s*)+',line):data.extend(int(x,8) for x in line.split()[1:])
 pos=0;answer=None;success=False
 while pos+9<=len(data):
  n=int.from_bytes(data[pos:pos+3],'big');typ=data[pos+3];flags=data[pos+4];stream=int.from_bytes(data[pos+5:pos+9],'big');payload=bytes(data[pos+9:pos+9+n]);pos+=9+n
  if len(payload)!=n:raise ValueError('Incomplete HTTP2 response')
  if stream==1 and typ==1 and flags&1 and b'grpc-status\x010' in payload:success=True
  if stream==1 and typ==0 and len(payload)>=5 and payload[0]==0:
   size=int.from_bytes(payload[1:5],'big');pb=payload[5:]
   if len(pb)!=size:raise ValueError('Incomplete unary RPC payload')
   fields={};i=0
   def varint():
    nonlocal i
    value=0
    for shift in range(0,70,7):
     if i>=len(pb):raise ValueError('Truncated protobuf varint')
     b=pb[i];i+=1;value|=(b&127)<<shift
     if b<128:return value
    raise ValueError('Oversized protobuf varint')
   while i<len(pb):
    tag=varint()
    if tag&7!=2:raise ValueError('Unexpected PrinterState response wire type')
    length=varint();value=pb[i:i+length];i+=length
    if len(value)!=length:raise ValueError('Truncated PrinterState response')
    fields[tag>>3]=value
   if fields.get(1):raise ValueError('PrinterState returned nonempty error object')
   answer={'state':fields.get(2,b'').decode(),'state_message':fields.get(3,b'').decode()}
 if not success or answer is None or answer['state']!='ready':raise ValueError('RPC did not prove ready with grpc-status0')
 return answer

def parse_args(argv=None):
 p=argparse.ArgumentParser();p.add_argument('run_name');p.add_argument('--seconds',type=int,default=900);p.add_argument('--home-method',choices=['StartPrint','Homing'],default='StartPrint');p.add_argument('--home-y-after-x',action='store_true',help='After native X completion and X probe end, queue exactly one guarded normal Y Homing RPC');a=p.parse_args(argv)
 if a.home_y_after_x and a.home_method!='Homing':p.error('--home-y-after-x requires --home-method Homing')
 return a

def native_home_lines(text,axis):
 # Match complete original logger lines, not command echoes, partial lines or x2.
 clean=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text)
 pattern=r'(?m)^(\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+\] \[info\] \[\d+\] Home Rail Complete - stepper: '+re.escape(axis)+r')[ \t]*\r?\n'
 return set(re.findall(pattern,clean))

class YAfterX:
 """Passive log/marker tracking. This class never generates or sends a request."""
 def __init__(self,text,now):
  self.starts={'x':len(text),'y':None}
  self.old_lines={'x':native_home_lines(text,'x'),'y':set()}
  self.progress={axis:{'queued':False,'probe_finished':False,'native_completion_log_seen':False,'rpc_acceptance_verified':False} for axis in ('x','y')}
  self.progress['x'].update(queued=True,queued_at_virtual_time_ns=now)
 def observe(self,text,now):
  for axis in ('x','y'):
   start=self.starts[axis]
   if start is None:continue
   suffix=text[start:];begin=re.search(r'(?:^|\n)AUTO_G28_'+axis.upper()+r'_BEGIN\r?\n',suffix)
   if begin is None:continue
   suffix=suffix[begin.end():];status=self.progress[axis]
   end='AUTO_G28_X_SENT' if axis=='x' else 'AUTO_G28_Y_PROBE_DONE'
   if not status['probe_finished'] and lines_marker(suffix,end):
    status.update(probe_finished=True,probe_finished_observed_at_virtual_time_ns=now)
   new_lines=native_home_lines(suffix,axis)-self.old_lines[axis]
   if not status['native_completion_log_seen'] and new_lines:
    status.update(native_completion_log_seen=True,native_completion_observed_at_virtual_time_ns=now,native_completion_log=sorted(new_lines)[0])
 def can_queue_y(self):
  x=self.progress['x'];return x['probe_finished'] and x['native_completion_log_seen'] and not self.progress['y']['queued']
 def mark_y_queued(self,text,now):
  if not self.can_queue_y():raise ValueError('Y requires native X completion and X probe end, and may only be queued once')
  self.starts['y']=len(text);self.old_lines['y']=native_home_lines(text,'y')
  self.progress['y'].update(queued=True,queued_at_virtual_time_ns=now,client_timeout_seconds=5)
 def y_complete(self):
  y=self.progress['y'];return y['queued'] and y['probe_finished'] and y['native_completion_log_seen']

def main():
 a=parse_args()
 d=ROOT/'runs'/a.run_name
 if d.exists():raise SystemExit('Use a new run directory')
 env=dict(os.environ,RUN_SECONDS=str(a.seconds),PASSIVE_MOTOR_TRACE='1',RECOVERED_NOZZLE_NTC='1',ASSUMED_XY_DIAG_CABLE='1',MOTOR_ENABLE_WIRING='mcu-control-only',PASSIVE_NOZZLE_TRACE='1',PASSIVE_HOMING_GPIO='1',PASSIVE_TMC_TRACE='1')
 proc=subprocess.Popen([str(ROOT/'rv1106-at32-link/scripts/run_native_event_fixture.sh'),a.run_name],env=env)
 phase='waiting_for_native_ready';record={'scope':'Normal native RPC and G28 X only; no homing success inferred','phase':phase,'actions':[]};next_log=None;log_number=0;state_start=0;next_ready_poll=0;sequence=None
 if a.home_y_after_x:record['scope']='Normal native Homing X, then one Y only after native X-complete log and X probe end; RPC acknowledgement is not completion'
 def save():
  if d.exists():(d/'auto-progression.json').write_text(json.dumps(record,indent=2)+'\n')
 def append(text):
  with (d/'console-input.commands').open('ab') as f:f.write(text.encode())
 def commands(method,name,timeout=1,axis='X'):
  out=d/name
  args=[sys.executable,str(ROOT/'rv1106-at32-link/scripts/make_grpc_probe.py'),'--method',method,'--timeout-seconds',str(timeout),'--output',str(out)]
  if method=='StartPrint':args+=['--file-name','contact-x.gcode']
  if method=='Homing':args+=['--homing-axis',axis]
  subprocess.run(args,check=True,stdout=subprocess.DEVNULL)
  return out.with_suffix('.commands').read_text()
 try:
  while proc.poll() is None:
   if not (d/'console.bin').exists():time.sleep(.2);continue
   text=(d/'console.bin').read_text(errors='replace')
   ack=json.loads((d/'renode-step.json').read_text()) if (d/'renode-step.json').exists() else {};now=ack.get('virtual_time_ns',0)
   if phase=='waiting_for_native_ready' and re.search(r'Printer is ready at [0-9]+\.[0-9]+',text):
    state_start=len(text);append('echo AUTO_STATE_RPC\n'+commands('PrinterState','auto-state')+'echo AUTO_STATE_RPC_DONE\n');phase='checking_native_rpc';record['actions'].append({'action':'PrinterState','virtual_time_ns':now})
   elif phase=='waiting_for_native_ready' and lines_marker(text,'COUPLED_STARTUP_COMMANDS_DONE') and now>=next_ready_poll:
    append('tail -100 /data/main.stdout\ntail -100 /data/logs/avata_main.log\n');next_ready_poll=now+1000000000
   elif phase=='checking_native_rpc' and lines_marker(text[state_start:],'AUTO_STATE_RPC_DONE'):
    record['ready_response']=state_response(text[state_start:])
    prefix="echo AUTO_G28_X_BEGIN\nprintf 'G28 X\\nM400\\n' > /data/gcodes/contact-x.gcode\n" if a.home_method=='StartPrint' else 'echo AUTO_G28_X_BEGIN\n'
    append(prefix+commands(a.home_method,'auto-home')+'echo AUTO_G28_X_SENT\ntail -65 /data/main.stdout\ntail -65 /data/logs/avata_main.log\n')
    phase='g28_x_queued';record['actions'].append({'action':a.home_method+'_queued','axis':'X','virtual_time_ns':now});next_log=now+2000000000
    if a.home_y_after_x:
     sequence=YAfterX(text,now);record['sequential_homing']=sequence.progress
   elif phase in ('g28_x_queued','g28_x_probe_finished','g28_y_queued','g28_y_probe_finished') and now>=next_log and (log_number<8 or a.home_y_after_x):
    log_number+=1;append(f'echo AUTO_HOMING_LOG_{log_number}\ncat /proc/uptime\ntail -65 /data/main.stdout\ntail -65 /data/logs/avata_main.log\necho AUTO_HOMING_LOG_{log_number}_DONE\n');next_log=now+2000000000
   if phase=='g28_x_queued' and lines_marker(text,'AUTO_G28_X_SENT'):
    phase='g28_x_probe_finished';record['probe_finished']=True;record['acceptance_verified']=False
   if sequence is not None:
    sequence.observe(text,now)
    if sequence.can_queue_y():
     request=commands('Homing','auto-home-y',timeout=5,axis='Y')
     append('echo AUTO_G28_Y_BEGIN\n'+request+'echo AUTO_G28_Y_PROBE_DONE\ntail -65 /data/main.stdout\ntail -65 /data/logs/avata_main.log\n')
     sequence.mark_y_queued(text,now);phase='g28_y_queued';next_log=now+2000000000
     record['actions'].append({'action':'Homing_queued','axis':'Y','virtual_time_ns':now,'client_timeout_seconds':5})
    if sequence.y_complete():phase='g28_y_native_complete'
    elif sequence.progress['y']['probe_finished']:phase='g28_y_probe_finished'
    record['native_home_complete_log_seen']=sequence.progress['x']['native_completion_log_seen']
   else:record['native_home_complete_log_seen']=bool(re.search(r'Home Rail Complete - stepper: x',text))
   record['phase']=phase;record['last_ack_virtual_time_ns']=now;save();time.sleep(.2)
 except Exception as exc:
  record['controller_error']=str(exc);record['phase']='stopped_automatic_actions';save()
  # Leave bounded observation and normal cleanup to the owned launcher. Never retry.
 proc.wait();record['launcher_exit_code']=proc.returncode;save()
 if a.home_y_after_x:return proc.returncode or (2 if 'controller_error' in record else (0 if sequence is not None and sequence.y_complete() else 3))
 return proc.returncode or (2 if 'controller_error' in record else (0 if record.get('probe_finished') else 3))
if __name__=='__main__':sys.exit(main())
