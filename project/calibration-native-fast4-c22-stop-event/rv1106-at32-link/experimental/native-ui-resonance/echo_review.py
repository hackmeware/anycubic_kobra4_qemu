"""Pure, fail-closed recognizer for one precisely bound down-event transport.

No IO or event delivery. Native spans MUST independently pass the strict native
parser. A provisional match never grants admission or permits a new down event.
The caller must verify append-only file identity and all retained prefix hashes.
"""
import math
import struct

HOST_LIMIT = 2.0
SOURCE_LIMIT_NS = 250_000_000
PROMPT = b'/ # '
MAX_RAW_BYTES = 32 * 1024 * 1024
MAX_NATIVE_SPANS = 4096


def event_command(x, y):
    for value, maximum in ((x, 479), (y, 319)):
        if type(value) is not int or not 0 <= value <= maximum:
            raise ValueError('Coordinates must be integers within the 480x320 framebuffer')
    data = b''.join(struct.pack('<IIHHi', 0, 0, t, c, v)
                    for t, c, v in ((3, 0, x), (3, 1, y), (1, 330, 1), (0, 0, 0)))
    return ("printf '" + ''.join('\\%03o' % b for b in data)
            + "' > /tmp/touch-events").encode('ascii')


class BoundTouchEcho:
    def __init__(self, x, y, start_offset):
        if type(start_offset) is not int or start_offset < 0:
            raise ValueError('Invalid admission offset')
        command = event_command(x, y)
        raw = command + b'\r\n'
        rendered = (command[:76] + b'\r\r\n' + command[76:156]
                    + b'\r\r\n' + command[156:236] + b'\r\r\n'
                    + command[236:] + b'\r\n')
        self.forms = (raw + PROMPT, rendered + PROMPT,
                      raw + PROMPT + rendered + PROMPT)
        self.max_transport_bytes = max(map(len, self.forms))
        self.start_offset = start_offset
        self.first_host = self.first_source = None
        self.last_host = self.last_source = None
        self.failed = None

    @staticmethod
    def _result(status, native=(), transport=None, reason=None):
        return dict(status=status,
                    allow_incomplete_tail=status == 'known incomplete',
                    complete=status == 'complete known prompt',
                    native_spans=list(native), transport_span=transport,
                    reason=reason, admission_clear=False)

    def prefix_status(self, raw):
        """Stateless classification; never starts/resets deadlines.

        Coordinates are down-only. Offsets in the returned spans address raw.
        Unknown complete native lines are returned, NOT declared safe. A native
        parser must validate them even when status says 'complete known prompt'.
        """
        R = self._result
        if (not isinstance(raw, bytes) or len(raw) < self.start_offset
                or len(raw) > MAX_RAW_BYTES):
            return R('unknown partial', reason='Invalid/truncated raw prefix')
        pos = self.start_offset
        if pos and raw[pos-1:pos] != b'\n':
            return R('unknown partial', reason='Admission offset is not a new line')
        native = []
        # Only complete native lines may precede transport. A line beginning
        # with an expected transport introducer commits to that exact grammar.
        while pos < len(raw) and raw[pos:pos+1] not in (b'p', b'/'):
            end = raw.find(b'\n', pos)
            if end < 0:
                return R('unknown partial', native, reason='Unknown native tail')
            if len(native) >= MAX_NATIVE_SPANS:
                return R('unknown partial', native, reason='Native span limit exceeded')
            native.append((pos, end+1))
            pos = end+1
        if pos == len(raw):
            return R('no echo yet', native)
        tail = raw[pos:]
        # Prefer the longest exact form, so raw+prompt+redraw is not mistaken
        # for completed raw+prompt followed by native output.
        exact = [form for form in self.forms if tail.startswith(form)]
        prefixes = [form for form in self.forms if form.startswith(tail)]
        if prefixes and not exact:
            return R('known incomplete', native, (pos, len(raw)))
        if not exact:
            return R('unknown partial', native, reason='Transport mismatch/overflow')
        form = max(exact, key=len)
        end = pos + len(form)
        rest = raw[end:]
        # A shorter complete alternative may still be a prefix of the longer
        # raw+prompt+rendered form. Once redraw bytes arrive, demand all of it.
        longer = [f for f in self.forms if len(f) > len(form) and f.startswith(tail)]
        if rest and longer:
            return R('known incomplete', native, (pos, len(raw)))
        if rest:
            # No second command/prompt and no new partial line are transport.
            # Complete native records may immediately follow the exact prompt.
            # Expose their bytes unchanged to the caller's strict native parser.
            cursor = end
            while cursor < len(raw):
                nl = raw.find(b'\n', cursor)
                if nl < 0:
                    return R('unknown partial', native, (pos, end), 'Unknown trailing tail')
                line = raw[cursor:nl+1]
                if line.startswith((b'printf ', PROMPT)):
                    return R('unknown partial', native, (pos, end), 'Duplicate transport')
                if len(native) >= MAX_NATIVE_SPANS:
                    return R('unknown partial', native, (pos, end), 'Native span limit exceeded')
                native.append((cursor, nl+1))
                cursor = nl+1
        return R('complete known prompt', native, (pos, end))

    def observe(self, raw, host_now, source_ns):
        """Advance clocks and classify. Errors latch; deadlines never reset.

        At exactly either deadline, completion is too late. Clock validation
        also applies to duplicate observations and observations before an echo.
        """
        if self.failed is not None:
            return self._result('unknown partial', reason=self.failed)
        def fail(reason):
            self.failed = reason
            return self._result('unknown partial', reason=reason)
        try:
            finite_host = type(host_now) in (float, int) and math.isfinite(host_now)
        except (OverflowError, ValueError, TypeError):
            finite_host = False
        if (not finite_host
                or host_now < 0 or type(source_ns) is not int or source_ns < 0):
            return fail('Invalid clock')
        if ((self.last_host is not None and host_now < self.last_host)
                or (self.last_source is not None and source_ns < self.last_source)):
            return fail('Clock moved backwards')
        self.last_host, self.last_source = host_now, source_ns
        result = self.prefix_status(raw)
        if result['status'] == 'unknown partial':
            return fail(result['reason'])
        if self.first_host is not None and (
                host_now-self.first_host >= HOST_LIMIT
                or source_ns-self.first_source >= SOURCE_LIMIT_NS):
            # An already completed transport does not expire afterwards.
            if not getattr(self, '_finished', False) or result['status'] == 'known incomplete':
                return fail('Transport completion deadline expired')
        if result['status'] == 'known incomplete':
            if self.first_host is None:
                self.first_host, self.first_source = host_now, source_ns
            self._finished = False
        elif result['complete']:
            self._finished = True
        return result
