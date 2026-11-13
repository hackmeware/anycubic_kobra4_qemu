import json,pathlib,sys,tempfile,time,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
from renode_stepper import RenodeStepper,StepError
from lockstep_coordinator import LockstepCoordinator

class Process:
    def __init__(self):self.signals=[]
    def poll(self):return None
    def send_signal(self,s):self.signals.append(s)

def ack(path,step=0,ns=1000000000,**changes):
    value=dict(schema=1,source='renode-shared-mcu-step',step_id=step,
               virtual_time_ns=ns,epoch='test-epoch',enabled=True,paused=True,time_went_backwards=False)
    value.update(changes);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value));tmp.replace(path)

class StepperTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=pathlib.Path(self.tmp.name)/'ack.json';ack(self.path);self.proc=Process()
    def tearDown(self):self.tmp.cleanup()
    def test_exact(self):
        sent=[]
        def send(data):
            sent.append(data);ack(self.path,1,1001000000)
        s=RenodeStepper(self.proc,self.path,send,timeout=.03)
        self.assertEqual(s.step(),1001000000);self.assertIn(b'RunFor "0.001000000"',sent[0])
    def test_epoch_delta_id_paused(self):
        for change in ({'epoch':'new'},{'virtual_time_ns':1002000000},{'step_id':2},{'paused':False}):
            ack(self.path)
            def send(data):
                value=dict(step_id=1,virtual_time_ns=1001000000);value.update(change)
                ack(self.path,**value)
            s=RenodeStepper(self.proc,self.path,send,timeout=.03)
            with self.assertRaises(StepError):s.step()
            self.assertTrue(s.failed);self.assertTrue(self.proc.signals)
    def test_stale(self):
        s=RenodeStepper(self.proc,self.path,lambda data:None,timeout=.01)
        with self.assertRaisesRegex(StepError,'timed out'):s.step()
    def test_initial_stale_id(self):
        ack(self.path,4)
        with self.assertRaises(StepError):RenodeStepper(self.proc,self.path,lambda data:None,timeout=.01)
    def test_malformed(self):
        self.path.write_text('not json')
        with self.assertRaises(StepError):RenodeStepper(self.proc,self.path,lambda data:None,timeout=.01)

class Q:
    def __init__(self,overshoot=1):self.q=0;self.running=False;self.timeout=.01;self.overshoot=overshoot;self.targets=[]
    def call(self,name):
        if name=='stop':self.running=False;return {}
        if name=='query-status':return {'running':self.running}
    def now(self):return self.q
    def run_until(self,target):
        self.targets.append(target);time.sleep(.001);self.q=target+self.overshoot
        self.last_deadline=target;self.last_fired=target;self.last_stop=self.q
        return self.q
    def close(self):pass
class S:
    def __init__(self,q):self.initial_time_ns=1000000000;self.time_ns=self.initial_time_ns;self.step_id=0;self.timeout=.01;self.failed=False;self.q=q;self.paused=False
    def step(self,ns):
        assert not self.q.running
        if self.step_id:assert len(self.q.targets)==self.step_id
        self.time_ns+=ns;self.step_id+=1;return self.time_ns
    def pause(self,force=False):self.paused=True
class CoordinatorTests(unittest.TestCase):
    def test_both_directions(self):
        with tempfile.TemporaryDirectory() as d:
            q=Q();s=S(q);g=LockstepCoordinator(q,s,pathlib.Path(d)/'report')
            end=time.monotonic()+1
            while len(q.targets)<20 and not g.error and time.monotonic()<end:time.sleep(.002)
            g.close();self.assertIsNone(g.error);self.assertGreaterEqual(len(q.targets),20)
            self.assertEqual(g.max_lead,1);self.assertEqual(g.max_lag,1000000)
            self.assertTrue(s.paused)
    def test_overshoot(self):
        with tempfile.TemporaryDirectory() as d:
            q=Q(6000000);s=S(q);g=LockstepCoordinator(q,s,pathlib.Path(d)/'report')
            end=time.monotonic()+1
            while not g.error and time.monotonic()<end:time.sleep(.002)
            g.close();self.assertIn('lead bound',g.error);self.assertEqual(s.step_id,1)

if __name__=='__main__':unittest.main()
