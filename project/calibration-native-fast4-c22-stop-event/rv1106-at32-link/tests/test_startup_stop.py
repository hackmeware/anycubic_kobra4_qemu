"""Startup control tests: mocks only, no emulator or firmware execution."""
import contextlib
import io
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
import run_link
import renode_peer


class Clock:
    def __init__(self):self.now=0.;self.on_sleep=lambda:None
    def monotonic(self):return self.now
    def sleep(self,seconds):self.now+=seconds;self.on_sleep()


class Process:
    def __init__(self, stubborn=False):
        self.stdin=mock.Mock();self.returncode=None;self.terminated=False
        self.killed=False;self.reaped=False;self.stubborn=stubborn;self.wait_timeouts=[]
    def poll(self):return self.returncode
    def terminate(self):
        self.terminated=True
        if not self.stubborn:self.returncode=-15
    def kill(self):self.killed=True;self.returncode=-9
    def wait(self,timeout=None):
        self.wait_timeouts.append(timeout)
        if self.returncode is None:raise subprocess.TimeoutExpired('dummy',timeout)
        self.reaped=True
        return self.returncode


class StartupWaitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name);self.stop=self.root/'stop'
        self.clock=Clock()
        self.patch=mock.patch.multiple(run_link.time,monotonic=self.clock.monotonic,sleep=self.clock.sleep)
        self.patch.start();self.addCleanup(self.patch.stop)
        self.wait=run_link.StartupWait(1,self.stop)

    def test_success_preserves_default_budget(self):
        self.wait.wait('ready',lambda:True)
        self.wait.settle()
        self.assertGreaterEqual(self.clock.now,.2)
        self.assertEqual(self.wait.deadline,1)

    def test_stop_wins_over_already_ready(self):
        self.stop.touch()
        with self.assertRaisesRegex(run_link.StartupAborted,'stop requested'):
            self.wait.wait('ready',lambda:True)

    def test_stop_created_by_readiness_predicate(self):
        def ready():self.stop.touch();return True
        with self.assertRaisesRegex(run_link.StartupAborted,'stop requested'):
            self.wait.wait('ready',ready)

    def test_ready_at_and_after_deadline_rejected(self):
        for ready_time in (1,2):
            with self.subTest(ready_time=ready_time):
                self.clock.now=0
                def ready():self.clock.now=ready_time;return True
                with self.assertRaisesRegex(run_link.StartupAborted,'deadline expired'):
                    self.wait.wait('ready',ready)

    def test_same_absolute_deadline_across_phases(self):
        self.wait.wait('PTY',lambda:self.clock.now>=.8)
        with self.assertRaisesRegex(run_link.StartupAborted,'deadline expired.*initialization'):
            self.wait.wait('initialization',lambda:self.clock.now>=1.1)
        self.assertLessEqual(self.clock.now,1.05)

    def test_cancellation_polled_within_50ms(self):
        self.clock.on_sleep=self.stop.touch
        with self.assertRaises(run_link.StartupAborted):self.wait.wait('PTY',lambda:False)
        self.assertLessEqual(self.clock.now,.05)
        self.assertTrue(self.stop.exists())

    def test_dead_process_and_model_error_win_over_ready(self):
        log=self.root/'renode.log';log.write_bytes(b'')
        proc=Process();self.wait.peers.append((proc,log))
        proc.returncode=0
        with self.assertRaisesRegex(run_link.StartupAborted,'process exited'):
            self.wait.wait('PTY',lambda:True)
        proc.returncode=None;log.write_bytes(b'There was an error')
        with self.assertRaisesRegex(run_link.StartupAborted,'model error'):
            self.wait.wait('initialization',lambda:True)


class MainStartupTests(unittest.TestCase):
    def run_main(self,mode,stubborn=False,final=False,fault=None):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);image=root/'dummy.bin';image.write_bytes(b'\0'*8)
            stop=root/'stop';logs=root/'logs';clock=Clock();processes=[];qemu=[]
            argv=['run_link.py','--mcu-image',str(image),'--log-dir',str(logs),
                  '--stop-request',str(stop),'--timeout','.05','--model',str(root)]
            if final:
                commands=root/'final.commands';commands.write_text('diagnostic\n')
                argv+=['--mcu-final-commands',str(commands),'--virtual-baud','576000']
            bridge=mock.Mock(counts=[0,0],error=None,timing_dropped=0,events=[])
            gate=mock.Mock(error=None)
            if fault=='clock-close':
                argv+=['--shared-mcus','--motor-image',str(image),'--nozzle-image',str(image),'--clock-coupled']
                gate.close.side_effect=OSError('clock close failed')
            elif fault in ('diagnostic','motor-bridge.json','motor-chunk-timing.json'):
                argv+=['--motor-image',str(image)]
            def start_peer(*args,**kwargs):
                proc=Process();processes.append(proc);args[6].append(proc)
                return root/'mock-motor-pty'
            def spawn(args,**kwargs):
                proc=Process(stubborn);processes.append(proc)
                if fault=='diagnostic':proc.stdin.write.side_effect=OSError('diagnostic pipe failed')
                if '--disable-gui' not in args:qemu.append(args);return proc
                resc=pathlib.Path(args[-1]);pty=pathlib.Path(re.search(r'CreateUartPtyTerminal "rv_link" "([^"]+)"',resc.read_text())[1])
                if mode not in ('pty-stop','deadline'):pty.touch()
                if mode in ('success','settle-stop','prelaunch-stop','prelaunch-deadline','error','exit'):
                    kwargs['stdout'].write(b'Starting emulation\n');kwargs['stdout'].flush()
                if mode=='error':kwargs['stdout'].write(b'There was an error\n');kwargs['stdout'].flush()
                if mode=='exit':proc.returncode=1
                if mode in ('pty-stop','init-stop','settle-stop'):clock.on_sleep=stop.touch
                if mode=='deadline':clock.on_sleep=lambda:setattr(clock,'now',180.)
                return proc
            original_write=pathlib.Path.write_text
            def write_text(path,*args,**kwargs):
                if fault==path.name:raise OSError('ENOSPC simulated')
                result=original_write(path,*args,**kwargs)
                if path.name=='qemu-execution.json':
                    if mode=='prelaunch-stop':stop.touch()
                    if mode=='prelaunch-deadline':clock.now=180.
                return result
            stdout=io.StringIO();stderr=io.StringIO()
            with mock.patch.object(sys,'argv',argv),mock.patch.object(run_link.subprocess,'Popen',side_effect=spawn), \
                 mock.patch.multiple(run_link.time,monotonic=clock.monotonic,sleep=clock.sleep), \
                 mock.patch.object(pathlib.Path,'write_text',write_text), \
                 mock.patch('renode_peer.start_peer',side_effect=start_peer), \
                 mock.patch('pty_bridge.PtyBridge',return_value=bridge), \
                 mock.patch('shared_mcu.prepare',side_effect=lambda a,tmp,*unused:(tmp/'link.resc',tmp/'nozzle-uart')), \
                 mock.patch('clock_coordinator.ClockCoordinator',return_value=gate), \
                 contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
                if mode=='success':
                    if fault:
                        with self.assertRaisesRegex(RuntimeError,'Cleanup unconfirmed'):run_link.main()
                    else:self.assertEqual(run_link.main(),0)
                else:
                    with self.assertRaises(run_link.StartupAborted) as caught:run_link.main()
                    if fault:self.assertIn('ENOSPC',str(caught.exception.__notes__))
            if mode=='success':
                self.assertEqual(len(qemu),1);self.assertFalse((logs/'startup-abort.json').exists())
                if final and fault!='clock-close':self.assertTrue(processes[0].stdin.write.called)
            else:
                self.assertEqual(qemu,[])
                if fault!='startup-abort.json':
                    evidence=json.loads((logs/'startup-abort.json').read_text())
                    self.assertEqual(evidence['status'],'aborted');self.assertFalse(evidence['qemu_started'])
                self.assertIn('startup aborted',stderr.getvalue())
                self.assertNotIn('Connected',stdout.getvalue())
                self.assertNotIn('Ready',stdout.getvalue())
                for proc in processes:self.assertFalse(proc.stdin.write.called)
                if mode.endswith('stop'):self.assertTrue(stop.exists())
                if fault!='startup-cleanup.json':
                    cleanup=json.loads((logs/'startup-cleanup.json').read_text())
                    self.assertEqual(cleanup['status'],'reaped')
                    self.assertEqual(len(cleanup['processes']),len(processes))
                    for record,proc in zip(cleanup['processes'],processes):
                        self.assertEqual(record['term_attempted'],proc.terminated)
                        self.assertEqual(record['kill_attempted'],proc.killed)
                        self.assertTrue(record['reaped'])
                        self.assertEqual(record['returncode'],proc.returncode)
            for proc in processes:
                self.assertIsNotNone(proc.poll());self.assertTrue(proc.reaped)
                if stubborn:self.assertTrue(proc.killed)
                self.assertEqual(proc.wait_timeouts[0],5 if mode=='success' else .5)
            if fault in ('motor-bridge.json','motor-chunk-timing.json'):bridge.close.assert_called_once()
            return clock.now

    def test_clock_close_error_still_terminates_children(self):
        self.run_main('success',final=True,fault='clock-close')
    def test_diagnostic_error_still_terminates_children(self):
        self.run_main('success',final=True,fault='diagnostic')
    def test_startup_motor_report_error_preserves_abort_and_reaps(self):
        for filename in ('motor-bridge.json','motor-chunk-timing.json'):
            with self.subTest(filename=filename):self.run_main('prelaunch-stop',final=True,fault=filename)
    def test_abort_report_error_preserves_abort_and_reaps(self):
        self.run_main('init-stop',final=True,fault='startup-abort.json')

    def test_cleanup_evidence_write_error_preserves_abort_and_reaps(self):
        self.run_main('init-stop',final=True,fault='startup-cleanup.json')

    def test_stop_in_both_phases_and_settle(self):
        for mode in ('pty-stop','init-stop','settle-stop'):
            with self.subTest(mode=mode):self.assertLess(self.run_main(mode,final=True),.2)
    def test_deadline_no_qemu(self):self.run_main('deadline',final=True)
    def test_error_and_exit_no_qemu(self):
        for mode in ('error','exit'):
            with self.subTest(mode=mode):self.run_main(mode,final=True)
    def test_final_launch_boundary_rechecked(self):
        for mode in ('prelaunch-stop','prelaunch-deadline'):
            with self.subTest(mode=mode):self.run_main(mode,final=True)
    def test_unresponsive_process_killed_and_reaped(self):self.run_main('init-stop',stubborn=True,final=True)
    def test_default_success_and_normal_diagnostics(self):self.run_main('success',final=True)


class CleanupTests(unittest.TestCase):
    def test_post_kill_timeout_is_bounded_and_other_children_reaped(self):
        stuck=Process(stubborn=True)
        stuck.wait=mock.Mock(side_effect=subprocess.TimeoutExpired('dummy',.5))
        healthy=Process()
        failures=run_link.CleanupFailures()
        records=run_link.terminate_children([stuck,healthy],False,failures)
        self.assertTrue(records[0]['kill_attempted']);self.assertFalse(records[0]['reaped'])
        self.assertTrue(records[0]['errors']);self.assertIsNone(records[0]['returncode'])
        self.assertTrue(records[1]['reaped'])
        self.assertTrue(stuck.terminated);self.assertTrue(stuck.killed)
        self.assertEqual(stuck.wait.call_args_list,[mock.call(timeout=.5),mock.call(timeout=.5)])
        self.assertTrue(healthy.terminated);self.assertTrue(healthy.reaped)
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaisesRegex(RuntimeError,'Cleanup unconfirmed.*reap child 0'):
            failures.finish(None)

    def test_termination_error_does_not_skip_other_children(self):
        failed=Process();failed.terminate=mock.Mock(side_effect=OSError('signal failed'))
        healthy=Process();failures=run_link.CleanupFailures()
        run_link.terminate_children([failed,healthy],False,failures)
        self.assertTrue(failed.killed);self.assertTrue(failed.reaped)
        self.assertTrue(healthy.terminated);self.assertTrue(healthy.reaped)
        original=run_link.StartupAborted('original abort')
        with contextlib.redirect_stderr(io.StringIO()):failures.finish(original)
        self.assertIn('signal failed',str(original.__notes__))


class IndependentPeerTests(unittest.TestCase):
    def test_peer_uses_shared_budget_and_cancellation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);image=root/'dummy.bin';image.write_bytes(b'\0'*8)
            stop=root/'stop';clock=Clock();clock.now=.95
            wait=run_link.StartupWait(1,stop);processes=[]
            with mock.patch.object(renode_peer.subprocess,'Popen',return_value=Process()), \
                 mock.patch.multiple(run_link.time,monotonic=clock.monotonic,sleep=clock.sleep):
                with self.assertRaisesRegex(run_link.StartupAborted,'deadline expired'):
                    renode_peer.start_peer('unused',root,image,0,root/'peer',root,processes,startup_wait=wait)
            self.assertEqual(len(processes),1);self.assertEqual(wait.deadline,1)
            self.assertLessEqual(clock.now,1.05)

if __name__=='__main__':unittest.main()
