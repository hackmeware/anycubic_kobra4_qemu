#!/usr/bin/env python3
"""New read-only sensor30 protocol boundary. Builders are never executed here.

The only request bytes exposed by this module are empty PrinterState and
GetStatus to guest 127.0.0.1:50051. This is a new observation closure, not a
repair, replacement, or relaxation of the historical thermal controller gate.
"""
if not __debug__:
    raise SystemExit('Sensor30 observer refuses optimized Python before imports or I/O')

import ast
import hashlib
import importlib.util
import pathlib
import re
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[3]
HELPER_PINS = {
    'rv1106-at32-link/experimental/stream-end-probe/make_probe.py': 'db8c6a6a22df8c972e2b662f5dc3e18b93094f2b0dc7fcba185c680ddae6b91e',
    'printer-shared-mcu/experimental/synthetic-calibration-thermal/native-controller/status_snapshot.py': '6bc896a4fb083e477df998db01fb7b89e9f6b2e2c3f1c1d67b73d56f870ccaf5',
    'printer-shared-mcu/experimental/synthetic-calibration-thermal/native-controller/schema-temperature/temperature_schema.py': '549595d7d0c5d5d114b8ddf22c796f723e83fef4afb25a41fc92aa1f64f1dbc7',
}
METHODS = ('PrinterState', 'GetStatus')
MAX_CAPTURE = 1024 * 1024
MAX_MESSAGE = 65536
PREFACE = b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'
_HELPERS = None


def checked_method(method):
    if type(method) is not str or method not in METHODS:
        raise ValueError('Only empty PrinterState and GetStatus are permitted')
    return method


def frame(kind, flags, stream, payload=b''):
    return len(payload).to_bytes(3, 'big') + bytes((kind, flags)) + stream.to_bytes(4, 'big') + payload


def request_packet(method):
    checked_method(method)
    def string(value):
        return bytes((len(value),)) + value
    headers = (b'\x83\x86\x04' + string(b'/applink.AppLinkService/' + method.encode('ascii')) +
               b'\x01' + string(b'127.0.0.1:50051') + b'\x0f\x10' + string(b'application/grpc') +
               b'\x00' + string(b'te') + string(b'trailers'))
    return PREFACE + frame(4, 0, 0) + frame(1, 4, 1, headers) + frame(0, 1, 1, bytes(5))


def validate_request(method, packet):
    if type(packet) is not bytes or packet != request_packet(method):
        raise ValueError('Request differs from exact read-only empty request')
    return packet


def load_helpers():
    global _HELPERS
    if _HELPERS is not None:
        return _HELPERS
    # Check the entire transitive pure-builder closure BEFORE importing any of it.
    paths = []
    for relative, expected in HELPER_PINS.items():
        path = ROOT / relative
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Read-only helper identity mismatch: ' + relative)
        paths.append(path)
    modules = []
    for index, path in enumerate(paths):
        source = path.read_bytes()
        if hashlib.sha256(source).hexdigest() != list(HELPER_PINS.values())[index]:
            raise ValueError('Read-only helper changed before source execution')
        tree = ast.parse(source, filename=str(path))
        module = types.ModuleType('sensor30_pure_helper_' + str(index))
        module.__file__ = str(path)
        if index == 1:
            # This pinned file has a top-level spec/module/exec import of the base
            # helper. Replace only those exact assignments/call with the already
            # verified source module, so no .pyc can enter the closure.
            removed = []
            kept = []
            for node in tree.body:
                name = node.targets[0].id if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) else None
                if name in ('spec', 'base') or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == 'spec.loader.exec_module'):
                    removed.append(node)
                else:
                    kept.append(node)
            if len(removed) != 3:
                raise ValueError('Unexpected snapshot helper import structure')
            tree.body = kept
            module.base = modules[0]
        exec(compile(tree, str(path), 'exec'), module.__dict__)
        modules.append(module)
    for path, expected in zip(paths, HELPER_PINS.values()):
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Read-only helper changed during import')
    _HELPERS = tuple(modules)
    return _HELPERS


def build_client(method, packet):
    validate_request(method, packet)
    base, snapshot, _ = load_helpers()
    # No generic generator CLI, caller-provided ELF, arbitrary method, target,
    # host, port, request payload, or shell command is reachable from this API.
    elf = base.build(packet) if method == 'PrinterState' else snapshot.build_snapshot(packet)
    if base.extract_packet(elf) != packet or elf.count(PREFACE) != 1:
        raise ValueError('Generated client request identity mismatch')
    return elf


def markers(token, method):
    checked_method(method)
    if type(token) is not str or re.fullmatch('[a-f0-9]{20}', token) is None:
        raise ValueError('Invalid unique marker token')
    prefix = 'AMB_' + token + ('_P' if method == 'PrinterState' else '_S')
    return {key: prefix + '_' + suffix for key, suffix in
            (('begin', 'B'), ('end', 'E'), ('raw_begin', 'RB'), ('raw_end', 'RE'), ('exit', 'X'))}


def _marker_setup(prefix):
    # The complete prefix is absent from shell input, including wrapped echo.
    if type(prefix) is not str or re.fullmatch(
            r'AMB_[a-f0-9]{20}_(?:C|P|S|F|L(?:[1-9]|1[0-9]|20))', prefix) is None:
        raise ValueError('Invalid fixed marker prefix')
    return "AMBIENT_MARKER=$(printf '" + ''.join('\\%03o' % byte for byte in prefix.encode('ascii')) + "')"


def _marker_line(suffix):
    if type(suffix) is not str or suffix not in ('B', 'E', 'RB', 'RE', 'X'):
        raise ValueError('Invalid fixed marker suffix')
    literal = '_' + suffix + ('=' if suffix == 'X' else '')
    encoded = ''.join('\\%03o' % byte for byte in literal.encode('ascii'))
    # %s does not interpret the fixed prefix as a format string. Encode every
    # remaining literal byte, and retain the captured status as a separate arg.
    return ("printf '%s" + encoded + ('%s' if suffix == 'X' else '') +
            "\\012' \"$AMBIENT_MARKER\"" + (' "$AMBIENT_EXIT"' if suffix == 'X' else ''))


def shell_check_expected(token):
    markers(token, 'PrinterState')  # Preserve the exact existing token validation.
    prefix = 'AMB_' + token + '_C'
    return '\n'.join((prefix + '_B', prefix + '_X=37', prefix + '_RB',
                      'SHELL_BUILTINS_ONLY', prefix + '_RE', prefix + '_E')) + '\n'


def shell_check_command_batch(token):
    markers(token, 'PrinterState')
    suffix = [_marker_setup('AMB_' + token + '_C'), _marker_line('B'),
              '(exit 37)', 'AMBIENT_EXIT=$?', _marker_line('X'), _marker_line('RB'),
              "printf '%s\\n' 'SHELL_BUILTINS_ONLY'", _marker_line('RE'), _marker_line('E')]
    line = '; '.join(suffix)
    if len(line) > 768:
        raise ValueError('Compound capture suffix exceeds reviewed TTY bound')
    return line + '\n'


def verify_shell_check(text, token):
    expected = shell_check_expected(token)
    prefix = 'AMB_' + token + '_C'
    body = bounded_region(text, prefix + '_B', prefix + '_E')
    if body is None:
        return None
    normalized = text.replace('\r\n', '\n')
    # Check all probe-prefixed lines, including outside the capture;
    # neither extra/unknown markers nor fabricated earlier fragments can pass.
    actual_markers = re.findall(r'(?m)^' + re.escape(prefix) + r'[^\n]*(?:\n|$)', normalized)
    expected_markers = [line + '\n' for line in expected.splitlines() if line.startswith(prefix + '_')]
    if actual_markers != expected_markers or body.replace('\r\n', '\n') != expected.split('\n', 1)[1].rsplit(prefix + '_E\n', 1)[0]:
        raise ValueError('Guest shell builtin marker compatibility failed')
    return {'verified': True, 'scope': 'guest-shell-builtins-only', 'exit_status': 37}


def log_command_batch(token, label):
    markers(token, 'PrinterState')  # Reuse the exact existing token validation.
    if type(label) is not str or re.fullmatch(r'F|L(?:[1-9]|1[0-9]|20)', label) is None:
        raise ValueError('Only the fixed finite log batches are permitted')
    suffix = [_marker_setup('AMB_' + token + '_' + label), _marker_line('B'),
              'tail -100 /data/main.stdout', 'tail -100 /data/logs/avata_main.log', _marker_line('E')]
    line = '; '.join(suffix)
    if len(line) > 768:
        raise ValueError('Compound capture suffix exceeds reviewed TTY bound')
    return line + '\n'


def command_batch(method, token, elf):
    """Exact code identity + exact shell suffix; uploads precede capture.

    The suffix is one input line. Every marker prefix/suffix byte is emitted
    from octal printf escapes, never a literal marker in echoed shell input.
    """
    if elf != build_client(method, request_packet(method)):
        raise ValueError('Unapproved client substitution')
    mark = markers(token, method)
    path = '/tmp/amb_' + token + ('_p' if method == 'PrinterState' else '_s')
    lines = ["printf '" + ''.join('\\%03o' % byte for byte in elf[off:off + 64]) + "' " +
             ('>' if off == 0 else '>>') + ' ' + path for off in range(0, len(elf), 64)]
    suffix = [f'chmod +x {path}', _marker_setup(mark['begin'][:-2]), _marker_line('B'), 'cat /proc/uptime',
              f'timeout -t 5 {path} > {path}.out', 'AMBIENT_EXIT=$?',
              _marker_line('X'), _marker_line('RB'), f'od -v -b {path}.out', _marker_line('RE'),
              'cat /proc/uptime', _marker_line('E')]
    line = '; '.join(suffix)
    if len(line) > 768:
        raise ValueError('Compound capture suffix exceeds reviewed TTY bound')
    return '\n'.join(lines + [line]) + '\n'


def validate_commands(method, token, elf, commands):
    if type(commands) is not str or commands != command_batch(method, token, elf):
        raise ValueError('Console command substitution is prohibited')
    return commands


def decode_headers(block):
    """Strict raw-string HPACK subset adapted from the unchanged Ready parser."""
    position, headers = 0, []
    static = {8: (b':status', b'200'), 9: (b':status', b'204'), 10: (b':status', b'206'),
              11: (b':status', b'304'), 12: (b':status', b'400'), 13: (b':status', b'404'),
              14: (b':status', b'500'), 31: (b'content-type', b'')}
    def integer(bits):
        nonlocal position
        if position >= len(block):
            raise ValueError('Truncated HPACK integer')
        mask = (1 << bits) - 1
        value = block[position] & mask
        position += 1
        if value < mask:
            return value
        for shift in range(0, 28, 7):
            if position >= len(block):
                raise ValueError('Truncated HPACK integer')
            byte = block[position]; position += 1
            value += (byte & 127) << shift
            if not byte & 128:
                return value
        raise ValueError('Oversized HPACK integer')
    def string():
        nonlocal position
        if position >= len(block) or block[position] & 128:
            raise ValueError('Missing or unsupported Huffman HPACK string')
        size = integer(7)
        value = block[position:position + size]; position += size
        if len(value) != size:
            raise ValueError('Truncated HPACK string')
        return value
    while position < len(block):
        first = block[position]
        if first & 128:
            index = integer(7)
            if index not in static:
                raise ValueError('Unsupported indexed HPACK header')
            name, value = static[index]
        elif first & 32 and not first & 64:
            if headers or integer(5) > 4096:
                raise ValueError('Invalid HPACK table-size update')
            continue
        else:
            index = integer(6 if first & 64 else 4)
            if index and index not in static:
                raise ValueError('Unsupported HPACK name index')
            name = static[index][0] if index else string()
            value = string()
        if not name or name.lower() != name or any(b < 33 or b > 126 for b in name):
            raise ValueError('Invalid header name')
        headers.append((name, value))
    return headers


def response_messages(data, method):
    """Complete captured HTTP/2 boundary, exact cardinality, explicit outcomes."""
    checked_method(method)
    if type(data) is not bytes or not 1 <= len(data) <= MAX_CAPTURE:
        raise ValueError('Invalid capture size/type')
    pos, continuation, header_end, ended = 0, False, False, False
    block, body, headersets, messages = bytearray(), bytearray(), [], []
    while pos < len(data):
        if ended or (method == 'GetStatus' and len(messages) == 2) or len(data) - pos < 9:
            raise ValueError('Trailing or incomplete HTTP/2 frame')
        size = int.from_bytes(data[pos:pos + 3], 'big')
        kind, flags = data[pos + 3:pos + 5]
        rawstream = int.from_bytes(data[pos + 5:pos + 9], 'big')
        stream = rawstream & 0x7fffffff
        pos += 9
        payload = data[pos:pos + size]; pos += size
        if size > 16384 or len(payload) != size or rawstream != stream:
            raise ValueError('Oversized, truncated or reserved-bit frame')
        if continuation and (kind != 9 or stream != 1):
            raise ValueError('Interrupted header continuation')
        if kind in (0, 1, 9):
            allowed = {0: 9, 1: 45, 9: 4}[kind]
            if stream != 1 or flags & ~allowed:
                raise ValueError('Unexpected response stream/flags')
            if method == 'GetStatus' and flags & 1:
                raise ValueError('Unexpected END_STREAM; not a locally canceled snapshot')
            if kind in (0, 1) and flags & 8:
                if not payload or payload[0] >= len(payload):
                    raise ValueError('Invalid padding')
                payload = payload[1:len(payload) - payload[0]]
            if kind == 0:
                if len(headersets) != 1 or continuation or flags & 1:
                    raise ValueError('DATA before headers or terminal DATA without gRPC trailers')
                body.extend(payload)
                while len(body) >= 5:
                    length = int.from_bytes(body[1:5], 'big')
                    if body[0] or length > MAX_MESSAGE:
                        raise ValueError('Compressed or oversized gRPC message')
                    if len(body) < 5 + length:
                        break
                    messages.append(bytes(body[5:5 + length])); del body[:5 + length]
                    maximum = 1 if method == 'PrinterState' else 2
                    if len(messages) > maximum or len(messages) == maximum and body:
                        raise ValueError('Extra or partial additional gRPC message')
            else:
                if kind == 1:
                    if continuation or len(headersets) >= 2 or method == 'GetStatus' and headersets:
                        raise ValueError('Repeated headers/server snapshot trailers')
                    if headersets and not flags & 1:
                        raise ValueError('Nonterminal second header block')
                    if flags & 32:
                        if len(payload) < 5 or int.from_bytes(payload[:4], 'big') & 0x7fffffff == stream:
                            raise ValueError('Invalid HEADERS priority')
                        payload = payload[5:]
                    header_end = bool(flags & 1)
                elif not continuation:
                    raise ValueError('Unexpected continuation')
                block.extend(payload)
                if len(block) > MAX_MESSAGE:
                    raise ValueError('Oversized header block')
                continuation = not bool(flags & 4)
                if not continuation:
                    headers = decode_headers(bytes(block)); block.clear()
                    headersets.append(headers)
                    if len(headersets) == 1:
                        if [v for k, v in headers if k == b':status'] != [b'200']:
                            raise ValueError('Non200/missing/ambiguous HTTP status')
                        if [v for k, v in headers if k == b'content-type'] != [b'application/grpc']:
                            raise ValueError('Missing/non-gRPC/ambiguous content-type')
                        if any(k in (b'grpc-status', b'grpc-message') for k, v in headers):
                            raise ValueError('Early gRPC error/trailers')
                        if any(k.startswith(b':') and k != b':status' for k, v in headers):
                            raise ValueError('Unexpected pseudoheader')
                    else:
                        if any(k.startswith(b':') or k == b'content-type' for k, v in headers):
                            raise ValueError('Invalid trailers')
                        if [v for k, v in headers if k == b'grpc-status'] != [b'0']:
                            raise ValueError('Missing/nonzero/ambiguous terminal gRPC status')
                        if any(k == b'grpc-message' and v for k, v in headers):
                            raise ValueError('Nonempty gRPC error message')
                    ended = header_end
        elif kind == 4:
            if stream or flags & ~1 or size % 6 or flags & 1 and size:
                raise ValueError('Malformed SETTINGS')
            for off in range(0, size, 6):
                key, value = int.from_bytes(payload[off:off + 2], 'big'), int.from_bytes(payload[off + 2:off + 6], 'big')
                if key == 2 or key == 4 and value > 0x7fffffff or key == 5 and not 16384 <= value <= 16777215:
                    raise ValueError('Invalid server SETTINGS value')
        elif kind == 6:
            if stream or size != 8 or flags & ~1:
                raise ValueError('Malformed PING')
        elif kind == 8:
            if stream not in (0, 1) or size != 4 or flags or not 0 < int.from_bytes(payload, 'big') <= 0x7fffffff:
                raise ValueError('Malformed WINDOW_UPDATE')
        elif kind == 2:
            if stream != 1 or size != 5 or flags or int.from_bytes(payload[:4], 'big') & 0x7fffffff == stream:
                raise ValueError('Malformed PRIORITY')
        else:
            raise ValueError('Reset/GOAWAY/push/unsupported response frame')
    if continuation or body or len(messages) != (1 if method == 'PrinterState' else 2):
        raise ValueError('Incomplete response messages')
    if method == 'PrinterState' and (not ended or len(headersets) != 2):
        raise ValueError('Missing successful terminal trailers')
    if method == 'GetStatus' and (ended or len(headersets) != 1):
        raise ValueError('Not a two-message streaming snapshot')
    return messages


def protobuf_fields(payload):
    """Pure strict wire decoder matching the separately pinned schema helper."""
    if type(payload) is not bytes or len(payload) > MAX_MESSAGE:
        raise ValueError('Invalid protobuf payload')
    position = 0
    def varint():
        nonlocal position
        value, start = 0, position
        for shift in range(0, 70, 7):
            if position == len(payload):
                raise ValueError('Truncated protobuf varint')
            byte = payload[position]; position += 1
            if shift == 63 and byte > 1:
                raise ValueError('Oversized protobuf varint')
            value |= (byte & 127) << shift
            if byte < 128:
                if position - start > 1 and byte == 0:
                    raise ValueError('Noncanonical protobuf varint')
                return value
        raise ValueError('Unterminated protobuf varint')
    while position < len(payload):
        tag = varint(); number, wire = tag >> 3, tag & 7
        if not 1 <= number <= 0x1fffffff:
            raise ValueError('Invalid protobuf field')
        if wire == 0:
            value = varint()
        elif wire in (1, 2, 5):
            size = varint() if wire == 2 else (8 if wire == 1 else 4)
            value = payload[position:position + size]; position += size
            if len(value) != size:
                raise ValueError('Truncated protobuf field')
        else:
            raise ValueError('Unsupported protobuf wire type')
        yield number, wire, value


def selected_fields(payload, wanted, expected_wire, required=False):
    result = {}
    for number, wire, value in protobuf_fields(payload):
        if number in wanted:
            if wire != expected_wire or number in result:
                raise ValueError('Duplicate/wrong-wire protobuf field')
            result[number] = value
    if required and set(result) != set(wanted):
        raise ValueError('Missing required nested status')
    return result


def state_payload(payload):
    fields = {}
    for number, wire, value in protobuf_fields(payload):
        if number not in (1, 2, 3) or wire != 2 or number in fields:
            raise ValueError('Unexpected/duplicate PrinterState field')
        fields[number] = value
    if fields.get(1) or fields.get(2) != b'ready':
        raise ValueError('PrinterState error/not ready')
    return {'state': 'ready', 'state_message': fields.get(3, b'').decode('utf-8')}


def decode_status(payload):
    status = selected_fields(payload, (1,), 2, True)[1]
    heaters = selected_fields(status, (2, 3), 2, True)
    result = {}
    def int32(value):
        if value <= 0x7fffffff:
            return value
        if value >= 0xffffffff80000000:
            return value - (1 << 64)
        raise ValueError('Noncanonical signed int32')
    for heater, field in (('nozzle', 2), ('bed', 3)):
        values = selected_fields(heaters[field], (1, 2), 0)
        result[heater] = {'current': int32(values.get(1, 0)), 'target': int32(values.get(2, 0))}
    return result


def validate_sensor30(temperatures, *, selected):
    for heater in ('nozzle', 'bed'):
        reading = temperatures[heater]
        if type(reading['target']) is not int or reading['target'] != 0:
            raise ValueError('Nonzero or invalid native target')
        current = reading['current']
        # A first all-default scalar is retained, never selected or rewritten.
        lower, upper = (29, 31) if heater == 'nozzle' else (23, 27)
        if type(current) is not int or not (lower <= current <= upper or not selected and current == 0):
            raise ValueError('Default-zero/nonsensor30 native temperature')


def read_od(text):
    data, final = bytearray(), None
    for line in text.splitlines():
        row = re.fullmatch(r'([0-7]{7,})[ \t]+((?:[0-7]{3}[ \t]*)+)', line)
        if row:
            if final is not None or int(row[1], 8) != len(data):
                raise ValueError('Noncontiguous or repeated raw dump')
            values = [int(value, 8) for value in row[2].split()]
            if len(values) > 16 or any(value > 255 for value in values):
                raise ValueError('Invalid octal row')
            data.extend(values)
            if len(data) > MAX_CAPTURE:
                raise ValueError('Capture limit')
        elif re.fullmatch('[0-7]{7,}', line):
            if final is not None:
                raise ValueError('Duplicate final offset')
            final = int(line, 8)
        else:
            raise ValueError('Unexpected text in raw dump')
    if not data or final != len(data):
        raise ValueError('Incomplete raw dump')
    return bytes(data)


def bounded_region(text, begin, end):
    starts = list(re.finditer(r'(?m)^' + re.escape(begin) + r'\r?\n', text))
    ends = list(re.finditer(r'(?m)^' + re.escape(end) + r'\r?\n', text))
    if len(starts) > 1 or len(ends) > 1 or ends and not starts:
        raise ValueError('Repeated/reversed capture markers')
    if not starts or not ends:
        return None
    if ends[0].start() <= starts[0].end():
        raise ValueError('Reversed/empty capture')
    return text[starts[0].end():ends[0].start()]


def capture_transport(text, method, token):
    """Extract raw bytes/outcome before semantic validation, for failed evidence too."""
    mark = markers(token, method)
    body = bounded_region(text, mark['begin'], mark['end'])
    if body is None:
        return None
    lines = body.replace('\r\n', '\n').splitlines()
    expected_exit = 0 if method == 'PrinterState' else 20
    if (len(lines) < 7 or lines[1] != mark['exit'] + '=' + str(expected_exit) or
            lines[2] != mark['raw_begin'] or lines[-2] != mark['raw_end']):
        raise ValueError('Missing/ambiguous/nonzero or incorrect transport outcome/capture structure')
    uptimes = []
    for line in (lines[0], lines[-1]):
        match = re.fullmatch(r'([0-9]+\.[0-9]{2}) ([0-9]+\.[0-9]{2})', line)
        if not match:
            raise ValueError('Invalid guest uptime boundary')
        uptimes.append(match[1])
    if float(uptimes[1]) < float(uptimes[0]):
        raise ValueError('Guest uptime moved backwards')
    wire = read_od('\n'.join(lines[3:-2]))
    return wire, uptimes, expected_exit


def verify_capture(text, method, token):
    extracted = capture_transport(text, method, token)
    if extracted is None:
        return None
    wire, uptimes, expected_exit = extracted
    payloads = response_messages(wire, method)
    result = {'client_exit_status': expected_exit, 'transport_exit_status': expected_exit,
              'wire_sha256': hashlib.sha256(wire).hexdigest(), 'wire_hex': wire.hex(),
              'guest_uptime_seconds': uptimes, 'guest_uptime_is_sensor_timestamp': False,
              'physical_completion_proven': False}
    if method == 'PrinterState':
        result.update(api_response=state_payload(payloads[0]), protobuf_hex=payloads[0].hex(),
                      terminal_grpc_status=0)
    else:
        observations = []
        for sequence, payload in enumerate(payloads, 1):
            temperatures = decode_status(payload)
            validate_sensor30(temperatures, selected=sequence == 2)
            observations.append({'sequence': sequence, 'protobuf_hex': payload.hex(), 'temperatures': temperatures})
        result.update(messages=observations, selected_sequence=2, selected_temperatures=observations[1]['temperatures'],
                      local_cancel_frame_sent=True, local_socket_shutdown_and_close=True,
                      terminal_grpc_status=None, unary_completion=False,
                      remote_cancel_acknowledged=False, native_sensor_acquisition_timestamp=None,
                      sample_freshness_scope='New subscription; second message by sequence; acquisition age unknown')
    return result
