import json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
import instance_disk as d
import persistence_hooks as h
import start_diagnostic as s

class IntegrationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.src=self.root/'source.raw';self.src.write_bytes(b'A'*4096);self.profile={'kernel':'a'*64}
 def lease(self):return d.open_instance(self.root/'instance',self.src,self.profile)
 def wait_file(self,p):
  limit=time.monotonic()+8
  while not p.exists() and time.monotonic()<limit:time.sleep(.02)
  self.assertTrue(p.exists(),str(p))
 def test_finalization_refuses_live_inherited_child(self):
  l=self.lease();cap=l.begin('run')
  child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'],pass_fds=(l.fd,))
  try:
   with self.assertRaises(d.InstanceBusy):h.finish_exclusive(l,cap)
   self.assertEqual(d.read_state(l.root)['phase'],'active')
  finally:child.terminate();child.wait()
 def test_finalization_requires_all_writers_gone(self):
  l=self.lease();cap=l.begin('run');l.disk.write_bytes(b'B'*4096)
  state=h.finish_exclusive(l,cap)
  self.assertEqual(state['phase'],'quiescent');self.assertFalse(state['guest_sync_confirmed'])
  self.assertEqual(self.src.read_bytes(),b'A'*4096)
  with self.lease() as again:self.assertTrue(again.recovery_backup)
 def test_profile_tree_binding_and_symlink(self):
  p=self.root/'tree';p.mkdir();(p/'a').write_text('a');first=h.bound_tree(p)
  (p/'a').write_text('b');self.assertNotEqual(first,h.bound_tree(p))
  (p/'link').symlink_to(p/'a')
  with self.assertRaises(d.InstanceError):h.bound_tree(p)
 def test_explicit_ui_tools_bound(self):
  ui=self.root/'chosen-ui';ui.mkdir();(ui/'helper.py').write_text('chosen helper')
  profile=h.profile_binding({'kernel':'a'*64},'three-mcu-scalar',ui,ui,self.src,self.src,ui)
  self.assertEqual(profile['ui-tools'],h.bound_tree(ui))
 def test_ephemeral_has_no_capability(self):
  self.assertEqual(h.pass_fds({}),());self.assertEqual(h.wrapper_transform(None),'')
 def chain(self,kill_parent):
  # Real production top-level -> unshare -> PID1 -> observer -> run-link stub
  # -> wrapper exec -> synthetic disk writer. No emulator/firmware executed.
  out=self.root/'out';out.mkdir();(out/'home').mkdir();(out/'tmp').mkdir();(out/'logs').mkdir()
  writer=self.root/'writer.py'
  writer.write_text("import os,sys,time;from pathlib import Path;p=Path(sys.argv[1]);fd=int(sys.argv[2]);os.fstat(fd);(p/'ready').write_text('ready');deadline=time.monotonic()+4\nwhile not (p/'release').exists() and time.monotonic()<deadline:time.sleep(.02)\n(p/'instance/disk.raw').write_bytes(b'B'*4096)\n")
  driver=self.root/'driver.py'
  driver.write_text('''import json,sys,subprocess
from pathlib import Path
import instance_disk as d, persistence_hooks as h, start_diagnostic as s
p=Path(sys.argv[1]);out=p/'out'
l=d.open_instance(p/'instance',p/'source.raw',{'kernel':'a'*64});cap=l.begin('chain')
observer=out/'observer.py';s.write_process_observer(observer,cap)
wrapper=out/'wrapper.py'
wrapper.write_text('import os,sys\\ncmd='+repr([sys.executable,str(p/'writer.py'),str(p),str(l.fd)])+'\\nos.execv(cmd[0],cmd)\\n')
runlink=out/'runlink.py';runlink.write_text('import subprocess,sys\\np=subprocess.Popen([sys.executable,'+repr(str(wrapper))+'])\\nraise SystemExit(p.wait())\\n')
plan={'persistence':cap,'argv':[sys.executable,'-B',str(observer),str(runlink)],'network':'off','hard_limit_seconds':8,'cooperative_limit_seconds':6,'max_namespace_rss_bytes':1024**3}
(out/'RUN-PLAN.json').write_text(json.dumps(plan))
(out/'logs/console.bin').write_text('RV1106_OFFLINE_USERSPACE_READY')
s.execute_bounded(out,plan,p,{'source.raw':d.digest(p/'source.raw')},l)
''')
  env=dict(os.environ,PYTHONPATH=str(Path(__file__).parent.resolve()),PYTHONDONTWRITEBYTECODE='1')
  proc=subprocess.Popen([sys.executable,'-B',str(driver),str(self.root)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  try:
   self.wait_file(self.root/'ready')
   if kill_parent:proc.kill();proc.wait()
   with self.assertRaises(d.InstanceBusy):d.open_instance(self.root/'instance',self.src,self.profile,recover=True)
   (self.root/'release').write_text('go')
   if not kill_parent:
    stdout,stderr=proc.communicate(timeout=12);self.assertEqual(proc.returncode,0,stderr.decode())
    result=json.loads((out/'EXIT.json').read_text());self.assertTrue(result['persistence_finalized']);self.assertFalse(result['guest_sync_confirmed'])
   else:
    end=time.monotonic()+12
    while time.monotonic()<end:
     try:
      with d.open_instance(self.root/'instance',self.src,self.profile,recover=True) as resumed:
       self.assertTrue(resumed.recovery_backup);break
     except d.InstanceBusy:time.sleep(.05)
    else:self.fail('descendant lock never released')
   self.assertEqual((self.root/'instance/disk.raw').read_bytes(),b'B'*4096)
   self.assertEqual(self.src.read_bytes(),b'A'*4096)
  finally:
   (self.root/'release').touch()
   if proc.poll() is None:proc.kill();proc.wait()
   if proc.stdout:proc.stdout.close()
   if proc.stderr:proc.stderr.close()
 def test_real_supervisor_chain(self):self.chain(False)
 def test_real_supervisor_chain_parent_death(self):self.chain(True)
 def test_wrapper_transform_exact_private_drive(self):
  with self.lease() as l:
   cap=l.begin('wrapper');original=['qemu','-drive',f'if=sd,index=0,file={l.disk},format=raw,snapshot=on']
   scope={'sys':sys,'cmd':original};exec(h.wrapper_transform(cap),scope)
   self.assertTrue(scope['cmd'][-1].endswith('snapshot=off'))
   self.assertTrue(original[-1].endswith('snapshot=on'))

if __name__=='__main__':unittest.main(verbosity=2)
