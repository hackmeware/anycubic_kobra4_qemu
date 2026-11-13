import json
import os
import pathlib
import sys
import threading
import time
import unittest
from unittest.mock import patch

BASE = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE / 'scripts'))
sys.path.insert(0, str(BASE / 'experimental/batched-clock'))
from stop_event_clock import StopEventClockClient, BoundedStreamPair, ClockError


class MachineStream:
    def __init__(self, order='before', overrides=None):
        self.timeout = 1
        self.responses = [{'QMP': {}}]
        self.running = False
        self.target = self.value = 0
        self.epoch = 1
        self.armed = self.fired = False
        self.order = order
        self.overrides = overrides or {}
        self.commands = []
        self.bad_reply = None
        self.closed = False

    def write(self, data):
        replies = []
        for line in data.splitlines():
            request = json.loads(line)
            c, a = request['execute'], request.get('arguments', {})
            self.commands.append(c)
            result = {}
            if c == 'query-status':
                result = {'running': self.overrides.get('running', self.running)}
            elif c == 'qom-get':
                p = a['property']
                result = self.overrides.get(p, {
                    'virtual-deadline-enabled': True,
                    'virtual-clock-epoch': self.epoch,
                    'virtual-time-ns': self.value,
                    'virtual-deadline-armed': self.armed,
                    'virtual-deadline-fired': self.fired,
                    'virtual-deadline-stop-ns': self.value,
                    'virtual-deadline-fired-ns': self.target,
                }[p])
            elif c == 'qom-set':
                self.target = a['value']
                self.armed, self.fired = True, False
            elif c == 'cont':
                self.value = self.target + 1
                self.armed, self.fired = False, True
                if callable(self.order):
                    events = self.order(self)
                else:
                    events = [{'event': 'RESUME'}, {'event': 'STOP'}]
                response = {'id': request['id'], 'return': result}
                replies += events + [response] if self.order != 'after' else [response] + events
                continue
            elif c == 'stop':
                self.running = False
            replies.append({'id': request['id'], 'return': result})
        if self.bad_reply:
            replies = self.bad_reply(replies)
        self.responses += replies
        return len(data)

    def flush(self):
        pass

    def readline(self):
        if not self.responses:
            raise ClockError('injected read timeout')
        return json.dumps(self.responses.pop(0)).encode() + b'\n'

    def close(self):
        self.closed = True


def client(order='before', overrides=None):
    stream = MachineStream(order, overrides)
    with patch('stop_event_clock.BoundedStreamPair', return_value=stream):
        q = StopEventClockClient(None, None, timeout=.05)
    return q, stream


class Tests(unittest.TestCase):
    def test_full_pipe_write_is_bounded(self):
        from benchmark_qemu import CountingWriter
        rfd, wfd = os.pipe()
        r, w = os.fdopen(rfd, 'rb', buffering=0), os.fdopen(wfd, 'wb', buffering=0)
        stream = BoundedStreamPair(r, CountingWriter(w), timeout=.01)
        try:
            while True:
                try:
                    os.write(wfd, b'x' * 4096)
                except BlockingIOError:
                    break
            begin = time.monotonic()
            with self.assertRaisesRegex(ClockError, 'write timeout'):
                stream.write(b'command\n')
            self.assertLess(time.monotonic()-begin, .5)
        finally:
            stream.close()

    def test_successive_runs(self):
        q, _ = client('after')
        for step in range(1, 5):
            self.assertEqual(q.run_until(step * 1000000), step * 1000000 + 1)

    def test_failed_arming_never_resumes(self):
        q, s = client(overrides={'virtual-deadline-armed': False})
        with self.assertRaisesRegex(ClockError, 'did not arm'):
            q.run_until(1000000)
        self.assertNotIn('cont', s.commands)

    def test_wait_after_cont_reply_lifecycle_and_timeout(self):
        for event in ('RESET', 'SHUTDOWN', 'GUEST_PANICKED', None):
            q, s = client('after')
            write = s.write
            def inject(data, event=event):
                n = write(data)
                if any(json.loads(line)['execute'] == 'cont' for line in data.splitlines()):
                    s.responses = [x for x in s.responses if 'event' not in x]
                    if event:
                        s.responses += [{'event': event}]
                return n
            s.write = inject
            with self.assertRaises(ClockError):
                q.run_until(1000000)
            self.assertTrue(q.invalid)

    def test_final_read_failure_and_failed_cleanup_keep_original_error(self):
        q, s = client('after')
        read = s.readline
        def broken():
            if s.commands.count('query-status') >= 2:
                raise ClockError('final transport failed')
            return read()
        s.readline = broken
        with self.assertRaisesRegex(ClockError, 'final transport failed'):
            q.run_until(1000000)
        self.assertEqual(s.commands[-1], 'stop')

    def test_run_holds_owner_lock_while_waiting(self):
        q, _ = client('after')
        waiting, release = threading.Event(), threading.Event()
        wait = q._wait_stop
        errors = []
        def block(baseline, deadline):
            waiting.set()
            release.wait(1)
            wait(baseline, deadline)
        q._wait_stop = block
        def run():
            try:
                q.run_until(1000000)
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=run)
        thread.start()
        try:
            self.assertTrue(waiting.wait(1))
            with self.assertRaisesRegex(ClockError, 'pending'):
                q.call('query-status')
        finally:
            release.set()
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_consumed_stop_still_respects_expired_deadline(self):
        q, _ = client()
        q.resume_sequence, q.stop_sequence = 1, 2
        with self.assertRaisesRegex(ClockError, 'timed out'):
            q._wait_stop(0, time.monotonic()-1)

    def test_stop_before_and_after_cont_reply(self):
        for order in ('before', 'after'):
            with self.subTest(order=order):
                q, s = client(order)
                self.assertEqual(q.run_until(1000000), 1000001)
                self.assertEqual((q.last_deadline, q.last_fired, q.last_stop), (1000000, 1000000, 1000001))
                self.assertEqual(s.commands.count('query-status'), 2)

    def test_several_cycles_do_not_reuse_old_stop(self):
        q, s = client()
        q.run_until(1000000)
        s.order = lambda _: [{'event': 'RESUME'}]
        with self.assertRaises(ClockError):
            q.run_until(2000000)
        self.assertTrue(q.invalid)
        self.assertEqual(s.commands[-1], 'stop')

    def test_old_stop_before_resume_is_not_completion(self):
        q, _ = client(lambda _: [{'event': 'STOP'}, {'event': 'RESUME'}])
        with self.assertRaises(ClockError):
            q.run_until(1000000)

    def test_missing_resume_rejected(self):
        q, _ = client(lambda _: [{'event': 'STOP'}])
        with self.assertRaises(ClockError):
            q.run_until(1000000)

    def test_unrelated_events_allowed(self):
        q, _ = client(lambda _: [{'event': 'RESUME'}, {'event': 'DEVICE_DELETED'}, {'event': 'STOP'}])
        self.assertEqual(q.run_until(1000000), 1000001)

    def test_lifecycle_events_invalidate(self):
        for event in ('RESET', 'SHUTDOWN', 'GUEST_PANICKED'):
            for phase in ('before', 'after'):
                with self.subTest(event=event, phase=phase):
                    q, s = client()
                    s.order = lambda _, event=event, phase=phase: (
                        [{'event': event}] if phase == 'before' else
                        [{'event': 'RESUME'}, {'event': 'STOP'}, {'event': event}])
                    with self.assertRaises(ClockError):
                        q.run_until(1000000)
                    self.assertTrue(q.invalid)

    def test_final_clock_and_stop_guards(self):
        for key, value in (
            ('running', True), ('virtual-clock-epoch', 2), ('virtual-clock-epoch', True),
            ('virtual-time-ns', -1), ('virtual-time-ns', True),
            ('virtual-deadline-fired', False), ('virtual-deadline-armed', True),
            ('virtual-deadline-stop-ns', 999999), ('virtual-deadline-stop-ns', 1000002),
            ('virtual-deadline-stop-ns', True), ('virtual-deadline-fired-ns', 999999),
            ('virtual-deadline-fired-ns', 1000002), ('virtual-deadline-fired-ns', True),
        ):
            with self.subTest(key=key, value=value):
                def changed(s, key=key, value=value):
                    s.overrides[key] = value
                    return [{'event': 'RESUME'}, {'event': 'STOP'}]
                q, _ = client(changed)
                with self.assertRaises(ClockError):
                    q.run_until(1000000)
                self.assertTrue(q.invalid)

    def test_wrong_reply_and_partial_batches_invalidate(self):
        for fault in (lambda r: [r[0], r[0]], lambda r: r[:1],
                      lambda r: [{'id': 999, 'return': 0}], lambda r: [{'id': r[0]['id'], 'error': {}}]):
            q, s = client()
            s.bad_reply = fault
            with self.assertRaises(ClockError):
                q.properties(['virtual-clock-epoch', 'virtual-time-ns'])
            self.assertTrue(q.invalid)

    def test_out_of_order_read_replies_are_mapped(self):
        q, s = client()
        s.bad_reply = lambda r: list(reversed(r))
        self.assertEqual(q.properties(['virtual-clock-epoch', 'virtual-time-ns']), [1, 0])

    def test_flood_cannot_extend_absolute_deadline(self):
        q, s = client()
        s.readline = lambda: b'{"event":"IGNORED"}\n'
        for action in (lambda: q.call('query-status'), lambda: q._wait_stop(0, .04)):
            with patch('stop_event_clock.time.monotonic', side_effect=[.01, .02, .03, .04, .05, .1, .2]):
                with self.assertRaises(ClockError):
                    action()

    def test_disconnect_and_malformed_json_invalidate(self):
        for raw in (b'', b'{invalid json}\n', b'[]\n'):
            q, s = client()
            s.readline = lambda raw=raw: raw
            with self.assertRaises(ClockError):
                q.call('query-status')
            self.assertTrue(q.invalid)

    def test_failed_connection_rejects_regular_commands_but_allows_stop(self):
        q, s = client()
        q.invalid = True
        with self.assertRaises(ClockError):
            q.call('cont')
        self.assertEqual(q.call('stop'), {})
        self.assertNotIn('cont', s.commands)

    def test_partial_write_invalidates_without_cont(self):
        q, s = client()
        s.write = lambda data: len(data) - 1
        with self.assertRaises(ClockError):
            q.call('query-status')
        self.assertTrue(q.invalid)

    def test_non_object_malformed_and_unexpected_wait_reply(self):
        for bad in ([], {'id': 77, 'return': {}}, {'event': 8}):
            q, _ = client(lambda _, bad=bad: [bad])
            with self.assertRaises(ClockError):
                q.run_until(1000000)

    def test_batch_cannot_mutate(self):
        q, _ = client()
        with self.assertRaises(ClockError):
            q.batch([('cont', None)])

    def test_invalid_deadlines_do_not_send(self):
        for deadline in (True, 1.5, 0, -1):
            q, s = client()
            with self.assertRaises(ClockError):
                q.run_until(deadline)
            self.assertNotIn('cont', s.commands)

    def test_concurrent_owner_rejected(self):
        q, _ = client()
        held, release = threading.Event(), threading.Event()
        def hold():
            with q.request_lock:
                held.set()
                release.wait(1)
        thread = threading.Thread(target=hold)
        thread.start()
        try:
            self.assertTrue(held.wait(1))
            with self.assertRaises(ClockError):
                q.call('query-status')
            with self.assertRaises(ClockError):
                q.run_until(1000000)
        finally:
            release.set()
            thread.join()

    def test_unchanged_coordinator_lead_lag_guards(self):
        from batched_lockstep import LockstepCoordinator
        g = LockstepCoordinator.__new__(LockstepCoordinator)
        g.q0 = g.r0 = g.max_lead = g.max_lag = 0
        g.max_lead_ns = 5000000
        self.assertEqual(g._check(1000001, 1000000, 0), 1)
        for q, r, lag in ((6000001, 1000000, 0), (0, 1000001, 1000000), (999999, 1000000, 0)):
            with self.assertRaises(RuntimeError):
                g._check(q, r, lag)


if __name__ == '__main__':
    unittest.main()
