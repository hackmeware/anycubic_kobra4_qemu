import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import start_diagnostic as s

class SupervisorTests(unittest.TestCase):
    def test_default_profile_has_no_coupling(self):
        p=s.profile_settings('two-mcu-independent',Path('/inputs'),Path('/out'))
        self.assertEqual(p['argv'],[]);self.assertEqual(p['startup_seconds'],60);self.assertFalse(p['motor'])
    def test_three_mcu_explicit_scalar_profile(self):
        p=s.profile_settings('three-mcu-scalar',Path('/inputs'),Path('/out'))
        self.assertTrue(p['motor']);self.assertEqual(p['startup_seconds'],300)
        self.assertIn('--shared-mcus',p['argv']);self.assertIn('--clock-lockstep',p['argv'])
        self.assertEqual(p['argv'][p['argv'].index('--qemu-icount-shift')+1],'0')
        self.assertEqual(p['quantum_seconds'],0.000001)
    def test_unknown_profile_refused(self):
        with self.assertRaises(ValueError):s.profile_settings('invented',Path('/inputs'),Path('/out'))
    def test_readiness_marker_present_and_absent(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'console.bin';self.assertFalse(s.guest_userspace_ready(p))
            p.write_bytes(b'not ready');self.assertFalse(s.guest_userspace_ready(p))
            p.write_bytes(b'x'*65530+b'RV1106_OFFLINE_USERSPACE_READY');self.assertTrue(s.guest_userspace_ready(p))
    def test_clean_no_boot_has_distinct_exit(self):
        r={'subprocess_returncode':0,'input_unchanged':True,'outer_stop_reason':None,
           'supervisor_evidence_present':True,'guest_userspace_ready':False}
        self.assertEqual(s.diagnostic_exit_code(r),3)
        r['guest_userspace_ready']=True;self.assertEqual(s.diagnostic_exit_code(r),0)
        r['subprocess_returncode']=1;self.assertEqual(s.diagnostic_exit_code(r),1)
    def test_observer_records_owned_exit_and_signal(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);observer=root/'observer.py';s.write_process_observer(observer)
            script=root/'owned_children.py'
            script.write_text("import subprocess,sys\nsubprocess.run([sys.executable,'-c','raise SystemExit(7)'])\nsubprocess.run([sys.executable,'-c','import os,signal;os.kill(os.getpid(),signal.SIGTERM)'])\n")
            r=s.subprocess.run([s.sys.executable,'-B',str(observer),str(script)],capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,0,r.stderr)
            rows=[json.loads(line) for line in (root/'PROCESS-EXITS.jsonl').read_text().splitlines()]
            self.assertEqual([row['returncode'] for row in rows],[7,-15])
            self.assertEqual(rows[1]['signal'],15)
    def test_owned_listener_parser_ignores_other_inodes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'42/fd').mkdir(parents=True);(root/'net').mkdir()
            (root/'42/cmdline').write_bytes(b'/runtime/qemu-baseline\0')
            (root/'42/fd/3').symlink_to('socket:[12345]')
            (root/'net/tcp').write_text('header\n0: 0100007F:49DE 00000000:0000 0A 0:0 0:0 0 1000 0 12345\n1: 00000000:1234 00000000:0000 0A 0:0 0:0 0 1000 0 99999\n')
            (root/'net/tcp6').write_text('header\n0: 00000000000000000000000001000000:49DF 00000000000000000000000000000000:0000 0A 0:0 0:0 0 1000 0 12345\n')
            rows=s.owned_tcp_listeners(root)
            self.assertEqual([(r['address'],r['port']) for r in rows],[('127.0.0.1',18910),('::1',18911)])
            self.assertTrue(all(r['pid']==42 for r in rows))
    def test_network_failure_distinct_from_boot_success(self):
        r={'subprocess_returncode':0,'input_unchanged':True,'outer_stop_reason':None,
           'supervisor_evidence_present':True,'guest_userspace_ready':True,'network_configuration_ready':False}
        self.assertEqual(s.diagnostic_exit_code(r),4)
        r['network_configuration_ready']=True;r['loopback_forwards_verified']=False
        self.assertEqual(s.diagnostic_exit_code(r),4)
        r['loopback_forwards_verified']=True;self.assertEqual(s.diagnostic_exit_code(r),0)
    def test_namespace_required(self):
        with tempfile.TemporaryDirectory() as d,patch.object(s.os,'getpid',return_value=55):
            with self.assertRaisesRegex(RuntimeError,'namespace'):s.namespace_supervisor(d)
    def test_no_uncontained_fallback(self):
        with patch.object(s.shutil,'which',return_value=None),patch.object(s.subprocess,'Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError,'unshare'):s.execute_bounded(Path('/unused'),{},Path('/unused'),{})
            spawn.assert_not_called()
    def test_owned_child_normal_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'RUN-PLAN.json').write_text(json.dumps({'argv':['not-executed'],'hard_limit_seconds':2}))
            child=Mock();child.poll.return_value=0;child.returncode=0
            with patch.object(s.os,'getpid',return_value=1),patch.object(s.os,'nice'),patch.object(s.os,'readlink',return_value='private-test'),patch('resource.setrlimit'),patch.object(s.signal,'signal'),patch.object(s.subprocess,'Popen',return_value=child):
                self.assertEqual(s.namespace_supervisor(root),0)
            record=json.loads((root/'SUPERVISOR.json').read_text());self.assertTrue(record['owned_child_exited']);child.terminate.assert_not_called()
    def test_failed_namespace_not_success(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);child=Mock();child.poll.return_value=1;child.returncode=1
            with patch.object(s.shutil,'which',return_value='/usr/bin/unshare'),patch.object(s.subprocess,'Popen',return_value=child):
                self.assertEqual(s.execute_bounded(root,{'network':'off','hard_limit_seconds':2},root,{}),1)
            record=json.loads((root/'EXIT.json').read_text());self.assertFalse(record['supervisor_evidence_present']);self.assertTrue(record['namespace_wrapper_exited'])

if __name__=='__main__':unittest.main()
