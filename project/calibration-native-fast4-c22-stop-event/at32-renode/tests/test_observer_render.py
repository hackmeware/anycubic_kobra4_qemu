#!/usr/bin/env python3
import importlib.util,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('viewer',Path(__file__).resolve().parents[1]/'tools/render_virtual_print.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
class Tests(unittest.TestCase):
 def render(self,text):
  with tempfile.TemporaryDirectory() as d:
   src=Path(d)/'trace.csv';dst=Path(d)/'trace.html';src.write_text(text);n=v.render(src,dst);return n,dst.read_text()
 def test_empty_channels(self):
  n,p=self.render('# source: <script>bad</script>\ntime_s,a_mm,hotend_c\n0,,25\n1,,26\n');self.assertEqual(n,2);self.assertIn('&lt;script&gt;',p);self.assertIn('"a_mm": null',p)
 def test_injection(self):
  _,p=self.render('time_s,hotend_fault\n0,</script>\n');self.assertIn('\\u003c/script>',p)
 def test_invalid(self):
  for s in ['time_s\nNaN\n','time_s\n0\n0\n','time_s\n','time_s\n0,1\n']:
   with self.assertRaises(ValueError):self.render(s)
if __name__=='__main__':unittest.main()
