import json,pathlib,sys,tempfile,time,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
from clock_coordinator import ClockCoordinator
class Q:
 def __init__(self,quantum):self.quantum=quantum;self.value=0;self.running=False;self.commands=[];self.reads_running=0
 def call(self,name,args=None):
  self.commands.append(name)
  if name=='cont':self.running=True;self.value+=self.quantum
  if name=='stop':self.running=False
 def now(self):
  if self.running:self.reads_running+=1;raise AssertionError('Measured MMIO while running')
  return self.value
 def close(self):pass
class Process:
 def poll(self):return 0
class Tests(unittest.TestCase):
 def run_gate(self,quantum,renode_ns):
  with tempfile.TemporaryDirectory() as folder:
   path=pathlib.Path(folder)/'time.json'
   def update(seq,t):
    tmp=path.with_suffix('.new');tmp.write_text(json.dumps(dict(enabled=True,time_went_backwards=False,epoch=0,sequence=seq,virtual_time_ns=t)));tmp.replace(path)
   update(0,0);q=Q(quantum)
   gate=ClockCoordinator(path,path,Process(),path.with_suffix('.report'),qmp_client=q,pulse_mode=True)
   update(1,renode_ns);deadline=time.monotonic()+1
   while not gate.error and q.value<renode_ns-999999 and time.monotonic()<deadline:time.sleep(.005)
   gate.close();return gate,q
 def test_measure_only_paused(self):
  gate,q=self.run_gate(200000,5000000)
  self.assertIsNone(gate.error);self.assertGreater(q.value,0);self.assertEqual(q.reads_running,0);self.assertFalse(q.running)
  self.assertLessEqual(gate.max_lead,5000000)
  for i,x in enumerate(q.commands):
   if x=='cont':self.assertEqual(q.commands[i+1],'stop')
 def test_overshoot_fails_closed(self):
  gate,q=self.run_gate(8000000,1000000)
  self.assertIn('lead bound after pulse',gate.error);self.assertFalse(q.running);self.assertEqual(q.reads_running,0)
 def test_stalled_clock_fails_closed(self):
  gate,q=self.run_gate(0,1000000)
  self.assertIn('no progress over 16 pulses',gate.error);self.assertFalse(q.running)
if __name__=='__main__':unittest.main()
