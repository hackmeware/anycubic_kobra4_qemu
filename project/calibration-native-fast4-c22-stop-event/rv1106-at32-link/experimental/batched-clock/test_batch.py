import sys,pathlib,json,threading,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[2]/'scripts'))
from batched_event_clock import BatchedEventClockClient,ClockError

class Stream:
 def __init__(self,reply):self.reply=reply;self.timeout=1;self.responses=[]
 def write(self,data):self.responses=self.reply([json.loads(x) for x in data.splitlines()])
 def flush(self):pass
 def readline(self):
  if not self.responses:raise ClockError('injected pending timeout')
  return json.dumps(self.responses.pop(0)).encode()

def client(reply):
 q=BatchedEventClockClient.__new__(BatchedEventClockClient)
 q.stream=Stream(reply);q.timeout=1;q.serial=0;q.invalid=False;q.epoch=1;q.request_lock=threading.Lock()
 return q

class FakeClock(BatchedEventClockClient):
 def __init__(self,overrun=1):
  self.timeout=1;self.epoch=1;self.clock_epoch=1;self.value=0;self.target=0
  self.armed=False;self.fired=False;self.stop=-1;self.running=False;self.overrun=overrun
  self.callback=None
 def batch(self,requests):return [self.call(c,a) for c,a in requests]
 def call(self,c,a=None):
  if c=='query-status':return {'running':self.running}
  if c=='qom-get':return {'virtual-clock-epoch':self.clock_epoch,'virtual-time-ns':self.value,
   'virtual-deadline-armed':self.armed,'virtual-deadline-fired':self.fired,
   'virtual-deadline-stop-ns':self.stop,'virtual-deadline-fired-ns':self.callback}[a['property']]
  if c=='qom-set':self.target=a['value'];self.armed=True
  if c=='cont':
   self.value=self.target+self.overrun;self.stop=self.value;self.callback=self.target
   self.armed=False;self.fired=True
  if c=='stop':self.running=False

class Tests(unittest.TestCase):
 def test_sender_preserves_commands_without_wrapping(self):
  import io
  from step_sender import SerializedStepSender
  class Process:
   stdin=io.BytesIO()
   def poll(self):return None
  p=Process();data=b'mach set "main"\nemulation RunFor "0.001"\n'
  SerializedStepSender(p,threading.Lock())(data)
  self.assertEqual(p.stdin.getvalue(),data)
 def test_run_until_checks_actual_samples(self):
  q=FakeClock();self.assertEqual(q.run_until(1000000),1000001)
  self.assertEqual((q.last_deadline,q.last_fired,q.last_stop),(1000000,1000000,1000001))
 def test_run_until_bad_stop(self):
  with self.assertRaises(ClockError):FakeClock(-1).run_until(1000000)
 def test_run_until_changed_epoch_after_cont(self):
  q=FakeClock();original=q.call
  def changed(c,a=None):
   result=original(c,a)
   if c=='cont':q.clock_epoch=2
   return result
  q.call=changed
  with self.assertRaises(ClockError):q.run_until(1000000)
 def test_run_until_bad_callback(self):
  q=FakeClock();original=q.call
  def changed(c,a=None):
   result=original(c,a)
   if c=='cont':q.callback=q.stop+1
   return result
  q.call=changed
  with self.assertRaises(ClockError):q.run_until(1000000)
 def test_out_of_order_replies_matched(self):
  q=client(lambda rs:[{'id':r['id'],'return':r['arguments']['property']} for r in reversed(rs)])
  self.assertEqual(q.properties(['a','b']),['a','b']);self.assertFalse(q.invalid)
 def test_duplicate_rejected(self):
  q=client(lambda rs:[{'id':rs[0]['id'],'return':1}]*2)
  with self.assertRaises(ClockError):q.properties(['a','b'])
  self.assertTrue(q.invalid)
 def test_pending_timeout_invalidates(self):
  q=client(lambda rs:[{'id':rs[0]['id'],'return':1}])
  with self.assertRaises(ClockError):q.properties(['a','b'])
  self.assertTrue(q.invalid)
  with self.assertRaises(ClockError):q.properties(['a'])
 def test_reset_invalidates(self):
  q=client(lambda rs:[{'event':'RESET'}])
  with self.assertRaises(ClockError):q.properties(['a'])
  self.assertTrue(q.invalid)
 def test_concurrent_request_rejected(self):
  q=client(lambda rs:[]);q.request_lock.acquire()
  with self.assertRaises(ClockError):q.properties(['a'])
  with self.assertRaises(ClockError):q.call('query-status')
 def test_epoch_change_rejected(self):
  q=client(lambda rs:[{'id':rs[0]['id'],'return':2},{'id':rs[1]['id'],'return':100}])
  with self.assertRaises(ClockError):q.now()
 def test_good_clock(self):
  q=client(lambda rs:[{'id':rs[0]['id'],'return':1},{'id':rs[1]['id'],'return':100}])
  self.assertEqual(q.now(),100)
 def test_mutating_batch_rejected(self):
  q=client(lambda rs:[])
  with self.assertRaises(ClockError):q.batch([('cont',None)])
 def test_lead_and_lag_bounds_unchanged(self):
  from batched_lockstep import LockstepCoordinator
  g=LockstepCoordinator.__new__(LockstepCoordinator);g.q0=g.r0=g.max_lead=g.max_lag=0;g.max_lead_ns=5000000
  self.assertEqual(g._check(1000001,1000000,0),1)
  with self.assertRaises(RuntimeError):g._check(6000001,1000000,0)
  with self.assertRaises(RuntimeError):g._check(0,1000001,1000000)
if __name__=='__main__':unittest.main()
