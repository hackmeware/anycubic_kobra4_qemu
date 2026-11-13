"""Read-only grouped telemetry for the isolated STOP-event clock experiment.

Uses the original bounded transport, reply validation, and STOP event sequencing.
There is deliberately no fallback to individually sampled properties. Callers
retain the original coordinator's 1 ms slices, 5 ms lead and 1 ms lag limits.
"""
import threading
import time

from diagnostic_timer_clock import QMPStream
from stop_event_clock import StopEventClockClient, BoundedStreamPair, ClockError


class SnapshotClockClient(StopEventClockClient):
    SOURCE = 'rv1106-virtual-clock-state'
    INTS = ('schema', 'epoch', 'virtual_time_ns', 'deadline_ns', 'fired_ns', 'stop_ns')
    BOOLS = ('enabled', 'initialized', 'running', 'armed', 'fired')

    def __init__(self, reader, writer, timeout=3):
        if timeout <= 0:
            raise ValueError('Positive QMP timeout required')
        self.timeout = timeout
        self.request_lock = threading.RLock()
        self.event_sequence = self.resume_sequence = self.stop_sequence = 0
        self.requests_sent = self.writes_sent = self.events_received = 0
        self.epoch = self.previous_time = None
        self.last_deadline = self.last_stop = self.last_fired = None
        QMPStream.__init__(self, BoundedStreamPair(reader, writer, timeout))
        self.snapshot()

    def get(self, name):
        """Explicit diagnostic scalar access; never used as a clock fallback."""
        return self.call('qom-get', {'path': '/machine', 'property': name})

    def snapshot(self):
        # Hold ownership through validation, not only the wire exchange.
        if not self.request_lock.acquire(blocking=False):
            raise ClockError('QMP request already pending')
        try:
            state = self.call('qom-get', {'path': '/machine', 'property': 'virtual-clock-state'})
            if not isinstance(state, dict):
                raise ClockError('Clock snapshot must be an object')
            for field in self.INTS:
                if type(state.get(field)) is not int:
                    raise ClockError('Invalid clock snapshot integer: ' + field)
            for field in self.BOOLS:
                if type(state.get(field)) is not bool:
                    raise ClockError('Invalid clock snapshot boolean: ' + field)
            if state.get('source') != self.SOURCE or state['schema'] != 1:
                raise ClockError('Unsupported clock snapshot schema/source')
            if not state['enabled'] or not state['initialized']:
                raise ClockError('Clock snapshot requires enabled and initialized clock')
            epoch, now = state['epoch'], state['virtual_time_ns']
            if epoch <= 0 or (self.epoch is not None and epoch != self.epoch):
                raise ClockError('QEMU clock epoch changed or invalid')
            if now < 0 or (self.previous_time is not None and now < self.previous_time):
                raise ClockError('Invalid or reversed QEMU virtual-time telemetry')
            if state['deadline_ns'] < 0 or any(state[field] < -1 for field in ('fired_ns', 'stop_ns')):
                raise ClockError('Invalid clock snapshot timestamp')
            if state['armed'] and state['fired']:
                raise ClockError('Inconsistent armed/fired snapshot')
            self.epoch, self.previous_time = epoch, now
            return state
        except Exception:
            self.invalid = True
            raise
        finally:
            self.request_lock.release()

    def paused_now(self):
        try:
            state = self.snapshot()
            self._paused(state)
            return state['virtual_time_ns']
        except Exception:
            self.invalid = True
            raise

    def now(self):
        return self.snapshot()['virtual_time_ns']

    def run_until(self, deadline):
        if type(deadline) is not int:
            raise ClockError('Deadline must be integer nanoseconds')
        if not self.request_lock.acquire(blocking=False):
            raise ClockError('QMP request already pending')
        try:
            phase_start = time.monotonic()
            before = self.snapshot()
            self._paused(before)
            if before['armed']:
                raise ClockError('Clock already armed before requested run')
            if deadline <= before['virtual_time_ns']:
                raise ClockError('Deadline is not in the future')
            self.call('qom-set', {'path': '/machine', 'property': 'virtual-deadline-ns', 'value': deadline})
            state = self.snapshot()
            self._paused(state)
            if (not state['armed'] or state['fired'] or state['deadline_ns'] != deadline
                    or state['fired_ns'] != -1 or state['stop_ns'] != -1
                    or state['virtual_time_ns'] != before['virtual_time_ns']):
                raise ClockError('QEMU did not arm requested virtual deadline cleanly')
            armed_at = time.monotonic()
            baseline = self.event_sequence
            self.call('cont')
            self._wait_stop(baseline, armed_at + self.timeout)
            stopped_at = time.monotonic()
            state = self.snapshot()
            self._paused(state)
            if not state['fired'] or state['armed'] or state['deadline_ns'] != deadline:
                raise ClockError('Unexpected pause without requested virtual deadline')
            now, stop, fired = state['virtual_time_ns'], state['stop_ns'], state['fired_ns']
            if stop < deadline or stop != now:
                raise ClockError('Invalid deadline stop telemetry')
            if not deadline <= fired <= stop:
                raise ClockError('Invalid deadline callback telemetry')
            self.last_phase_wall_s = {'arming': armed_at-phase_start,
                                     'execution_wait': stopped_at-armed_at,
                                     'final_checks': time.monotonic()-stopped_at}
            self.last_deadline, self.last_stop, self.last_fired = deadline, stop, fired
            return now
        except Exception:
            self.invalid = True
            try:
                self.call('stop')
            except Exception:
                pass
            raise
        finally:
            self.request_lock.release()
