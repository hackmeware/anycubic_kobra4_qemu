"""Real dummy processes plus fault tests. Never launches Renode/QEMU/firmware."""
import ctypes
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bootstrap_compare', HERE/'compare.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def dummy(code):
    return subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True)


class ProcessSafetyTests(unittest.TestCase):
    def finish(self, p):
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait(timeout=1)
        for stream in (p.stdin, p.stdout, p.stderr):
            if stream and not stream.closed: stream.close()

    def test_clean_requires_absent_whole_group(self):
        p = dummy('pass')
        self.addCleanup(self.finish, p)
        record = {'passed': True}
        guard = c.ProcessGuard(p, time.monotonic()+3, record)
        p.wait(timeout=1)
        self.assertTrue(guard.close())
        self.assertTrue(record['process_group_absent'])
        self.assertTrue(record['watchdog_stopped'])
        self.assertEqual(record['forced_signals'], [])

    def test_blocked_pipe_is_bounded_and_group_killed(self):
        p = dummy('import time; time.sleep(20)')
        self.addCleanup(self.finish, p)
        record = {'passed': False}
        guard = c.ProcessGuard(p, time.monotonic()+3, record)
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            c.bounded_send(p, b'x'*(1024*1024), time.monotonic()+.08)
        self.assertLess(time.monotonic()-started, .5)
        self.assertFalse(guard.close())
        self.assertTrue(record['process_group_absent'])
        self.assertEqual([x['signal'] for x in record['forced_signals']], ['SIGKILL'])
        self.assertEqual(record['forced_signals'][0]['outcome'], 'sent')

    def test_stopped_process_is_killed_never_resumed(self):
        p = dummy('import time; time.sleep(20)')
        self.addCleanup(self.finish, p)
        os.kill(p.pid, signal.SIGSTOP)
        record = {'passed': False}
        guard = c.ProcessGuard(p, time.monotonic()+3, record)
        guard.close()
        self.assertEqual(record['exit_code'], -signal.SIGKILL)
        self.assertEqual([x['signal'] for x in record['forced_signals']], ['SIGKILL'])
        self.assertTrue(record['watchdog_stopped'])
        self.assertTrue(record['process_group_absent'])

    def test_expiry_is_joined_and_cannot_signal_next_leg(self):
        p = dummy('import time; time.sleep(20)')
        self.addCleanup(self.finish, p)
        record = {'passed': False}
        guard = c.ProcessGuard(p, time.monotonic()+2.02, record)
        p.wait(timeout=1)
        guard.close()
        signals = list(record['forced_signals'])
        time.sleep(.05)
        self.assertFalse(guard.timer.is_alive())
        self.assertEqual(guard.signals, signals)
        self.assertEqual(signals[0]['reason'], 'absolute_runtime_deadline')
        self.assertTrue(record['process_group_absent'])

    def test_exited_leader_does_not_hide_live_descendant(self):
        # Linux subreaper lets this test reap its own intentionally orphaned dummy.
        libc = ctypes.CDLL(None, use_errno=True)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)  # PR_SET_CHILD_SUBREAPER
        self.addCleanup(lambda: libc.prctl(36, 0, 0, 0, 0))
        p = dummy('import os,time; child=os.fork(); '
                  'print(child,flush=True) if child else None; '
                  'os._exit(0) if child else time.sleep(20)')
        self.addCleanup(self.finish, p)
        child = int(p.stdout.readline())
        p.wait(timeout=1)
        record = {'passed': True}
        guard = c.ProcessGuard(p, time.monotonic()+3, record)
        reaped = []
        waiter = threading.Thread(target=lambda: reaped.append(os.waitpid(child, 0)))
        waiter.start()
        self.assertFalse(guard.close())
        waiter.join(timeout=1)
        self.assertFalse(waiter.is_alive())
        self.assertTrue(record['process_group_absent'])
        self.assertEqual(record['exit_code'], 0)
        self.assertFalse(record['clean_exit'])
        self.assertFalse(record['passed'])
        self.assertEqual(record['forced_signals'][0]['signal'], 'SIGKILL')
        self.assertEqual(reaped[0][0], child)

    def test_running_expiry_thread_joined(self):
        p = dummy('import time; time.sleep(20)')
        self.addCleanup(self.finish, p)
        record = {'passed': False}
        entered, release = threading.Event(), threading.Event()
        original = c.ProcessGuard.kill
        def delayed_kill(guard, reason):
            if reason == 'absolute_runtime_deadline':
                entered.set()
                release.wait(timeout=.2)
            original(guard, reason)
        with patch.object(c.ProcessGuard, 'kill', delayed_kill):
            guard = c.ProcessGuard(p, time.monotonic()+2.01, record)
            self.assertTrue(entered.wait(timeout=1))
            releaser = threading.Timer(.04, release.set)
            releaser.start()
            guard.close()
            releaser.join(timeout=1)
        self.assertTrue(record['watchdog_stopped'])
        self.assertFalse(guard.timer.is_alive())
        self.assertTrue(record['process_group_absent'])

if __name__ == '__main__': unittest.main()
