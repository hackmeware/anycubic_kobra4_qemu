"""Isolated STOP-event QMP client; no guest timing or launcher changes.

QMP STOP is a wakeup, not proof that the correct virtual deadline completed.
Every paused, epoch, actual-clock, armed/fired, and callback check still runs.
"""
import json
import os
import select
import threading
import time

from diagnostic_timer_clock import ClockError, QMPStream, StreamPair


class BoundedStreamPair(StreamPair):
    """Exclusive binary streams, with raw deadline-aware pipe writes.

    The caller must not have queued buffered output on the supplied writer.
    Writes bypass Python buffering; flush is intentionally unnecessary.
    """
    def __init__(self, reader, writer, timeout=3):
        super().__init__(reader, writer, timeout)
        self.write_fd = writer.fileno()
        os.set_blocking(self.write_fd, False)

    def write(self, data):
        deadline = time.monotonic() + self.timeout
        remaining_data = memoryview(data)
        while remaining_data:
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                raise ClockError('QMP pipe write timeout')
            try:
                written = os.write(self.write_fd, remaining_data)
            except BlockingIOError:
                if not select.select([], [self.write_fd], [], remaining_time)[1]:
                    raise ClockError('QMP pipe write timeout')
                continue
            except OSError as exc:
                raise ClockError('QMP pipe write failed') from exc
            if written <= 0:
                raise ClockError('QMP pipe write disconnected')
            remaining_data = remaining_data[written:]
        return len(data)

    def flush(self):
        pass


class StopEventClockClient(QMPStream):
    def __init__(self, reader, writer, timeout=3):
        if timeout <= 0:
            raise ValueError('Positive QMP timeout required')
        self.timeout = timeout
        self.request_lock = threading.RLock()
        self.event_sequence = self.resume_sequence = self.stop_sequence = 0
        self.requests_sent = self.writes_sent = self.events_received = 0
        super().__init__(BoundedStreamPair(reader, writer, timeout))
        enabled, epoch = self.properties(['virtual-deadline-enabled', 'virtual-clock-epoch'])
        if enabled is not True:
            raise ClockError('QEMU virtual deadline mode was not explicitly enabled')
        if type(epoch) is not int or epoch < 0:
            raise ClockError('Invalid QEMU clock epoch')
        self.epoch = epoch
        self.last_deadline = self.last_stop = self.last_fired = None

    def _read(self):
        value = super()._read()
        if not isinstance(value, dict):
            raise ClockError('QMP response must be an object')
        return value

    def _event(self, value):
        if 'event' not in value:
            return False
        name = value['event']
        if not isinstance(name, str) or 'id' in value:
            raise ClockError('Malformed QMP event')
        self.event_sequence += 1
        self.events_received += 1
        if name in ('RESET', 'SHUTDOWN', 'GUEST_PANICKED'):
            raise ClockError('QMP lifecycle event invalidated clock: ' + name)
        if name == 'RESUME':
            self.resume_sequence = self.event_sequence
        elif name == 'STOP':
            self.stop_sequence = self.event_sequence
        return True

    def _exchange(self, requests):
        if not self.request_lock.acquire(blocking=False):
            raise ClockError('QMP request already pending')
        try:
            if self.invalid and any(c not in ('stop', 'quit') for c, _ in requests):
                raise ClockError('QMP connection invalidated')
            pending, wire, values = {}, [], [None] * len(requests)
            for index, (command, args) in enumerate(requests):
                self.serial += 1
                pending[self.serial] = index
                request = {'execute': command, 'id': self.serial}
                if args is not None:
                    request['arguments'] = args
                wire.append(json.dumps(request) + '\n')
            payload = ''.join(wire).encode()
            if self.stream.write(payload) != len(payload):
                raise ClockError('Incomplete QMP request write')
            self.stream.flush()
            self.requests_sent += len(requests)
            self.writes_sent += 1
            deadline = time.monotonic() + self.timeout
            old_timeout = self.stream.timeout
            try:
                while pending:
                    self.stream.timeout = deadline - time.monotonic()
                    if self.stream.timeout <= 0:
                        raise ClockError('QMP exchange timed out with pending requests')
                    reply = self._read()
                    if self._event(reply):
                        continue
                    ident = reply.get('id')
                    if type(ident) is not int or ident not in pending:
                        raise ClockError('Unexpected or duplicate QMP reply id')
                    if 'error' in reply or 'return' not in reply:
                        raise ClockError('QMP command failed: ' + str(reply))
                    values[pending.pop(ident)] = reply['return']
            finally:
                self.stream.timeout = old_timeout
            return values
        except Exception:
            self.invalid = True
            raise
        finally:
            self.request_lock.release()

    def call(self, command, arguments=None):
        return self._exchange([(command, arguments)])[0]

    def batch(self, requests):
        if not requests or any(c not in ('qom-get', 'query-status') for c, _ in requests):
            raise ClockError('Batch requires nonempty read-only queries')
        return self._exchange(requests)

    def properties(self, names):
        return self.batch([('qom-get', {'path': '/machine', 'property': p}) for p in names])

    def validate_clock(self, epoch, value):
        if type(epoch) is not int or epoch != self.epoch:
            raise ClockError('QEMU clock epoch changed')
        if type(value) is not int or value < 0:
            raise ClockError('Invalid QEMU virtual-time telemetry')

    @staticmethod
    def _paused(status):
        if not isinstance(status, dict) or status.get('running') is not False:
            raise ClockError('QEMU unexpectedly running')

    def paused_now(self):
        status, epoch, value = self.batch([('query-status', None)] + [
            ('qom-get', {'path': '/machine', 'property': p})
            for p in ('virtual-clock-epoch', 'virtual-time-ns')])
        self._paused(status)
        self.validate_clock(epoch, value)
        return value

    def now(self):
        epoch, value = self.properties(['virtual-clock-epoch', 'virtual-time-ns'])
        self.validate_clock(epoch, value)
        return value

    def _wait_stop(self, baseline, deadline):
        # cont may consume RESUME and STOP before its own response arrives.
        # Require a new RESUME followed by STOP, never reuse an earlier event.
        old_timeout = self.stream.timeout
        try:
            if time.monotonic() >= deadline:
                raise ClockError('QMP STOP event timed out')
            while not baseline < self.resume_sequence < self.stop_sequence:
                self.stream.timeout = deadline - time.monotonic()
                if self.stream.timeout <= 0:
                    raise ClockError('QMP STOP event timed out')
                value = self._read()
                if not self._event(value):
                    raise ClockError('Unexpected QMP response while waiting for STOP')
        finally:
            self.stream.timeout = old_timeout

    def run_until(self, deadline):
        if type(deadline) is not int:
            raise ClockError('Deadline must be integer nanoseconds')
        if not self.request_lock.acquire(blocking=False):
            raise ClockError('QMP request already pending')
        try:
            phase_start = time.monotonic()
            if deadline <= self.paused_now():
                raise ClockError('Deadline is not in the future')
            self.call('qom-set', {'path': '/machine', 'property': 'virtual-deadline-ns', 'value': deadline})
            if self.properties(['virtual-deadline-armed'])[0] is not True:
                raise ClockError('QEMU did not arm virtual deadline')
            armed_at = time.monotonic()
            baseline = self.event_sequence
            self.call('cont')
            self._wait_stop(baseline, armed_at + self.timeout)
            stopped_at = time.monotonic()
            status, fired_flag, armed, stop, epoch, now, fired = self.batch(
                [('query-status', None)] + [('qom-get', {'path': '/machine', 'property': p}) for p in (
                    'virtual-deadline-fired', 'virtual-deadline-armed', 'virtual-deadline-stop-ns',
                    'virtual-clock-epoch', 'virtual-time-ns', 'virtual-deadline-fired-ns')])
            self._paused(status)
            self.validate_clock(epoch, now)
            if fired_flag is not True or armed is not False:
                raise ClockError('Unexpected pause without completed virtual deadline')
            if type(stop) is not int or stop < deadline or stop != now:
                raise ClockError('Invalid deadline stop telemetry')
            if type(fired) is not int or not deadline <= fired <= stop:
                raise ClockError('Invalid deadline callback telemetry')
            self.last_phase_wall_s = {'arming': armed_at-phase_start,
                                     'execution_wait': stopped_at-armed_at,
                                     'final_checks': time.monotonic()-stopped_at}
            self.last_deadline, self.last_stop, self.last_fired = deadline, stop, fired
            return now
        except Exception:
            self.invalid = True
            # Best effort only. The owner must terminate/reap if QMP cleanup fails.
            try:
                self.call('stop')
            except Exception:
                pass
            raise
        finally:
            self.request_lock.release()

    def close(self):
        self.stream.close()
