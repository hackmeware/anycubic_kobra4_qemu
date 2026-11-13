from pathlib import Path
import sys,unittest,socket,json,ast
from unittest.mock import patch
T=Path(__file__).resolve().parent;D=T/'sensor_run_check/native-fast4-c22-stop-event/supervision';sys.path.insert(0,str(D));import pid_namespace_supervisor as m
class Checks(unittest.TestCase):
 def owner(self):
  o=m.NamespaceSupervisor(T/'not-created.json');o.last_sample=100.;o.sequence=1;o.initfd=123;o.alive=lambda fd:True;return o
 def test_gap_tolerance_and_expiry(self):
  o=self.owner()
  with patch.object(m.time,'monotonic',return_value=109.9):self.assertEqual(o.rss(),0)
  with patch.object(m.time,'monotonic',return_value=110.1):
   with self.assertRaisesRegex(m.OwnershipError,'last_sample_age_s.*last_sequence.*peak_rss_bytes.*pid1_alive.*timeout_s'):o.rss()
 def test_dead_pid_still_rejected(self):
  o=self.owner();o.alive=lambda fd:False
  with patch.object(m.time,'monotonic',return_value=100.1):
   with self.assertRaisesRegex(m.OwnershipError,'monitor died'):o.rss()
 def test_sample_order_and_rss_guards(self):
  for updates,pattern in [({'sequence':3},'out of order'),({'generated':89.0},'out of order'),({'rss':m.RSS_LIMIT,'peak':m.RSS_LIMIT,'reason':'rss'},'guard stopped: rss'),({'reason':'wall'},'guard stopped: wall')]:
   o=self.owner();a,b=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET);o.control=a
   packet=dict(type='sample',sequence=2,generated=100.,rss=0,peak=0,code=None,reason=None);packet.update(updates);b.send(json.dumps(packet).encode())
   try:
    with patch.object(m.time,'monotonic',return_value=100.1):
     with self.assertRaisesRegex(m.OwnershipError,pattern):o.rss()
   finally:a.close();b.close()
 def test_cleanup_and_launch_code_unchanged(self):
  prior=T.parent/'c22_fullrun_startup300_r8_20261111/sensor_run_check/native-fast4-c22-stop-event/supervision/pid_namespace_supervisor.py'
  trees=[ast.parse(p.read_text()) for p in (prior,D/'pid_namespace_supervisor.py')]
  for name in ['cleanup','launch','__exit__','init_main']:
   nodes=[next(n for n in ast.walk(t) if isinstance(n,ast.FunctionDef) and n.name==name) for t in trees]
   self.assertEqual(ast.dump(nodes[0]),ast.dump(nodes[1]))
  self.assertEqual(m.RSS_LIMIT,4*1024**3);self.assertEqual(m.INTERVAL,.025);self.assertEqual(m.HEARTBEAT_TIMEOUT,10.)
if __name__=='__main__':unittest.main()
