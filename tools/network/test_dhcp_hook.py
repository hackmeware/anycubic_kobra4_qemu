import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE=Path(__file__).with_name('udhcpc-hook.sh').read_text()
class HookTests(unittest.TestCase):
 def run_hook(self, updates=None, symlink=False, mode='isolated'):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); work=root/'work';work.mkdir();(work/'mode').write_text(mode+'\n');binpath=root/'bin';binpath.mkdir()
   etc=root/'etc';etc.mkdir();tmp=root/'tmp';tmp.mkdir();resolver=etc/'resolv.conf'
   if symlink:resolver.symlink_to('../tmp/resolv.conf')
   else:resolver.touch()
   log=root/'commands'
   for name in ['ifconfig','route']:
    f=binpath/name;f.write_text('#!/bin/sh\nprintf "%s\\n" "'+name+' $*" >> "$MOCK_LOG"\n');f.chmod(0o700)
   f=binpath/'mount';f.write_text('#!/bin/sh\nprintf "%s\\n" "mount $*" >> "$MOCK_LOG"\n[ "$1" = -o ] && [ "$2" = bind ] || exit 1\ncp "$3" "$4"\n');f.chmod(0o700)
   hook=root/'hook.sh';hook.write_text(SOURCE.replace('/tmp/k4-usb-net',str(work)).replace('/etc/resolv.conf',str(resolver)).replace('/tmp/resolv.conf',str(tmp/'resolv.conf')).replace('..'+str(tmp/'resolv.conf'),'../tmp/resolv.conf'))
   env=dict(os.environ,PATH=str(binpath)+':/usr/bin:/bin',MOCK_LOG=str(log),interface='eth0',ip='10.0.2.15',subnet='255.255.255.0',router='10.0.2.2',dns='10.0.2.3')
   env.update(updates or {})
   result=subprocess.run(['/bin/sh',str(hook),'bound'],env=env,text=True,capture_output=True)
   return result, resolver.read_text(), (log.read_text() if log.exists() else ''), (work/'lease-ready').exists()
 def test_valid(self):
  r,resolver,log,ready=self.run_hook()
  self.assertEqual(r.returncode,0,r.stderr);self.assertTrue(ready)
  self.assertEqual(resolver,'nameserver 10.0.2.3\n')
  self.assertIn('route add default gw 10.0.2.2 dev eth0',log)
  self.assertIn('K4_NET_LEASE_READY',r.stdout)
 def test_dangling_vendor_symlink(self):
  r,resolver,log,ready=self.run_hook(symlink=True)
  self.assertEqual(r.returncode,0,r.stderr);self.assertTrue(ready)
  self.assertEqual(resolver,'nameserver 10.0.2.3\n')
  self.assertNotIn('mount ',log)
 def test_isolated_without_router_dns(self):
  r,_,log,ready=self.run_hook({'router':'','dns':''})
  self.assertEqual(r.returncode,0,r.stderr);self.assertTrue(ready)
  self.assertIn('K4_NET_LOCAL_ONLY_READY',r.stdout)
  self.assertNotIn('route add default',log);self.assertNotIn('mount ',log)
 def test_invalid_provided_dns(self):
  r,_,_,ready=self.run_hook({'dns':'10.0.2.999'})
  self.assertNotEqual(r.returncode,0);self.assertFalse(ready)
 def test_invalid_address(self):
  r,_,_,ready=self.run_hook({'ip':'10.0.2.999'})
  self.assertNotEqual(r.returncode,0);self.assertFalse(ready)
 def test_no_dns(self):
  r,_,_,ready=self.run_hook({'dns':''},mode='internet')
  self.assertNotEqual(r.returncode,0);self.assertFalse(ready)
 def test_no_router(self):
  r,_,_,ready=self.run_hook({'router':''},mode='internet')
  self.assertNotEqual(r.returncode,0);self.assertFalse(ready)
 def test_invalid_interface(self):
  r,_,log,ready=self.run_hook({'interface':'wlan0'})
  self.assertNotEqual(r.returncode,0);self.assertFalse(ready);self.assertEqual(log,'')
if __name__=='__main__':unittest.main()
