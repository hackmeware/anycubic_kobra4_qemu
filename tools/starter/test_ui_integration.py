import unittest,ui_integration as u
class Tests(unittest.TestCase):
 def test_sgr(self):self.assertEqual(u.normalize_console('\x1b[31mx\x1b[0m\r\n'),'x\n')
 def test_control_rejected(self):
  for s in ['\x1b[2J','\x1b]title\x07','\x08','\x7f']:
   with self.assertRaises(ValueError):u.normalize_console(s)
 def test_uniform(self):self.assertFalse(u.nonuniform(b'P6\n480 320\n255\n'+bytes(480*320*3)))
 def test_nonuniform(self):self.assertTrue(u.nonuniform(b'P6\n480 320\n255\n'+b'\x01'+bytes(480*320*3-1)))
 def test_geometry(self):
  with self.assertRaises(ValueError):u.nonuniform(b'P6\n1 1\n255\n123')
 def test_stop_needs_all(self):
  good={'ui_connection_ready':True,'live_frame_available':True,'loopback_viewer_verified':True}
  self.assertTrue(u.should_stop(good))
  for k in good:self.assertFalse(u.should_stop({**good,k:False}))
  self.assertFalse(u.should_stop({**good,'parse_error':'bad'}))
if __name__=='__main__':unittest.main()
