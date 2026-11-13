import json,pathlib,sys,tempfile,time,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
from event_clock_client import EventClockClient,ClockError
from clock_coordinator import ClockCoordinator
class Client(EventClockClient):
 def __init__(self,overrun=0):
  self.timeout=1
  self.epoch=1;self.value=0;self.running=False;self.overrun=overrun;self.target=0;self.armed=False;self.fired=False;self.stop=-1;self.epoch_value=1;self.last_deadline=None;self.last_stop=None;self.last_fired=None
 def call(self,name,args=None):
  if name=='query-status':return {'running':self.running}
  if name=='qom-get':return {'virtual-clock-epoch':self.epoch_value,'virtual-time-ns':self.value,'virtual-deadline-armed':self.armed,'virtual-deadline-fired':self.fired,'virtual-deadline-stop-ns':self.stop,'virtual-deadline-fired-ns':self.target}[args['property']]
  if name=='qom-set':self.target=args['value'];self.armed=True;self.fired=False;self.stop=-1
  if name=='cont':self.value=self.target+self.overrun;self.stop=self.value;self.armed=False;self.fired=True;self.running=False
  if name=='stop':self.running=False
 def close(self):pass
class Process:
 def poll(self):return 0
class Tests(unittest.TestCase):
 def test_valid_deadline(self):
  q=Client(1000);self.assertEqual(q.run_until(1000000),1001000);self.assertFalse(q.running);self.assertEqual(q.last_stop,1001000)
 def test_past_deadline_rejected(self):
  q=Client();q.value=10
  with self.assertRaises(ClockError):q.run_until(10)
 def test_running_rejected(self):
  q=Client();q.running=True
  with self.assertRaises(ClockError):q.run_until(1000)
 def test_epoch_change_rejected(self):
  q=Client();q.epoch_value=2
  with self.assertRaises(ClockError):q.now()
 def test_bad_stop_rejected(self):
  q=Client(-1)
  with self.assertRaises(ClockError):q.run_until(1000)
 def test_bad_callback_rejected(self):
  q=Client();original=q.get
  q.get=lambda name: -1 if name=='virtual-deadline-fired-ns' else original(name)
  with self.assertRaises(ClockError):q.run_until(1000)
 def gate(self,overrun):
  with tempfile.TemporaryDirectory() as folder:
   path=pathlib.Path(folder)/'telemetry.json'
   def write(seq,t):
    tmp=path.with_suffix('.new');tmp.write_text(json.dumps(dict(enabled=True,time_went_backwards=False,epoch=0,sequence=seq,virtual_time_ns=t)));tmp.replace(path)
   write(0,0);q=Client(overrun);g=ClockCoordinator(path,path,Process(),path.with_suffix('.report'),qmp_client=q,event_mode=True)
   write(1,1000000);deadline=time.monotonic()+1
   while not g.error and q.value==0 and time.monotonic()<deadline:time.sleep(.005)
   g.close();return g,q
 def test_gate_success(self):
  g,q=self.gate(1000);self.assertIsNone(g.error);self.assertEqual(g.max_lead,1000);self.assertFalse(q.running)
 def test_gate_overshoot_preserved(self):
  g,q=self.gate(6000000);self.assertIn('lead bound after deadline',g.error);self.assertFalse(q.running)
if __name__=='__main__':unittest.main()
