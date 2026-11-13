import contextlib,importlib.util,io,json,pathlib,sys,tempfile,unittest
from unittest import mock
p=pathlib.Path(__file__).resolve().parents[1]/'scripts/run_native_homing_observation.py'
s=importlib.util.spec_from_file_location('observation',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def frame(typ,flags,payload):return len(payload).to_bytes(3,'big')+bytes([typ,flags])+b'\0\0\0\1'+payload
def response(state=b'ready',error=b'',success=True):
 pb=(b'\x0a'+bytes([len(error)])+error if error else b'')+b'\x12'+bytes([len(state)])+state
 data=frame(0,0,b'\0'+len(pb).to_bytes(4,'big')+pb)+frame(1,1,b'grpc-status\x01'+(b'0' if success else b'1'))
 return '\n'.join(f'{i:07o} '+' '.join(f'{x:03o}' for x in data[i:i+16]) for i in range(0,len(data),16))
class Tests(unittest.TestCase):
 def test_ready(self):self.assertEqual(m.state_response(response())['state'],'ready')
 def test_not_ready(self):
  with self.assertRaises(ValueError):m.state_response(response(b'shutdown'))
 def test_error(self):
  with self.assertRaises(ValueError):m.state_response(response(error=b'error'))
 def test_transport_failure(self):
  with self.assertRaises(ValueError):m.state_response(response(success=False))
 def test_empty(self):
  with self.assertRaises(ValueError):m.state_response('')
 def test_marker(self):
  self.assertFalse(m.lines_marker('echo AUTO_STATE_RPC_DONE\n','AUTO_STATE_RPC_DONE'))
  self.assertTrue(m.lines_marker('AUTO_STATE_RPC_DONE\r\n','AUTO_STATE_RPC_DONE'))


ROOT = pathlib.Path(__file__).resolve().parents[2]
BASELINE = ROOT / 'evidence/home-y-after-x/run_native_homing_observation.before.py'

def home_line(axis, stamp='16.426'):
 return '\x1b[32m[1970-01-01 00:00:'+stamp+'] [info] [447] Home Rail Complete - stepper: '+axis+'\x1b[m\n'

def load_baseline():
 spec=importlib.util.spec_from_file_location('observation_before',BASELINE)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return module

class SequentialTests(unittest.TestCase):
 def test_option_requires_explicit_homing_method(self):
  for args in [['test','--home-y-after-x'],['test','--home-method','StartPrint','--home-y-after-x']]:
   with self.subTest(args=args),contextlib.redirect_stderr(io.StringIO()),mock.patch.object(m.subprocess,'Popen') as launch,mock.patch.object(m.sys,'argv',['observer',*args]),self.assertRaises(SystemExit) as caught:m.main()
   self.assertEqual(caught.exception.code,2);launch.assert_not_called()
  args=m.parse_args(['test','--home-method','Homing','--home-y-after-x'])
  self.assertTrue(args.home_y_after_x)
  self.assertFalse(m.parse_args(['test']).home_y_after_x)

 def test_original_native_line_only(self):
  self.assertEqual(len(m.native_home_lines(home_line('x'),'x')),1)
  self.assertFalse(m.native_home_lines(home_line('x'),'y'))
  for text in ['echo Home Rail Complete - stepper: x\n','Home Rail Complete - stepper: x\n',home_line('x2'),home_line('x').rstrip('\n')]:
   with self.subTest(text=text):self.assertFalse(m.native_home_lines(text,'x'))
  self.assertEqual(len(m.native_home_lines(home_line('x')+home_line('x','17.000'),'x')),2)

 def test_both_x_events_required_in_either_order(self):
  for first,second in [(home_line('x'),'AUTO_G28_X_SENT\n'),('AUTO_G28_X_SENT\n',home_line('x'))]:
   sequence=m.YAfterX('',0);text='AUTO_G28_X_BEGIN\n'+first;sequence.observe(text,1)
   self.assertFalse(sequence.can_queue_y())
   text+=second;sequence.observe(text,2);self.assertTrue(sequence.can_queue_y())
   sequence.mark_y_queued(text,2);self.assertFalse(sequence.can_queue_y())
   for _ in range(3):sequence.observe(text,3);self.assertFalse(sequence.can_queue_y())
   with self.assertRaises(ValueError):sequence.mark_y_queued(text,3)

 def test_stale_pre_begin_and_echo_markers_do_not_trigger(self):
  stale=home_line('x')+'AUTO_G28_X_BEGIN\nAUTO_G28_X_SENT\n'
  sequence=m.YAfterX(stale,0)
  text=stale+'echo AUTO_G28_X_BEGIN\necho AUTO_G28_X_SENT\n'+home_line('x','17.000')
  sequence.observe(text,1);self.assertFalse(sequence.can_queue_y())
  text+='AUTO_G28_X_BEGIN\nAUTO_G28_X_SENT\n'+home_line('x')
  sequence.observe(text,2);self.assertFalse(sequence.can_queue_y())
  text+=home_line('x','18.000');sequence.observe(text,3);self.assertTrue(sequence.can_queue_y())

 def test_partial_probe_end_does_not_trigger(self):
  sequence=m.YAfterX('',0);text='AUTO_G28_X_BEGIN\n'+home_line('x')+'AUTO_G28_X_SENT'
  sequence.observe(text,1);self.assertFalse(sequence.can_queue_y())
  sequence.observe(text+'\n',2);self.assertTrue(sequence.can_queue_y())

 def test_y_queue_probe_end_and_completion_are_independent(self):
  sequence=m.YAfterX('',0);text='AUTO_G28_X_BEGIN\n'+home_line('x')+'AUTO_G28_X_SENT\n'+home_line('y')
  sequence.observe(text,1);sequence.mark_y_queued(text,2)
  self.assertTrue(sequence.progress['y']['queued']);self.assertFalse(sequence.y_complete())
  text+='AUTO_G28_Y_BEGIN\nAUTO_G28_Y_PROBE_DONE\n'+home_line('y')
  sequence.observe(text,3);self.assertTrue(sequence.progress['y']['probe_finished']);self.assertFalse(sequence.y_complete())
  text+=home_line('y','25.000');sequence.observe(text,4);self.assertTrue(sequence.y_complete())
  y=sequence.progress['y'];self.assertEqual(y['queued_at_virtual_time_ns'],2);self.assertEqual(y['probe_finished_observed_at_virtual_time_ns'],3);self.assertEqual(y['native_completion_observed_at_virtual_time_ns'],4)
  self.assertFalse(y['rpc_acceptance_verified'])

 def run_fake(self,module,options,steps,fail_y=False):
  """All launcher/generator subprocesses and sleeps are mocked; never runs firmware."""
  with tempfile.TemporaryDirectory() as directory:
   root=pathlib.Path(directory);run=root/'runs'/'test';calls=[];timeline=[]
   class FakeProcess:
    returncode=None
    def __init__(self):run.mkdir(parents=True);(run/'console-input.commands').write_text('');self.index=0;self.text=''
    def poll(self):
     if self.index>=len(steps):self.returncode=0;return 0
     now,addition=steps[self.index];self.index+=1;self.text+=addition
     (run/'console.bin').write_text(self.text);(run/'renode-step.json').write_text(json.dumps({'virtual_time_ns':now}))
     timeline.append((now,(run/'console-input.commands').read_text()))
     return None
    def wait(self):self.returncode=0;return 0
   def generate(args,**kwargs):
    method=args[args.index('--method')+1];timeout=args[args.index('--timeout-seconds')+1]
    axis=args[args.index('--homing-axis')+1] if '--homing-axis' in args else None
    calls.append({'method':method,'axis':axis,'timeout':timeout,'filename':args[args.index('--file-name')+1] if '--file-name' in args else None})
    if fail_y and axis=='Y':raise RuntimeError('offline injected generator failure')
    pathlib.Path(args[args.index('--output')+1]).with_suffix('.commands').write_text(f'echo OFFLINE_PROBE_{method}_{axis}_{timeout}\n')
   with mock.patch.object(module,'ROOT',root),mock.patch.object(module.sys,'argv',['observer','test',*options]),mock.patch.object(module.subprocess,'Popen',side_effect=lambda *a,**k:FakeProcess()),mock.patch.object(module.subprocess,'run',side_effect=generate),mock.patch.object(module.time,'sleep'):
    result=module.main()
   return result,(run/'console-input.commands').read_text(),json.loads((run/'auto-progression.json').read_text()),calls,timeline

 def prefix_steps(self):
  return [(0,'Printer is ready at 1.0\n'),(1,response()+'\nAUTO_STATE_RPC_DONE\n')]

 def test_default_behavior_matches_checkpoint_for_both_methods(self):
  steps=self.prefix_steps()+[(3_000_000_000,'AUTO_G28_X_BEGIN\nAUTO_G28_X_SENT\n'+home_line('x'))]+[(i*2_000_000_000,'') for i in range(2,15)]
  for options in [[],['--home-method','Homing']]:
   with self.subTest(options=options):
    before=self.run_fake(load_baseline(),options,steps);after=self.run_fake(m,options,steps)
    self.assertEqual(after,before)
    self.assertEqual(len(after[3]),2);self.assertNotIn('sequential_homing',after[2]);self.assertNotIn('AUTO_G28_Y',after[1])

 def test_main_queues_y_exactly_once_with_five_second_timeout(self):
  steps=self.prefix_steps()+[(3_000_000_000,'AUTO_G28_X_BEGIN\nAUTO_G28_X_SENT\n'),(5_000_000_000,home_line('x')),(7_000_000_000,'AUTO_G28_Y_BEGIN\n'),(9_000_000_000,'AUTO_G28_Y_PROBE_DONE\n'),(11_000_000_000,home_line('y','25.000')),(13_000_000_000,home_line('x')+home_line('y','25.000'))]
  result,commands,record,calls,timeline=self.run_fake(m,['--home-method','Homing','--home-y-after-x'],steps)
  self.assertEqual(result,0);self.assertEqual([c['axis'] for c in calls],[None,'X','Y']);self.assertEqual(calls[-1]['timeout'],'5')
  self.assertEqual(commands.count('echo AUTO_G28_Y_BEGIN\n'),1);self.assertEqual(commands.count('echo AUTO_G28_Y_PROBE_DONE\n'),1)
  self.assertEqual(record['phase'],'g28_y_native_complete');self.assertEqual(len([a for a in record['actions'] if a.get('axis')=='Y']),1)
  y=record['sequential_homing']['y'];self.assertEqual(y['queued_at_virtual_time_ns'],5_000_000_000);self.assertEqual(y['probe_finished_observed_at_virtual_time_ns'],9_000_000_000);self.assertEqual(y['native_completion_observed_at_virtual_time_ns'],11_000_000_000)
  self.assertFalse(y['rpc_acceptance_verified'])
  self.assertNotIn('AUTO_G28_Y',dict(timeline)[5_000_000_000])

 def test_main_never_queues_y_with_only_one_x_event(self):
  for event in ['AUTO_G28_X_SENT\n',home_line('x')]:
   with self.subTest(event=event):
    steps=self.prefix_steps()+[(3_000_000_000,'AUTO_G28_X_BEGIN\n'+event),(5_000_000_000,'')]
    result,commands,record,calls,_=self.run_fake(m,['--home-method','Homing','--home-y-after-x'],steps)
    self.assertEqual(result,3);self.assertNotIn('AUTO_G28_Y',commands);self.assertEqual(len(calls),2)

 def test_y_probe_end_does_not_infer_home(self):
  steps=self.prefix_steps()+[(3_000_000_000,'AUTO_G28_X_BEGIN\n'+home_line('x')+'AUTO_G28_X_SENT\n'),(5_000_000_000,'AUTO_G28_Y_BEGIN\nAUTO_G28_Y_PROBE_DONE\n')]
  result,_,record,_,_=self.run_fake(m,['--home-method','Homing','--home-y-after-x'],steps)
  self.assertEqual(result,3);self.assertEqual(record['phase'],'g28_y_probe_finished');self.assertFalse(record['sequential_homing']['y']['native_completion_log_seen'])

 def test_opt_in_keeps_logging_past_old_eight_log_cap(self):
  steps=self.prefix_steps()+[(3_000_000_000,'AUTO_G28_X_BEGIN\nAUTO_G28_X_SENT\n')]+[(i*2_000_000_000,'') for i in range(2,12)]+[(24_000_000_000,home_line('x')),(26_000_000_000,'AUTO_G28_Y_BEGIN\nAUTO_G28_Y_PROBE_DONE\n'),(28_000_000_000,'')]
  result,commands,record,calls,_=self.run_fake(m,['--home-method','Homing','--home-y-after-x'],steps)
  self.assertEqual(result,3);self.assertIn('echo AUTO_HOMING_LOG_13\n',commands);self.assertEqual(len(calls),3)
  self.assertEqual(record['phase'],'g28_y_probe_finished')

 def test_generator_failure_stops_without_retry_or_queued_claim(self):
  steps=self.prefix_steps()+[(3_000_000_000,'AUTO_G28_X_BEGIN\n'+home_line('x')+'AUTO_G28_X_SENT\n')]
  result,commands,record,calls,_=self.run_fake(m,['--home-method','Homing','--home-y-after-x'],steps,fail_y=True)
  self.assertEqual(result,2);self.assertEqual([c['axis'] for c in calls].count('Y'),1);self.assertNotIn('AUTO_G28_Y',commands)
  self.assertFalse(record['sequential_homing']['y']['queued']);self.assertEqual(record['phase'],'stopped_automatic_actions')

if __name__=='__main__':unittest.main()
