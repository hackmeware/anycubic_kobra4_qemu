import shlex
import unittest
from pathlib import Path
from generate_guest_commands import generate,MAX_LINE
class Tests(unittest.TestCase):
 def test_bounds_and_reconstruction(self):
  hook=Path(__file__).with_name('udhcpc-hook.sh').read_text()
  commands=generate(hook); lines=commands.splitlines()
  self.assertTrue(all(len(line.encode())<=MAX_LINE for line in lines))
  payload=[]
  for line in lines:
   if line.startswith("printf '%s\\n' ") and line.endswith(" >> /tmp/k4-usb-net/hook.sh"):
    words=shlex.split(line)
    self.assertEqual(words[0:2],['printf','%s\\n'])
    self.assertEqual(words[3:],['>>','/tmp/k4-usb-net/hook.sh'])
    payload.append(words[2])
  self.assertEqual('\n'.join(payload)+'\n',hook)
 def test_tmp_before_write(self):
  lines=generate('echo hello\n').splitlines()
  mount=next(i for i,l in enumerate(lines) if 'mount -t tmpfs' in l)
  write=next(i for i,l in enumerate(lines) if '> /tmp/k4-usb-net/hook.sh' in l)
  self.assertLess(mount,write)
  self.assertIn('size=16m,mode=1777',lines[mount])
 def test_mode_serialization(self):
  self.assertIn("internet > /tmp/k4-usb-net/mode",generate('echo hi',mode='internet'))
  with self.assertRaises(ValueError):generate('echo hi',mode='off')
 def test_oversize_rejected(self):
  with self.assertRaises(ValueError):generate('x'*MAX_LINE)
if __name__=='__main__':unittest.main()
