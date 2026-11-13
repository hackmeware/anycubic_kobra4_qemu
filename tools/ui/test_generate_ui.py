import unittest,generate_ui as g
class Tests(unittest.TestCase):
 def test_bounds(self):
  commands,setup,backend=g.generate('ui-12345678')
  self.assertLess(max(map(len,commands.splitlines())),2048)
  self.assertTrue(commands.startswith('mount -t tmpfs tmpfs /tmp'))
  self.assertEqual(backend.count('/app/bin/avata_ui -c'),1)
  self.assertIn('TOUCH',setup)
 def test_bad_run(self):
  for s in ['../x','ui-x','ui-12345678;echo']:
   with self.assertRaises(ValueError):g.generate(s)
 def test_network(self):
  with self.assertRaises(ValueError):g.generate('ui-12345678','internet')
 def test_path(self):
  with self.assertRaises(ValueError):g.encoded(b'abc','/app/x')
if __name__=='__main__':unittest.main()

class PersistentLogTests(unittest.TestCase):
 def test_logs_are_fresh_run_specific_and_prior_paths_untouched(self):
  _,_,backend=g.generate('ui-12345678')
  self.assertIn('D=/data/kobra-runs/ui-12345678',backend)
  self.assertIn('mkdir "$D" || abort directory_not_fresh',backend)
  self.assertIn('[ ! -L /data/kobra-runs ]',backend)
  self.assertNotIn('/data/main.stdout',backend)
  self.assertNotIn('/data/ui.stdout',backend)
  self.assertIn('>"$D/main.stdout"',backend)
