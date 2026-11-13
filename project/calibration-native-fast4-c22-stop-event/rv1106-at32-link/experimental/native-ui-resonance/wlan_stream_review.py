"""Offline future-profile overlay. No emulator, actuator or process operations.

Pending is an admission veto, never an accepted auxiliary classification.
Call with the WHOLE monotonically growing bounded console, not log chunks.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import math
import os
import re
import stat
import time

WLAN_MESSAGES = frozenset((
    "exec command 'wpa_cli -i wlan0 reconnect' failed, ",
    "exec command 'wpa_cli -i wlan0 status' failed, ",
    "exec command 'wpa_cli -i wlan0 scan' failed, "))
WLAN_MISSING_CONTROL = 'Failed to connect to non-global ctrl_ifname: wlan0  error: No such file or directory'
WLAN_WORD = re.compile(r'(?i)\b(?:wpa_cli|ctrl_ifname)\b')
ERROR_WORD = re.compile(r'(?i)\b(?:error|failed|failure|fault|timeout|invalid)\b')
MAX_CONSOLE = 32 * 1024 * 1024
MAX_LINE = 16384
MAX_PENDING = 8
MAX_WLAN_OCCURRENCES = 4096
PENDING_HOST_SECONDS = 5.0
PENDING_SOURCE_NS = 250_000_000
LOCK_HOST_SECONDS = 1.0
CONTRACT = 'exact-wlan-stream-v1'


# Transport framing only: exact shell prompt followed by a complete native log.
# Numeric and native function source fields are both legitimate log syntax.
PROMPT_NATIVE = re.compile(r'^/ # (\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\] \[(?:trace|debug|info|warning|warn|error|critical|fatal)\] \[[^\]\r\n]+\] [^\r\n]*)$')


def native_text(text, base):
    """Review view only; never a replacement for raw admission receipt bytes."""
    lines = []
    for raw in text.splitlines(keepends=True):
        clean = base.ANSI.sub('', raw)
        if clean.endswith('\n'):
            body = clean[:-1].removesuffix('\r')
            match = PROMPT_NATIVE.fullmatch(body)
            if match:
                clean = match[1] + '\n'
        lines.append(clean)
    return ''.join(lines)


def permitted_fault_prefix(tail, base, ready_stamp):
    """Provisional only, never classification: exact raw permitted-line prefix.

    Formatting alternatives are explicit observed terminal grammar, including
    partial final reset escapes. No arbitrary ANSI suffix is discarded here.
    """
    for prompt in ('', '/ # '):
        for color in ('', '\x1b[31m', '\x1b[31m\x1b[1m'):
            prefix = prompt + color
            if not tail.startswith(prefix):
                continue
            body = tail[len(prefix):]
            stamp = re.match(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\] ', body)
            if not stamp:
                continue
            messages = [(211, base.VIDEO)] + [(129, value) for value in WLAN_MESSAGES]
            if ready_stamp is None or stamp[1] < ready_stamp:
                messages += [(source, message) for message, source in base.AUXILIARY.items()]
            for source, message in messages:
                line = prefix + '[' + stamp[1] + '] [error] [' + str(source) + '] ' + message
                for ending in ('\n', '\r\n', '\x1b[m\n', '\x1b[m\r\n'):
                    if (line + ending).startswith(tail):
                        return True
    return (WLAN_MISSING_CONTROL + '\n').startswith(tail) or (WLAN_MISSING_CONTROL + '\r\n').startswith(tail)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class UiNativeReview:
    def __init__(self, base):
        self.base = base
        self.strict = base.NativeReview()
        self.occurrences = []
        self.pending = {}
        self.failure = None
        self.last_host = None
        self.last_source = None
        self.console_bytes = 0
        self.console_sha256 = digest(b'')
        self.partial = False
        self.provisional_tail_fault = False
        self.seen = False
        self.finalized = False

    @property
    def admission_clear(self):
        return (self.seen and not self.failure and not self.pending and
                not self.partial and not self.finalized)

    @property
    def native_readiness_verified(self):
        """Complete native Ready evidence, NOT permission for another down.

        An incomplete tail remains unclassified and admission-blocking. This
        flag only supports reviewing a complete request after accepted intent.
        """
        return bool(self.seen and self.strict.ready_stamp is not None and
                    not self.failure and not self.pending and not self.finalized and
                    not self.provisional_tail_fault)

    def require_clear(self):
        if not self.admission_clear:
            raise ValueError('Native console review blocks new UI/PID admission')

    def summary(self):
        return {'contract': CONTRACT, 'admission_clear': self.admission_clear,
                'native_readiness_verified': self.native_readiness_verified,
                'pending_count': len(self.pending),
                'pending': [dict(value) for value in self.pending.values()],
                'provisional_tail_fault': self.provisional_tail_fault,
                'incomplete_tail': self.partial, 'failure': self.failure,
                'finalized': self.finalized,
                'console_bytes': self.console_bytes,
                'console_sha256': self.console_sha256,
                'observed_host_monotonic': self.last_host,
                'observed_source_ns': self.last_source}

    def observe(self, raw, *, host_now, source_ns, final=False):
        if self.failure is not None:
            raise ValueError('Latched native console review failure: ' + self.failure)
        try:
            return self._observe(raw, host_now=host_now, source_ns=source_ns, final=final)
        except Exception as error:
            self.failure = type(error).__name__ + ': ' + str(error)
            raise

    def _observe(self, raw, *, host_now, source_ns, final):
        if self.finalized:
            raise ValueError('Native console review already finalized')
        if type(raw) is not bytes or len(raw) > MAX_CONSOLE:
            raise ValueError('Expected bounded raw console bytes')
        if (type(host_now) not in (float, int) or not math.isfinite(host_now) or
                host_now < 0 or self.last_host is not None and host_now < self.last_host):
            raise ValueError('Invalid/backward host monotonic clock')
        if (source_ns is not None and (type(source_ns) is not int or source_ns < 0) or
                self.last_source is not None and (source_ns is None or source_ns < self.last_source)):
            raise ValueError('Invalid/backward/missing confirmed source clock')
        if len(raw) < self.console_bytes or digest(raw[:self.console_bytes]) != self.console_sha256:
            raise ValueError('Console truncated/rewritten; no cross-stream carryover')
        self.last_host, self.last_source = host_now, source_ns
        # Deadlines are checked BEFORE looking for new corroboration. A late
        # duplicate cannot revive an expired pending event, including at final.
        for item in self.pending.values():
            if host_now >= item['host_deadline'] or source_ns >= item['source_deadline_ns']:
                raise TimeoutError('Uncorroborated WLAN deadline expired: ' + item['line'])
        self.console_bytes, self.console_sha256 = len(raw), digest(raw)
        self.seen = True
        parts = raw.split(b'\n')
        self.partial = bool(parts[-1])
        if any(len(part) > MAX_LINE for part in parts):
            raise ValueError('Console line storage bound exceeded')
        complete = parts[:-1]
        contexts, events = {}, []
        checked = []
        previous = None
        # Only exact complete native lines and an immediately adjacent exact
        # diagnostic pair establish corroboration. Full scan handles reversed
        # duplicate order in one read; persisted pending handles later reads.
        for number, part in enumerate(complete, 1):
            raw_line = part.decode('utf-8', errors='replace').removesuffix('\r')
            line = native_text(raw_line + '\n', self.base).rstrip('\r\n')
            native = self.base.LOG_LINE.fullmatch(line)
            known = (native and native[2] == 'error' and native[3] == '129' and
                     native[4] in WLAN_MESSAGES)
            if known:
                if len(events) >= MAX_WLAN_OCCURRENCES:
                    raise ValueError('WLAN occurrence storage bound exceeded')
                events.append({'line': line, 'raw_line': raw_line,
                               'line_number_1based': number})
                if previous and previous['line'] == WLAN_MISSING_CONTROL:
                    contexts.setdefault(line, previous)
                checked.append('\n')
            else:
                if (line != WLAN_MISSING_CONTROL and WLAN_WORD.search(line) and
                        ERROR_WORD.search(line)):
                    raise ValueError('Unknown WLAN command/control fault: ' + line)
                checked.append(line + '\n')
            previous = {'line': line, 'raw': raw_line, 'number': number}
        # Continue all original strict checks on every call, even while pending.
        # No thermal/LIS/resource guard is inside or disabled by this wrapper.
        tail = parts[-1].decode('utf-8', errors='replace')
        # Strict complete evidence is checked before any provisional deferral.
        ready = self.strict.observe(''.join(checked) + tail, final=final)
        self.provisional_tail_fault = False
        if tail:
            clean_tail = self.base.ANSI.sub('', tail)
            fault = re.search(r'\[(?:error|critical|fatal)\]|\b(shutdown|fault|emergency)\b|\b(?:MCU|sensor)\b.*\b(error|failed|timeout)\b', clean_tail, re.I)
            wlan_fault = WLAN_WORD.search(clean_tail) and ERROR_WORD.search(clean_tail)
            if fault or wlan_fault:
                if permitted_fault_prefix(tail, self.base, self.strict.ready_stamp):
                    self.provisional_tail_fault = True
                else:
                    raise ValueError('Unterminated native/WLAN fault evidence: ' + clean_tail)
        classified = []
        unresolved = {}
        for event in events:
            line = event['line']
            context = contexts.get(line)
            if context is not None:
                classified.append({**event,
                    'classification': 'exact absent wlan0 control interface; corroborated native duplicate',
                    'startup_only': False,
                    'corroborating_line': context['line'],
                    'corroborating_raw_line': context['raw'],
                    'corroborating_line_number_1based': context['number']})
            elif line not in unresolved:
                if len(unresolved) >= MAX_PENDING:
                    raise ValueError('Pending WLAN event storage bound exceeded')
                if source_ns is None:
                    raise ValueError('Uncorroborated WLAN without confirmed source clock')
                unresolved[line] = self.pending.get(line) or {
                    **event, 'status': 'pending_not_accepted',
                    'first_host_monotonic': host_now, 'first_source_ns': source_ns,
                    'host_deadline': host_now + PENDING_HOST_SECONDS,
                    'source_deadline_ns': source_ns + PENDING_SOURCE_NS}
        self.pending = unresolved
        self.occurrences = self.strict.occurrences + classified
        if final:
            if self.pending:
                raise ValueError('Final uncorroborated WLAN command failure: ' + next(iter(self.pending)))
            if self.partial:
                raise ValueError('Unterminated final console evidence')
            self.finalized = True
        return bool(ready and not self.pending and not self.partial)


def require_report_clear(record, directory):
    """Final down-admission check, under admission_lock, against actual bytes.

    A newly appended/unreviewed suffix denies admission, even if the last saved
    thermal report was clear. Never used for cleanup pointer-up.
    """
    review = record.get('native_console_review', {})
    if (review.get('contract') != CONTRACT or review.get('admission_clear') is not True or
            type(review.get('pending_count')) is not int or review['pending_count'] != 0 or
            review.get('pending') != [] or review.get('incomplete_tail') is not False or
            review.get('failure') is not None or review.get('finalized') is not False):
        raise ValueError('Native console review blocks new UI/PID admission')
    count = review.get('console_bytes')
    sha = review.get('console_sha256')
    if (type(count) is not int or not 0 <= count <= MAX_CONSOLE or
            not isinstance(sha, str) or re.fullmatch('[a-f0-9]{64}', sha) is None):
        raise ValueError('Invalid console admission receipt')
    fd = os.open(directory / 'console.bin', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != count:
            raise ValueError('Console changed since reviewed UI admission receipt')
        chunks, remaining = [], count
        while remaining:
            chunk = os.read(fd, min(remaining, 1024 * 1024))
            if not chunk:
                raise ValueError('Console shortened during admission check')
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1) or digest(b''.join(chunks)) != sha:
            raise ValueError('Console changed since reviewed UI admission receipt')
    finally:
        os.close(fd)


@contextmanager
def admission_lock(directory, *, monotonic=time.monotonic, sleep=time.sleep):
    """Separate from the UI's long-lived control lock. Hold across down only.

    Observer holds this only across sample + report publication; lock contention
    has its own finite host deadline. No process/namespace controls are changed.
    """
    fd = os.open(directory / 'native-console-admission.lock',
                 os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('Admission lock is not a regular file')
        began = monotonic()
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                now = monotonic()
                if not math.isfinite(now) or not began <= now < began + LOCK_HOST_SECONDS:
                    raise TimeoutError('Native console admission lock deadline')
                sleep(min(.01, began + LOCK_HOST_SECONDS - now))
        yield
    finally:
        os.close(fd)
