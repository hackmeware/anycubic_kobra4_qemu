import struct
import unittest
from baseline_network import network_args,enable_usb_host,validate_runner_args
class Tests(unittest.TestCase):
 def test_dt(self):
  nodes={'':{},'/old@ffb00000':{'status':b'okay\0'}}
  out=enable_usb_host(nodes)
  self.assertEqual(nodes['/old@ffb00000']['status'],b'okay\0')
  self.assertEqual(out['/old@ffb00000']['status'],b'disabled\0')
  self.assertEqual(out['/usbdrd/usb@ffb00000']['interrupts'],struct.pack('>III',0,54,4))
 def test_argv(self):
  args=['-M','rv1106','-kernel','/tmp/test.elf','-monitor','pipe:/tmp/monitor']
  self.assertEqual(validate_runner_args(args),args)
 def test_monitor_none(self):
  self.assertEqual(validate_runner_args(['-M','rv1106','-kernel','x','-monitor','none']),['-M','rv1106','-kernel','x','-monitor','none'])
 def test_reject(self):
  for args in (['-netdev','user'],['-M','virt','-kernel','x'],['-M','rv1106','-kernel','x','-icount','shift=0']):
   with self.assertRaises(ValueError):validate_runner_args(args)
 def test_coupled(self):
  args=['-M','rv1106,virtual-deadline-enabled=on','-kernel','x','-S','-qmp','pipe:/tmp/private/qmp','-icount','shift=0,align=off,sleep=off']
  self.assertEqual(validate_runner_args(args),args)
  for bad in (args[:-2],args[:-1]+['shift=1,align=off,sleep=off'],args[:7]+['unix:/tmp/qmp']+args[8:]):
   with self.assertRaises(ValueError):validate_runner_args(bad)
 def test_modes(self):
  self.assertEqual(network_args(),['-nic','none'])
  self.assertIn('restrict=on',network_args('isolated',18912,9895)[1])
  self.assertIn('hostfwd=tcp:127.0.0.1:9895-:9883',network_args('internet',18912,9895)[1])
 def test_port(self):
  with self.assertRaises(ValueError):network_args('isolated',12,12)
if __name__=='__main__':unittest.main()
