import os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
import instance_disk as d

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.src=self.root/'source.raw';self.src.write_bytes(b'a'*4096);self.inst=self.root/'instance';self.profile={'kernel':'a'*64,'mcu':'b'*64}
 def open(self,**kw):return d.open_instance(self.inst,self.src,self.profile,**kw)
 def test_copy_resume(self):
  with self.open() as l:
   self.assertNotEqual(l.disk.stat().st_ino,self.src.stat().st_ino);l.begin('run');l.disk.write_bytes(b'b'*4096)
   l.finish('run',writer_exited=True,guest_sync_confirmed=True,guest_sync_evidence='synthetic only')
  with self.open() as l:self.assertEqual(l.disk.read_bytes(),b'b'*4096);self.assertIsNone(l.recovery_backup)
  self.assertEqual(self.src.read_bytes(),b'a'*4096)
 def test_busy(self):
  with self.open():
   with self.assertRaises(d.InstanceBusy):self.open()
 def test_crash_recovery(self):
  with self.open() as l:l.begin('crash');l.disk.write_bytes(b'c'*4096)
  with self.assertRaises(d.RecoveryRequired):self.open()
  with self.open(recover=True) as l:self.assertEqual(Path(l.recovery_backup).read_bytes(),b'c'*4096);l.begin('recovered')
 def test_unsynced_exit_backup(self):
  with self.open() as l:l.begin('run');l.finish('run',writer_exited=True)
  with self.open() as l:self.assertEqual(Path(l.recovery_backup).read_bytes(),b'a'*4096)
 def test_external_change(self):
  with self.open():pass
  (self.inst/'disk.raw').write_bytes(b'd'*4096)
  with self.assertRaises(d.RecoveryRequired):self.open()
  with self.open(recover=True) as l:self.assertEqual(Path(l.recovery_backup).read_bytes(),b'd'*4096)
 def test_profile_mismatch(self):
  with self.open():pass
  self.profile['kernel']='c'*64
  with self.assertRaises(d.InstanceError):self.open(recover=True)
 def test_source_mismatch(self):
  with self.open():pass
  self.src.write_bytes(b'z'*4096)
  with self.assertRaises(d.InstanceError):self.open(recover=True)
 def test_symlink_source(self):
  p=self.root/'link';p.symlink_to(self.src)
  with self.assertRaises(d.InstanceError):d.open_instance(self.inst,p,self.profile)
 def test_symlink_root(self):
  self.inst.symlink_to(self.root)
  with self.assertRaises(d.InstanceError):self.open()
 def test_symlink_disk(self):
  with self.open():pass
  (self.inst/'disk.raw').rename(self.inst/'preserved.raw');(self.inst/'disk.raw').symlink_to(self.src)
  with self.assertRaises(d.InstanceError):self.open()
 def test_hardlink_source(self):
  os.link(self.src,self.root/'other')
  with self.assertRaises(d.InstanceError):self.open()
 def test_partial_initialization(self):
  self.inst.mkdir(mode=0o700);(self.inst/'disk.raw').write_bytes(b'keep')
  with self.assertRaises((d.InstanceError,FileNotFoundError)):self.open(recover=True)
  self.assertEqual((self.inst/'disk.raw').read_bytes(),b'keep')
 def test_finalize_guards(self):
  with self.open() as l:
   l.begin('run')
   with self.assertRaises(d.InstanceError):l.finish('run',writer_exited=False)
   with self.assertRaises(d.InstanceError):l.finish('run',writer_exited=True,guest_sync_confirmed=True)
   with self.assertRaises(d.InstanceError):l.finish('wrong',writer_exited=True)
 def test_owned_drive_only(self):
  with self.open() as l:
   s=l.begin('run');a=['qemu','-drive',f'if=sd,index=0,file={l.disk},format=raw,snapshot=on']
   def change(a):return d.persistent_qemu_argv(a,self.inst,l.fd,s['instance_id'],'run')
   self.assertTrue(change(a)[-1].endswith('snapshot=off'));self.assertTrue(a[-1].endswith('snapshot=on'))
   for bad in [a+a,a[:-1]+[a[-1].replace(str(l.disk),str(self.src))],a[:-1]+[a[-1]+',cache=unsafe']]:
    with self.assertRaises(d.InstanceError):change(bad)
 def test_wrong_descriptor(self):
  with self.open() as l:
   s=l.begin('run');fd=os.open(self.src,os.O_RDONLY)
   try:
    with self.assertRaises(d.InstanceError):d.inherited_lease(self.inst,fd,s['instance_id'],'run')
   finally:os.close(fd)
 def test_permissions_history(self):
  with self.open() as l:
   l.begin('run');l.finish('run',writer_exited=True)
   self.assertGreaterEqual(len(list((self.inst/'history').glob('*.json'))),3)
   for p in [self.inst,self.inst/'state.json',l.disk,self.inst/'writer.lock']:self.assertEqual(p.stat().st_mode&0o077,0)
 def test_parent_death(self):
  # Abrupt parent exit, real inherited descriptor in a separate live child.
  child="import os,time,sys;from pathlib import Path;p=Path(sys.argv[1]);(p/'ready').write_text('ready');deadline=time.monotonic()+10\nwhile not (p/'release').exists() and time.monotonic()<deadline:time.sleep(.02)"
  parent="import instance_disk as d,sys,subprocess,os;from pathlib import Path;p=Path(sys.argv[1]);l=d.open_instance(p/'instance',p/'source.raw',{'kernel':'a'*64,'mcu':'b'*64});l.begin('parent');subprocess.Popen([sys.executable,'-c',sys.argv[2],str(p)],pass_fds=(l.fd,),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);os._exit(0)"
  env=dict(os.environ,PYTHONPATH=str(Path(d.__file__).parent))
  subprocess.run([sys.executable,'-B','-c',parent,str(self.root),child],env=env,check=True,timeout=5)
  end=time.monotonic()+5
  while not (self.root/'ready').exists() and time.monotonic()<end:time.sleep(.02)
  self.assertTrue((self.root/'ready').exists())
  try:
   with self.assertRaises(d.InstanceBusy):self.open(recover=True)
  finally:(self.root/'release').write_text('exit')
  end=time.monotonic()+5
  while time.monotonic()<end:
   try:
    with self.open(recover=True):break
   except d.InstanceBusy:time.sleep(.02)
  else:self.fail('lock not released after child exit')

if __name__=='__main__':unittest.main(verbosity=2)
