import json,struct,tempfile,unittest,zlib
from pathlib import Path
import build_disk,build_system,build_app,prepare_setup
class GuardTests(unittest.TestCase):
 def test_layout_rejected_before_output(self):
  with tempfile.TemporaryDirectory() as t:
   t=Path(t);p=t/'layout';p.write_text('{"partitions":[]}');out=t/'out'
   with self.assertRaisesRegex(ValueError,'layout hash'):build_disk.create(t,t,t,out,p)
   self.assertFalse(out.exists())
 def test_system_rejected_before_output(self):
  with tempfile.TemporaryDirectory() as t:
   t=Path(t);p=t/'system';p.write_bytes(b'bad');out=t/'out'
   with self.assertRaisesRegex(ValueError,'system image hash'):build_system.build(p,out,'/never-run')
   self.assertFalse(out.exists())
 def test_setup_rejected_before_output(self):
  with tempfile.TemporaryDirectory() as t:
   t=Path(t);p=t/'setup';p.write_bytes(b'bad');out=t/'out'
   with self.assertRaisesRegex(ValueError,'setup archive'):prepare_setup.prepare(p,out,'/never-run')
   self.assertFalse(out.exists())
 def test_app_rejects_unrecognized_archive(self):
  with tempfile.TemporaryDirectory() as t:
   t=Path(t);p=t/'app';p.write_bytes(b'bad')
   with self.assertRaisesRegex(ValueError,'archive size'):build_app.build([p],t/'out','/never-run')
 def test_layout_pin(self):
  self.assertEqual(build_disk.sha(Path(__file__).parent/'reference-disk-layout.json'),'021394b8b297d0de21d2db32069b68011c773811cd7988aaed3f55fa19621d43')
if __name__=='__main__':unittest.main()
