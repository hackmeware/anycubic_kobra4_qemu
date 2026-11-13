"""Separate-process tests of the outer subreaper. No emulator or firmware."""
import json
import importlib.util
import os
from unittest.mock import patch
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent

class OuterGuardTests(unittest.TestCase):
    def run_guard(self, code):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            record = Path(directory)/'guard.json'
            start = time.monotonic()
            completed = subprocess.run([sys.executable, str(HERE/'outer_guard.py'),
                '--record', str(record), '--wall-seconds', '3', '--', sys.executable, '-c', code],
                capture_output=True, timeout=5)
            self.assertLess(time.monotonic()-start, 4)
            result = json.loads(record.read_text())
            self.assertTrue(result['all_descendants_absent'], result)
            self.assertTrue(result['whole_groups_absent'], result)
            return completed.returncode, result

    def test_waitpid_race_preserves_comparator_nonzero_status(self):
        spec = importlib.util.spec_from_file_location('outer_guard_test', HERE/'outer_guard.py')
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        process = subprocess.Popen([sys.executable, '-c', 'raise SystemExit(37)'], stdout=subprocess.PIPE)
        process.stdout.read()  # EOF proves exit, but intentionally does not reap.
        process.stdout.close()
        reaped = []
        # Force the poll/exit/waitpid interleaving deterministically with a real
        # exited child whose status is consumed by real waitpid(-1).
        with patch.object(process, 'poll', return_value=None):
            guard.reap_children(process, reaped)
        self.assertEqual(process.returncode, 37)
        self.assertEqual(process.poll(), 37)
        self.assertEqual(reaped[0]['pid'], process.pid)

    def test_overrun_still_attempts_first_cleanup_pass(self):
        spec = importlib.util.spec_from_file_location('outer_overrun', HERE/'outer_guard.py')
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        row = {'pid': 99999999, 'starttime': 10, 'ppid': os.getpid(), 'pgid': 99999999,
               'session': 99999999, 'state': 'S', 'rss_bytes': 1}
        class FakeProcess:
            pid = row['pid']
            def poll(self): return None
        calls = []
        def clock():
            calls.append(1)
            return 0 if len(calls) == 1 else 10
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            with patch.object(guard, 'enable_subreaper'), patch.object(guard, 'reap_children'), \
                 patch.object(guard, 'proc_snapshot', return_value={row['pid']: row}), \
                 patch.object(guard, 'process_info', return_value=row), \
                 patch.object(guard, 'available_memory', return_value=8*1024**3), \
                 patch.object(guard.subprocess, 'Popen', return_value=FakeProcess()), \
                 patch.object(guard.time, 'monotonic', clock), \
                 patch.object(guard.os, 'pidfd_open', return_value=123), \
                 patch.object(guard.os, 'close'), \
                 patch.object(guard.signal, 'pidfd_send_signal') as kill:
                path = Path(directory)/'record.json'
                self.assertEqual(guard.supervise(['dummy'], path, 3), 1)
                self.assertEqual(kill.call_count, 1)
                result = json.loads(path.read_text())
                self.assertEqual(result['signals'][0]['outcome'], 'sent')
                self.assertFalse(result['all_descendants_absent'])

    def test_pidfd_fault_does_not_abort_other_cleanup_or_evidence(self):
        # Real dummy descendants; one pidfd open fails once, then cleanup retries.
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            record = Path(directory)/'record.json'
            comparator = ('import subprocess,sys,time; '
                          'subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"],start_new_session=True); '
                          'time.sleep(30)')
            driver = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('guard',sys.argv[1]); g=importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
original=g.os.pidfd_open
count=[0]
def faulty(pid):
 count[0]+=1
 if count[0]==1: raise OSError('injected pidfd failure')
 return original(pid)
g.os.pidfd_open=faulty
raise SystemExit(g.supervise([sys.executable,'-c',sys.argv[3]],g.Path(sys.argv[2]),3))
"""
            result = subprocess.run([sys.executable, '-c', driver, str(HERE/'outer_guard.py'), str(record), comparator], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 1, result.stderr)
            evidence = json.loads(record.read_text())
            self.assertTrue(evidence['all_descendants_absent'])
            self.assertTrue(evidence['whole_groups_absent'])
            self.assertEqual(evidence['signals'][0]['outcome'], 'error')
            self.assertTrue(any(row['outcome'] == 'sent' for row in evidence['signals'][1:]))

    def test_normal_exit(self):
        code, result = self.run_guard('pass')
        self.assertEqual(code, 0)
        self.assertTrue(result['passed'])
        self.assertEqual(result['signals'], [])

    def test_comparator_death_separate_session_child(self):
        code, result = self.run_guard(
            'import subprocess,sys,os; '
            'subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"],start_new_session=True); '
            'os._exit(7)')
        self.assertEqual(code, 1)
        self.assertEqual(result['comparator_exit_code'], 7)
        self.assertEqual(result['failure'], 'comparator exited nonzero')
        self.assertTrue(result['signals'])
        self.assertGreaterEqual(len(result['tracked_groups']), 2)
        self.assertTrue(all(row['signal'] == 'SIGKILL' and row['starttime'] > 0 for row in result['signals']))

    def test_overall_timeout_with_separate_session_child(self):
        code, result = self.run_guard(
            'import subprocess,sys,time; '
            'subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"],start_new_session=True); '
            'time.sleep(30)')
        self.assertEqual(code, 1)
        self.assertEqual(result['failure'], 'overall wall deadline')
        self.assertGreaterEqual(len(result['tracked_groups']), 2)
        self.assertTrue(result['signals'])
        self.assertTrue(result['reaped_adopted_children'])

    def test_zero_exit_with_surviving_child_fails_closed(self):
        code, result = self.run_guard(
            'import subprocess,sys; '
            'subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"],start_new_session=True)')
        self.assertEqual(code, 1)
        self.assertEqual(result['comparator_exit_code'], 0)
        self.assertEqual(result['failure'], 'comparator exited with surviving descendants')
        self.assertTrue(result['signals'])

if __name__ == '__main__': unittest.main()
