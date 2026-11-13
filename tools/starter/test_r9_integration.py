import unittest,tempfile
from pathlib import Path
from types import SimpleNamespace
import r9_clock_guard as guard
import start_diagnostic as starter
class R9Tests(unittest.TestCase):
 def test_step_below_bound(self):
  with tempfile.TemporaryDirectory() as d:
   calls=[];stepper=SimpleNamespace(time_ns=0)
   guard.guarded_step(stepper,calls.append,Path(d),1000000)
   self.assertEqual(calls,[1000000]);self.assertFalse((Path(d)/'stop-request').exists())
 def test_boundary_refuses_without_advancing(self):
  with tempfile.TemporaryDirectory() as d:
   calls=[];stepper=SimpleNamespace(time_ns=guard.LIMIT_NS-1000000)
   with self.assertRaises(RuntimeError):guard.guarded_step(stepper,calls.append,Path(d),1000000)
   self.assertEqual(calls,[]);self.assertTrue((Path(d)/'stop-request').exists())
 def test_bound_lower_than_historical(self):self.assertLess(guard.LIMIT_NS,720000000000)
 def test_observer_installs_guard_before_run(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'observer.py';starter.write_process_observer(p,r9=True);s=p.read_text();compile(s,str(p),'exec')
   self.assertLess(s.index('r9_clock_guard.install'),s.index('runpy.run_path'))
 def test_profile_motor_required(self):self.assertTrue(starter.profile_settings('r9-calibration',Path('/inputs'),Path('/out'))['motor'])
if __name__=='__main__':unittest.main()
