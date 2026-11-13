"""Offline only: run disposable local Python children, never native firmware."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/bounded_native_supervisor.py'
spec = importlib.util.spec_from_file_location('supervisor', SOURCE)
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)
VALID = {'phase': 'verified_ready', 'request_count': 1, 'final_export_requested': True,
         'launcher_exit_code': 0, 'result': {'client_exit_status': 0, 'transport_exit_status': 0,
         'api_response': {'state': 'ready', 'state_message': ''}, 'physical_completion_proven': False}}


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.stop, self.native, self.evidence = [self.root / x for x in ('stop', 'ready.json', 'supervision.json')]

    def tearDown(self):
        self.tmp.cleanup()

    def run_child(self, body, **extra):
        code = ('import pathlib, time, json, os, signal, subprocess, sys\n'
                f'stop=pathlib.Path({str(self.stop)!r})\n'
                f'native=pathlib.Path({str(self.native)!r})\n'
                f'valid={VALID!r}\n' + body)
        args = dict(stop_request=self.stop, native_report=self.native, evidence=self.evidence,
                    total_seconds=1.2, grace_seconds=.35, term_seconds=.2, kill_seconds=.2,
                    poll_seconds=.01)
        args.update(extra)
        start = time.monotonic()
        result = supervisor.supervise([sys.executable, '-c', code], **args)
        self.assertLess(time.monotonic() - start, args['total_seconds'] + .7)
        pgid = result.get('process_group_id')
        if pgid is not None:
            live, zombies = [], []
            for item in Path('/proc').glob('[0-9]*/stat'):
                try:
                    fields = item.read_text().rsplit(')', 1)[1].split()
                    if int(fields[2]) == pgid:
                        (zombies if fields[0] == 'Z' else live).append(int(item.parent.name))
                except FileNotFoundError:
                    pass
            print(f'DUMMY_GROUP_AUDIT pgid={pgid} live={live} zombies={zombies}', flush=True)
            self.assertEqual(live, [], 'A dummy process remained live after bounded cleanup')
        return result

    def test_graceful_group_and_ready(self):
        result = self.run_child("child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(.12)'])\n"
                                "while not stop.exists(): time.sleep(.01)\n"
                                "child.wait()\nnative.write_text(json.dumps(valid))\n")
        self.assertTrue(result['success'], result)
        self.assertEqual(result['forced_signals'], [])
        self.assertTrue(result['process_group_cleanup_confirmed'])
        self.assertTrue(json.loads(self.evidence.read_text())['success'])

    def test_missing_report_fails(self):
        result = self.run_child('pass\n')
        self.assertFalse(result['success'])
        self.assertFalse(result['native_report_valid'])

    def test_term_forces_failure_even_with_valid_report(self):
        result = self.run_child("native.write_text(json.dumps(valid))\nwhile True: time.sleep(.01)\n")
        self.assertFalse(result['success'])
        self.assertEqual(result['forced_signals'], ['SIGTERM'])
        self.assertTrue(result['process_group_cleanup_confirmed'])

    def test_kill_ignoring_child(self):
        result = self.run_child("signal.signal(signal.SIGTERM, signal.SIG_IGN)\nwhile True: time.sleep(.01)\n")
        self.assertFalse(result['success'])
        self.assertEqual(result['forced_signals'], ['SIGTERM', 'SIGKILL'])
        self.assertTrue(result['process_group_cleanup_confirmed'])

    def test_exited_leader_does_not_hide_live_grandchild(self):
        # Dummy grandchild dies on TERM. Linux may retain an orphan zombie, in
        # which case absence cannot be proven and success must still be false.
        result = self.run_child("subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\n"
                                "native.write_text(json.dumps(valid))\n")
        self.assertFalse(result['success'])
        self.assertIn('SIGTERM', result['forced_signals'])
        self.assertEqual(result['child_exit_code'], 0)
        # No live group member is allowed after the supervisor finishes.
        pgid = result['process_group_id']
        for p in Path('/proc').glob('[0-9]*/stat'):
            try:
                fields = p.read_text().rsplit(')', 1)[1].split()
                if int(fields[2]) == pgid:
                    self.assertEqual(fields[0], 'Z')
            except FileNotFoundError:
                pass

    def test_group_term_reaches_grandchild_while_parent_reaps(self):
        marker = self.root / 'grandchild-term'
        child_code = ("import signal,time,pathlib,sys; "
                      f"signal.signal(signal.SIGTERM,lambda *a:(pathlib.Path({str(marker)!r}).write_text('TERM'),sys.exit(0))); "
                      "time.sleep(30)")
        result = self.run_child(f"child=subprocess.Popen([sys.executable,'-c',{child_code!r}])\n"
                                "signal.signal(signal.SIGTERM,lambda *a:None)\n"
                                "child.wait()\n")
        self.assertFalse(result['success'])
        self.assertEqual(result['forced_signals'], ['SIGTERM'])
        self.assertTrue(result['process_group_cleanup_confirmed'])
        self.assertEqual(marker.read_text(), 'TERM')

    def test_group_status_error_still_signals(self):
        with patch.object(supervisor, 'group_absent', side_effect=PermissionError('injected group status')):
            result = self.run_child('while True: time.sleep(.01)\n')
        self.assertFalse(result['success'])
        self.assertEqual(result['forced_signals'], ['SIGTERM', 'SIGKILL'])
        # The direct child must still be reaped although group absence is unknown.
        self.assertIsNotNone(result['child_exit_code'])

    def test_stop_write_exception_still_terminates(self):
        original = Path.open
        def bad_stop(path, *args, **kw):
            if path == self.stop and args and args[0] == 'x':
                raise PermissionError('injected stop failure')
            return original(path, *args, **kw)
        with patch.object(Path, 'open', bad_stop):
            result = self.run_child('while True: time.sleep(.01)\n')
        self.assertFalse(result['success'])
        self.assertIn('SIGTERM', result['forced_signals'])
        self.assertTrue(any('injected stop failure' in x for x in result['errors']))

    def test_virtual_time_threshold_requests_graceful_stop(self):
        clock = self.root / 'virtual-time.json'
        result = self.run_child(f"pathlib.Path({str(clock)!r}).write_text(json.dumps({{'virtual_time_ns': 123}}))\n"
                                "while not stop.exists(): time.sleep(.01)\n"
                                "native.write_text(json.dumps(valid))\n",
                                virtual_time_file=clock, max_virtual_time_ns=100)
        self.assertTrue(result['success'], result)
        self.assertTrue(any(x['stage'] == 'virtual_time_threshold_observed' for x in result['stages']))

    def test_nonzero_exit_with_valid_report_fails(self):
        result = self.run_child('native.write_text(json.dumps(valid))\nsys.exit(7)\n')
        self.assertFalse(result['success'])
        self.assertEqual(result['child_exit_code'], 7)

    def test_invalid_virtual_time_fails_closed(self):
        clock = self.root / 'virtual-time.json'
        result = self.run_child(f"pathlib.Path({str(clock)!r}).write_text(json.dumps({{'virtual_time_ns': True}}))\n"
                                "while not stop.exists(): time.sleep(.01)\n"
                                "native.write_text(json.dumps(valid))\n",
                                virtual_time_file=clock, max_virtual_time_ns=100)
        self.assertFalse(result['success'])
        self.assertEqual(result['forced_signals'], [])
        self.assertTrue(any('Invalid virtual-time' in x for x in result['errors']))

    def test_evidence_save_error_cannot_pass(self):
        with patch.object(supervisor, 'atomic_save', side_effect=OSError('injected save failure')):
            result = self.run_child('while not stop.exists(): time.sleep(.01)\nnative.write_text(json.dumps(valid))\n')
        self.assertFalse(result['success'])
        self.assertFalse(json.loads(self.evidence.read_text())['success'])
        self.assertTrue(result['process_group_cleanup_confirmed'])

    def test_stale_report_prevents_launch(self):
        self.native.write_text(json.dumps(VALID))
        with patch.object(subprocess, 'Popen') as launch:
            result = self.run_child('raise RuntimeError()\n')
        launch.assert_not_called()
        self.assertFalse(result['success'])

    def test_invalid_budgets_prevent_launch(self):
        for total in (0., float('nan'), float('inf'), .5):
            with self.subTest(total=total), patch.object(subprocess, 'Popen') as launch:
                result = supervisor.supervise(['unused'], stop_request=self.stop, native_report=self.native,
                    evidence=self.evidence, total_seconds=total, grace_seconds=.3, term_seconds=.2, kill_seconds=.2)
                self.assertFalse(result['success'])
                launch.assert_not_called()

    def test_report_schema_rejections(self):
        invalid = [[], {}, dict(VALID, launcher_exit_code=False), dict(VALID, request_count=True),
                   dict(VALID, phase='probe_queued'), dict(VALID, final_export_requested=False),
                   dict(VALID, error=''), dict(VALID, result={'api_response': {'state': 'ready'}})]
        for value in invalid:
            self.native.write_text(json.dumps(value))
            with self.subTest(value=value), self.assertRaises(ValueError):
                supervisor.read_ready_report(self.native)
        self.native.write_text('{')
        with self.assertRaises(ValueError):
            supervisor.read_ready_report(self.native)

    def test_report_symlink_and_fifo_rejected_without_blocking(self):
        target = self.root / 'target'
        target.write_text(json.dumps(VALID))
        self.native.symlink_to(target)
        with self.assertRaises(OSError):
            supervisor.read_ready_report(self.native)
        self.native.unlink()
        os.mkfifo(self.native)
        with self.assertRaises(ValueError):
            supervisor.read_ready_report(self.native)

    def test_launch_failure_leaves_unsuccessful_evidence(self):
        with patch.object(subprocess, 'Popen', side_effect=OSError('injected launch failure')):
            result = self.run_child('pass\n')
        self.assertFalse(result['success'])
        saved = json.loads(self.evidence.read_text())
        self.assertFalse(saved['success'])
        self.assertTrue(any('injected launch failure' in x for x in saved['errors']))

    def test_unconfirmed_cleanup_cannot_pass(self):
        # Supply absence uncertainty without signalling unrelated processes.
        with patch.object(supervisor, 'group_absent', return_value=False), patch.object(os, 'killpg'):
            result = self.run_child('native.write_text(json.dumps(valid))\n')
        self.assertFalse(result['success'])
        self.assertFalse(result['process_group_cleanup_confirmed'])


if __name__ == '__main__':
    unittest.main()
