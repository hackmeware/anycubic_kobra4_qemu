"""Opt-in RV1106 emulator-only secure-timer clock measurement fixture.

This is diagnostic instrumentation, not production calibration. No firmware or
clock frequency is changed. See ../DIAGNOSTIC_TIMER_CLOCK.md for limitations.
"""
import json
import re

MASK64 = (1 << 64) - 1
BASE = 0xff590000
HZ = 24000000

class ClockError(RuntimeError):
    pass

class QMPStream:
    """Exclusive synchronous QMP connection, including reset/error detection."""
    def __init__(self, stream):
        self.stream = stream
        self.serial = 0
        self.invalid = False
        greeting = self._read()
        if 'QMP' not in greeting:
            raise ClockError('Missing QMP greeting')
        self.call('qmp_capabilities')

    def _read(self):
        line = self.stream.readline()
        if not line:
            raise ClockError('QMP disconnected')
        try:
            return json.loads(line)
        except (ValueError, TypeError) as exc:
            raise ClockError('Malformed QMP response') from exc

    def call(self, command, arguments=None):
        if self.invalid and command not in ('stop', 'quit'):
            raise ClockError('QMP clock invalidated by reset/shutdown')
        self.serial += 1
        request = {'execute': command, 'id': self.serial}
        if arguments is not None:
            request['arguments'] = arguments
        self.stream.write((json.dumps(request) + '\n').encode())
        self.stream.flush()
        while True:
            response = self._read()
            if response.get('event') in ('RESET', 'SHUTDOWN', 'GUEST_PANICKED'):
                self.invalid = True
                raise ClockError('QMP lifecycle event invalidated clock: ' + response['event'])
            if response.get('id') != self.serial:
                continue
            if 'error' in response:
                raise ClockError('QMP failure: ' + str(response['error']))
            return response.get('return')

class DiagnosticTimerClock:
    def __init__(self, qmp, *, opt_in=False, channel=5):
        if not opt_in:
            raise ClockError('Explicit diagnostic instrumentation opt-in required')
        if channel not in range(6):
            raise ClockError('Invalid timer channel')
        self.qmp = qmp
        self.base = BASE + channel * 0x20
        self.prepared = False
        self.armed = False
        self.failed = False
        self.origin = self.previous = None

    def _fail(self, reason):
        self.failed = True
        raise ClockError(reason)

    def _words(self, address, count):
        if self.failed:
            raise ClockError('Diagnostic clock previously failed')
        try:
            value = self.qmp.call('human-monitor-command', {
                'command-line': f'xp /{count}wx 0x{address:x}'})
            words = []
            expected = address
            for line in value.splitlines():
                match = re.fullmatch(r'([0-9a-fA-F]+):((?:\s+0x[0-9a-fA-F]{8})+)\s*', line)
                if not match or int(match[1], 16) != expected:
                    self._fail('Malformed or misaddressed HMP read')
                part = [int(x, 16) for x in match[2].split()]
                words.extend(part)
                expected += 4 * len(part)
            if len(words) != count:
                self._fail('Incomplete HMP timer read')
            return words
        except ClockError:
            self.failed = True
            raise
        except Exception as exc:
            self._fail('Timer observation failed: ' + str(exc))

    def bootstrap_commands(self):
        """Call while VM stopped; return guest commands, never execute them here.

        Caller must ensure offline shell, no native apps, and exclusive console.
        Resume only to execute commands, wait for marker, then stop and arm.
        """
        if self.prepared or self.armed:
            self._fail('Fixture bootstrap may only occur once')
        if self.qmp.call('query-status').get('running') is not False:
            self._fail('Stop QEMU before inspecting unused timer bank')
        if any(self._words(BASE, 48)):
            self._fail('Secure timer bank is not pristine/unused')
        self.prepared = True
        b = self.base
        operations = [(b + 16, 0), (b, 0xffffffff),
                      (b + 4, 0xffffffff), (b + 16, 1)]
        return ' && '.join(f'/bin/busybox devmem 0x{a:08x} 32 0x{v:08x}'
                           for a, v in operations) + ' && echo DIAGNOSTIC_TIMER_READY\n'

    def _invariants(self):
        low, high = self._words(self.base, 2)
        control, = self._words(self.base + 16, 1)
        if low != 0xffffffff or high != 0xffffffff or control != 1:
            self._fail('Diagnostic timer load/control modified')

    def _counter(self):
        self._invariants()
        for _ in range(4):
            high1, = self._words(self.base + 12, 1)
            low, = self._words(self.base + 8, 1)
            high2, = self._words(self.base + 12, 1)
            if high1 == high2:
                self._invariants()
                return (high1 << 32) | low
        self._fail('Unable to read coherent timer counter')

    def arm(self):
        """After successful guest bootstrap and QMP stop, establish relative epoch."""
        if not self.prepared or self.armed:
            self._fail('Invalid fixture arm lifecycle')
        if self.qmp.call('query-status').get('running') is not False:
            self._fail('Stop QEMU before establishing diagnostic epoch')
        self.origin = self.previous = self._counter()
        self.armed = True
        return 0

    def now(self, *, require_progress=False):
        if not self.armed:
            self._fail('Fixture not armed')
        current = self._counter()
        if current > self.previous:
            self._fail('Counter reversed: timer reprogram/reset/wrap detected')
        if require_progress and current == self.previous:
            self._fail('Diagnostic timer stale while progress required')
        self.previous = current
        return (self.origin - current) * 1000000000 // HZ

class DiagnosticQMP(QMPStream):
    """QMP(path) compatible adapter. Bootstrap before passing to coordinator.

    Unix socket use is a deployment choice; QMPStream supports stdio too.
    """
    def __init__(self, path, *, opt_in=False, timeout=3):
        import socket
        if not opt_in:
            raise ClockError('Explicit diagnostic instrumentation opt-in required')
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(timeout)
        try:
            self.socket.connect(str(path))
            super().__init__(self.socket.makefile('rwb', buffering=0))
            self.clock = DiagnosticTimerClock(self, opt_in=True)
        except Exception:
            self.socket.close()
            raise

    @classmethod
    def from_pipes(cls, base, *, opt_in=False, timeout=3):
        return DiagnosticQMPPipes.from_pipes(base, opt_in=opt_in, timeout=timeout)

    def now(self):
        return self.clock.now()

    def close(self):
        self.stream.close()
        self.socket.close()


def bootstrap_fixture(qmp, clock, exchange, offline_banner, *, timeout=10):
    """Bounded guest bootstrap BEFORE native app commands or clock coordination.

    qmp/clock must share one exclusive connection. exchange(command, marker,
    timeout) sends to exclusive guest console and waits for a standalone marker
    output line (not input echo), returning the observed text. Caller obtains
    offline_banner from this boot, before queuing any other guest commands.
    On failure we pause QEMU and raise; caller must not launch native apps.
    Returns initial relative nanoseconds (zero).
    """
    if 'original vendor startup has not been run' not in offline_banner:
        raise ClockError('Current boot lacks verified offline-shell banner')
    try:
        qmp.call('cont')
        # Keep names out of command text so console echo cannot cause false hits.
        proof = exchange('/bin/busybox ps; echo DIAGNOSTIC_PREAPP_PROOF\n',
                         'DIAGNOSTIC_PREAPP_PROOF', timeout)
        if re.search(r'\bavata_(?:main|ui)\b', proof):
            raise ClockError('Native applications already running')
        if not re.search(r'\bPID\s+USER\b', proof):
            raise ClockError('Guest process listing missing')
        qmp.call('stop')
        command = clock.bootstrap_commands()
        qmp.call('cont')
        exchange(command, 'DIAGNOSTIC_TIMER_READY', timeout)
        qmp.call('stop')
        return clock.arm()
    except Exception:
        clock.failed = True
        try:
            qmp.call('stop')
        except Exception:
            pass
        raise

class StreamPair:
    """Adapt separate binary read/write streams, e.g. QEMU QMP stdio pipes."""
    def __init__(self, reader, writer, timeout=3):
        self.reader, self.writer = reader, writer
        self.timeout = timeout
        self.buffer = bytearray()
    def readline(self):
        import os
        import select
        import time
        deadline = time.monotonic() + self.timeout
        while b'\n' not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.reader], [], [], remaining)[0]:
                raise ClockError('QMP pipe read timeout')
            data = os.read(self.reader.fileno(), 65536)
            if not data:
                raise ClockError('QMP pipe disconnected')
            self.buffer.extend(data)
            if len(self.buffer) > 1048576:
                raise ClockError('Oversized QMP pipe response')
        end = self.buffer.index(b'\n') + 1
        line = bytes(self.buffer[:end])
        del self.buffer[:end]
        return line
    def write(self, data):
        return self.writer.write(data)
    def flush(self):
        return self.writer.flush()
    def close(self):
        self.reader.close()
        self.writer.close()


class DiagnosticQMPPipes(QMPStream):
    """Primary socket-free adapter for QMP stdio or caller-owned FIFO streams."""
    def __init__(self, reader, writer, *, opt_in=False, timeout=3):
        if not opt_in:
            raise ClockError('Explicit diagnostic instrumentation opt-in required')
        super().__init__(StreamPair(reader, writer, timeout))
        self.clock = DiagnosticTimerClock(self, opt_in=True)
    def now(self):
        return self.clock.now()
    def close(self):
        self.stream.close()


    @classmethod
    def from_pipes(cls, base, *, opt_in=False, timeout=3):
        """Open existing base.out for responses and base.in for commands.

        Caller creates both FIFOs and launches QEMU with `-qmp pipe:<base>`.
        This is explicit IPC selection, never fallback from a failed socket.
        """
        import os
        import stat
        if not opt_in:
            raise ClockError('Explicit diagnostic instrumentation opt-in required')
        paths = [str(base) + '.out', str(base) + '.in']
        if not all(stat.S_ISFIFO(os.stat(path).st_mode) for path in paths):
            raise ClockError('QMP pipe endpoints must be existing FIFOs')
        opened = []
        try:
            for path in paths:
                fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
                if not stat.S_ISFIFO(os.fstat(fd).st_mode):
                    os.close(fd)
                    raise ClockError('QMP endpoint changed during open')
                opened.append(os.fdopen(fd, 'r+b', buffering=0))
            return cls(opened[0], opened[1], opt_in=True, timeout=timeout)
        except Exception:
            for stream in opened:
                stream.close()
            raise
