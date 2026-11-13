"""Offline snapshot faults and inherited STOP-event/transport regression suite."""
import copy
import json
import pathlib
import sys
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'experimental/stop-event-clock'),
                str(ROOT / 'experimental/batched-clock')]
from snapshot_clock import SnapshotClockClient, ClockError
import test_stop_event_clock as original


class MachineStream(original.MachineStream):
    def __init__(self, order='before', overrides=None):
        super().__init__(order)
        self.snapshot_overrides = overrides or {}
        self.read_count = 0
        self.transform = None
        self.fired_ns = self.stop_ns = -1

    def write(self, data):
        # Let the original fake simulate cont ordering and all generic commands.
        for line in data.splitlines():
            req = json.loads(line)
            command, args = req['execute'], req.get('arguments', {})
            if command == 'qom-get' and args['property'] == 'virtual-clock-state':
                self.commands.append(command)
                self.read_count += 1
                state = dict(schema=1, source=SnapshotClockClient.SOURCE, enabled=True,
                             initialized=True, running=self.running, epoch=self.epoch,
                             virtual_time_ns=self.value, deadline_ns=self.target,
                             armed=self.armed, fired=self.fired,
                             fired_ns=self.fired_ns, stop_ns=self.stop_ns)
                state.update(self.snapshot_overrides)
                if self.transform:
                    state = self.transform(state)
                replies = [{'id': req['id'], 'return': state}]
                self.responses.extend(self.bad_reply(replies) if self.bad_reply else replies)
            else:
                if command == 'qom-set':
                    self.fired_ns = self.stop_ns = -1
                super().write(line + b'\n')
                if command == 'cont':
                    self.fired_ns, self.stop_ns = self.target, self.value
        return len(data)


def client(order='before', overrides=None):
    stream = MachineStream(order, overrides)
    with patch('snapshot_clock.BoundedStreamPair', return_value=stream):
        q = SnapshotClockClient(None, None, timeout=.05)
    return q, stream


class Tests(unittest.TestCase):
    def test_successive_runs_and_only_three_snapshot_reads(self):
        for order in ('before', 'after'):
            q, s = client(order)
            for step in range(1, 5):
                self.assertEqual(q.run_until(step*1000000), step*1000000+1)
                self.assertEqual(q.last_fired, step*1000000)
                self.assertEqual(q.last_deadline, step*1000000)
            self.assertEqual(s.read_count, 13)
            self.assertNotIn('query-status', s.commands)
            self.assertEqual(q.requests_sent, 22)  # handshake, initial, 4 * 5
            self.assertEqual(q.writes_sent, q.requests_sent)

    def test_schema_missing_every_field(self):
        for key in (*SnapshotClockClient.INTS, *SnapshotClockClient.BOOLS, 'source'):
            q, s = client()
            s.transform = lambda state, key=key: {k:v for k,v in state.items() if k != key}
            with self.subTest(field=key), self.assertRaises(ClockError):
                q.now()
            self.assertTrue(q.invalid)

    def test_strict_types_for_every_field(self):
        for key in SnapshotClockClient.INTS:
            for value in (True, 1.0, '1', None):
                q, s = client()
                s.snapshot_overrides[key] = value
                with self.subTest(field=key, value=value), self.assertRaises(ClockError):
                    q.now()
                self.assertTrue(q.invalid)
        for key in SnapshotClockClient.BOOLS:
            for value in (0, 1, 'true', None):
                q, s = client()
                s.snapshot_overrides[key] = value
                with self.subTest(field=key, value=value), self.assertRaises(ClockError):
                    q.now()
                self.assertTrue(q.invalid)

    def test_bad_schema_lifecycle_epoch_and_ranges(self):
        for key, value in (('schema', 2), ('source', 'wrong'), ('enabled', False),
                           ('initialized', False), ('epoch', 0), ('epoch', -1),
                           ('epoch', 2), ('virtual_time_ns', -1), ('deadline_ns', -1),
                           ('fired_ns', -2), ('stop_ns', -2)):
            q, s = client()
            s.snapshot_overrides[key] = value
            with self.subTest(field=key, value=value), self.assertRaises(ClockError):
                q.now()
            self.assertTrue(q.invalid)

    def test_initial_invalid_and_unsupported_never_fallback(self):
        for changes in ({'epoch': 0}, {'enabled': False}, {'initialized': False}):
            with self.assertRaises(ClockError):
                client(overrides=changes)
        s = MachineStream()
        # Capabilities succeeds; inject failure only into the initial snapshot.
        s.bad_reply = lambda replies: (
            [{'id': replies[0]['id'], 'error': {'desc': 'unsupported snapshot'}}]
            if s.commands[-1] == 'qom-get' and s.read_count == 1 else replies)
        with patch('snapshot_clock.BoundedStreamPair', return_value=s):
            with self.assertRaisesRegex(ClockError, 'unsupported snapshot'):
                SnapshotClockClient(None, None)
        self.assertEqual(s.commands, ['qmp_capabilities', 'qom-get'])
        self.assertEqual(s.read_count, 1)

    def test_snapshot_nonobject_and_reversed_time(self):
        for bad in (None, [], 1, 'state'):
            q, s = client()
            s.transform = lambda _, bad=bad: bad
            with self.assertRaises(ClockError):
                q.now()
            self.assertTrue(q.invalid)
        q, s = client()
        s.value = 20
        self.assertEqual(q.now(), 20)
        s.value = 19
        with self.assertRaises(ClockError):
            q.now()
        self.assertTrue(q.invalid)

    def test_prearm_running_or_armed_never_continues(self):
        for key in ('running', 'armed'):
            q, s = client()
            s.snapshot_overrides[key] = True
            with self.assertRaises(ClockError):
                q.run_until(1000000)
            self.assertTrue(q.invalid)
            self.assertNotIn('cont', s.commands)
            self.assertEqual(s.commands[-1], 'stop')

    def test_bad_armed_snapshots_never_continue(self):
        for key, value in (('armed', False), ('fired', True), ('deadline_ns', 999999),
                           ('running', True), ('fired_ns', 0), ('stop_ns', 0),
                           ('virtual_time_ns', 1), ('epoch', 2), ('initialized', False)):
            q, s = client()
            s.transform = lambda state, key=key, value=value: (
                dict(state, **{key:value}) if s.armed else state)
            with self.subTest(field=key), self.assertRaises(ClockError):
                q.run_until(1000000)
            self.assertNotIn('cont', s.commands)
            self.assertTrue(q.invalid)

    def test_final_snapshot_guards(self):
        for key, value in (('running', True), ('fired', False), ('armed', True),
                           ('deadline_ns', 999999), ('deadline_ns', 1000001),
                           ('stop_ns', -1), ('stop_ns', 999999), ('stop_ns', 1000002),
                           ('fired_ns', -1), ('fired_ns', 999999), ('fired_ns', 1000002),
                           ('virtual_time_ns', 0), ('epoch', 2), ('enabled', False)):
            q, s = client()
            s.transform = lambda state, key=key, value=value: (
                dict(state, **{key:value}) if s.fired else state)
            with self.subTest(field=key, value=value), self.assertRaises(ClockError):
                q.run_until(1000000)
            self.assertTrue(q.invalid)
            self.assertEqual(s.commands[-1], 'stop')
            self.assertIsNone(q.last_deadline)

    def test_partial_stale_and_missing_replies(self):
        q, s = client()
        stale = q.snapshot()
        s.transform = lambda _: copy.deepcopy(stale)
        with self.assertRaises(ClockError):
            q.run_until(1000000)
        self.assertNotIn('cont', s.commands)
        for fault in (lambda _: [], lambda _: [{'id': 1, 'return': {}}],
                      lambda r: [{'id': r[0]['id'], 'error': {}}]):
            q, s = client()
            s.bad_reply = fault
            with self.assertRaises(ClockError):
                q.now()
            self.assertTrue(q.invalid)

    def test_failed_final_snapshot_and_cleanup_preserve_error(self):
        q, s = client('after')
        read = s.readline
        def broken():
            if s.read_count >= 4:
                raise ClockError('snapshot transport failure')
            return read()
        s.readline = broken
        with self.assertRaisesRegex(ClockError, 'snapshot transport failure'):
            q.run_until(1000000)
        self.assertTrue(q.invalid)
        self.assertEqual(s.commands[-1], 'stop')

    def test_paused_now_invalidates_running(self):
        q, s = client()
        s.running = True
        with self.assertRaises(ClockError):
            q.paused_now()
        self.assertTrue(q.invalid)

    def test_unsupported_snapshot_command_does_not_fallback(self):
        q, s = client()
        s.bad_reply = lambda r: [{'id': r[0]['id'], 'error': {}}]
        with self.assertRaises(ClockError):
            q.run_until(1000000)
        self.assertEqual(s.commands[-2:], ['qom-get', 'stop'])
        self.assertNotIn('cont', s.commands)


# Execute the original transport/STOP race tests against the new subclass too.
# Tests tied to the old scalar-query fake are covered by snapshot tests above.
INHERITED = (
    'test_run_holds_owner_lock_while_waiting',
    'test_consumed_stop_still_respects_expired_deadline',
    'test_several_cycles_do_not_reuse_old_stop',
    'test_old_stop_before_resume_is_not_completion',
    'test_missing_resume_rejected', 'test_unrelated_events_allowed',
    'test_lifecycle_events_invalidate',
    'test_wait_after_cont_reply_lifecycle_and_timeout',
    'test_flood_cannot_extend_absolute_deadline',
    'test_disconnect_and_malformed_json_invalidate',
    'test_failed_connection_rejects_regular_commands_but_allows_stop',
    'test_partial_write_invalidates_without_cont',
    'test_non_object_malformed_and_unexpected_wait_reply',
    'test_batch_cannot_mutate', 'test_invalid_deadlines_do_not_send',
    'test_concurrent_owner_rejected', 'test_unchanged_coordinator_lead_lag_guards',
    'test_full_pipe_write_is_bounded',
)
class InheritedTests(unittest.TestCase):
    pass

def reuse(name):
    def test(self):
        with patch.object(original, 'client', client):
            getattr(original.Tests, name)(self)
    return test

for name in INHERITED:
    setattr(InheritedTests, name, reuse(name))

if __name__ == '__main__':
    unittest.main()
