import pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
from run_link import parser,execution_args
class ExecutionMode(unittest.TestCase):
 def test_alternate_wiring_requires_dynamic(self):
  with self.assertRaises(ValueError):execution_args(parser().parse_args(['--motor-enable-wiring','mcu-control-only']))
 def test_alternate_wiring_explicit(self):
  self.assertEqual(execution_args(parser().parse_args(['--motor-enable-wiring','mcu-control-only','--shared-mcus','--motor-plant','electromechanical-driver'])),[])
 def test_default_unchanged(self):self.assertEqual(execution_args(parser().parse_args([])),[])
 def test_explicit(self):
  a=parser().parse_args(['--clock-coupled','--clock-source','qom-deadline','--qemu-icount-shift','0'])
  self.assertEqual(execution_args(a),['-icount','shift=0,align=off,sleep=off'])
 def test_requires_deadline(self):
  with self.assertRaises(ValueError):execution_args(parser().parse_args(['--qemu-icount-shift','0']))
 def test_lockstep_explicit(self):
  a=parser().parse_args(['--clock-lockstep','--shared-mcus','--clock-coupled','--clock-source','qom-deadline','--qemu-icount-shift','0'])
  self.assertEqual(execution_args(a),['-icount','shift=0,align=off,sleep=off'])
 def test_lockstep_requires_all_clocks(self):
  with self.assertRaises(ValueError):execution_args(parser().parse_args(['--clock-lockstep']))
 def test_lockstep_rejects_live_monitor(self):
  a=parser().parse_args(['--clock-lockstep','--shared-mcus','--clock-coupled','--clock-source','qom-deadline','--qemu-icount-shift','0','--peer-monitor-input','/tmp/test'])
  with self.assertRaises(ValueError):execution_args(a)
if __name__=='__main__':unittest.main()
