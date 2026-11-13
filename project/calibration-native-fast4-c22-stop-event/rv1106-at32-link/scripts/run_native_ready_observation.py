#!/usr/bin/env python3
"""Bounded startup observation and exactly one read-only PrinterState request.

No homing, heater or print RPCs. Fail closed, request normal final export, and
never retry an uncertain queue/write or a failed generation/response.
"""
import argparse
import json
import os
import pathlib
import re
import secrets
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
BEGIN, END = 'READY_ONLY_RPC_BEGIN', 'READY_ONLY_RPC_END'
RAW_BEGIN, RAW_END = 'READY_RAW_BEGIN', 'READY_RAW_END'
MAX_CAPTURE = 1024 * 1024


def marker_matches(text, marker):
    return list(re.finditer(r'(?m)^' + re.escape(marker) + r'\r?\n', text))


def native_ready(text):
    clean = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    return re.search(r'(?m)^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+\] '
                     r'\[info\] \[\d+\] Printer is ready at \d+\.\d+\.[ \t]*\r?\n', clean) is not None


def instrument(commands):
    """Accept only the candidate's one-invocation command shape; preserve `$?`."""
    lines = commands.splitlines()
    indices = [i for i, line in enumerate(lines) if line.startswith('timeout -t ')]
    if len(indices) != 1:
        raise ValueError('Expected one bounded client invocation')
    i = indices[0]
    if not re.fullmatch(r'timeout -t ([1-9]|[12][0-9]|30) /tmp/grpc-probe > /tmp/grpc-probe.out', lines[i]):
        raise ValueError('Unexpected client invocation')
    expected_tail = ['GRPC_PROBE_TRANSPORT_EXIT=$?', 'od -v -b /tmp/grpc-probe.out',
                     'echo GRPC_PROBE_TRANSPORT_EXIT=$GRPC_PROBE_TRANSPORT_EXIT', 'echo GRPC_PROBE_DONE']
    if lines[i + 1:] != expected_tail or i < 2 or lines[i - 1] != 'chmod +x /tmp/grpc-probe':
        raise ValueError('Unexpected stream-end command shape or missing saved status')
    for number, line in enumerate(lines[:i - 1]):
        redirect = '>' if number == 0 else '>>'
        if not re.fullmatch(r"printf '(?:\\[0-7]{3})+' " + redirect + r' /tmp/grpc-probe', line):
            raise ValueError('Unexpected command outside the single probe invocation')
    lines[i + 2:i + 2] = ['READY_CLIENT_STATUS=$GRPC_PROBE_TRANSPORT_EXIT',
                          'echo READY_CLIENT_STATUS=$READY_CLIENT_STATUS', 'echo ' + RAW_BEGIN]
    od = lines.index('od -v -b /tmp/grpc-probe.out')
    lines.insert(od + 1, 'echo ' + RAW_END)
    return '\n'.join(lines) + '\n'


def bounded_region(text, begin, end):
    starts, finishes = marker_matches(text, begin), marker_matches(text, end)
    if len(starts) > 1 or len(finishes) > 1:
        raise ValueError('Duplicate capture markers')
    if not starts:
        if finishes:
            raise ValueError('Capture end without its begin marker')
        return None
    if not finishes:
        return None
    if finishes[0].start() <= starts[0].end():
        raise ValueError('Reversed or empty capture markers')
    return text[starts[0].end():finishes[0].start()]


def read_od(text):
    data, final_offset = bytearray(), None
    for line in text.splitlines():
        match = re.fullmatch(r'([0-7]{7,})[ \t]+((?:[0-7]{3}[ \t]*)+)', line)
        if match:
            if final_offset is not None or int(match[1], 8) != len(data):
                raise ValueError('Noncontiguous or repeated raw dump')
            values = [int(value, 8) for value in match[2].split()]
            if any(value > 255 for value in values) or len(values) > 16:
                raise ValueError('Invalid octal byte row')
            data.extend(values)
            if len(data) > MAX_CAPTURE:
                raise ValueError('Raw capture exceeds limit')
        elif re.fullmatch(r'[0-7]{7,}[ \t]*', line):
            if final_offset is not None:
                raise ValueError('Duplicate dump final offset')
            final_offset = int(line, 8)
        elif re.match(r'^\d{7,}[ \t]', line) or line == '*':
            raise ValueError('Malformed or elided raw dump')
    if final_offset is None or final_offset != len(data) or not data:
        raise ValueError('Incomplete raw dump')
    return bytes(data)


def decode_headers(block):
    """Strict subset for recovered native HPACK. Unsupported forms fail closed.

    Recognizes raw-string literals and the observed static :status/content-type
    entries; never substring-searches for status or guesses Huffman/dynamic data.
    """
    position, headers = 0, []
    static = {8: (b':status', b'200'), 9: (b':status', b'204'),
              10: (b':status', b'206'), 11: (b':status', b'304'),
              12: (b':status', b'400'), 13: (b':status', b'404'),
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
        if not name or name.lower() != name:
            raise ValueError('Invalid HTTP/2 header name')
        headers.append((name, value))
    return headers


def state_response(data):
    """Require complete framing, final grpc-status=0, and one ready protobuf."""
    position, continuation, ended = 0, None, False
    header_block, grpc_body, header_sets, terminal_headers = bytearray(), bytearray(), [], None
    while position < len(data):
        if ended or len(data) - position < 9:
            raise ValueError('Trailing or incomplete HTTP/2 frame')
        size = int.from_bytes(data[position:position + 3], 'big')
        kind, flags = data[position + 3:position + 5]
        stream = int.from_bytes(data[position + 5:position + 9], 'big') & 0x7fffffff
        position += 9
        payload = data[position:position + size]; position += size
        if size > 16384 or len(payload) != size:
            raise ValueError('Oversized or incomplete HTTP/2 payload')
        if continuation is not None and (kind != 9 or stream != continuation[0]):
            raise ValueError('Interrupted header block')
        if kind == 9:
            if continuation is None:
                raise ValueError('Unexpected CONTINUATION')
            header_block.extend(payload)
            if flags & 4:
                stream, terminal = continuation
                continuation = None
                if stream == 1:
                    headers = decode_headers(bytes(header_block)); header_sets.append(headers)
                    if terminal:
                        terminal_headers, ended = headers, True
                header_block.clear()
        elif kind in (0, 1):
            if stream == 0:
                raise ValueError('Stream frame with zero stream ID')
            if flags & 8:
                if not payload or payload[0] >= len(payload):
                    raise ValueError('Invalid HTTP/2 padding')
                payload = payload[1:len(payload) - payload[0]]
            if kind == 1:
                if flags & 32:
                    if len(payload) < 5 or int.from_bytes(payload[:4], 'big') & 0x7fffffff == stream:
                        raise ValueError('Invalid HEADERS priority')
                    payload = payload[5:]
                header_block = bytearray(payload)
                if flags & 4:
                    if stream == 1:
                        headers = decode_headers(bytes(header_block)); header_sets.append(headers)
                        if flags & 1:
                            terminal_headers, ended = headers, True
                    header_block.clear()
                else:
                    continuation = (stream, bool(flags & 1))
            elif stream == 1:
                grpc_body.extend(payload)
                if flags & 1:
                    ended = True
        elif kind == 3 and stream == 1:
            raise ValueError('PrinterState stream reset')
        elif kind == 4:
            if stream or size % 6 or flags & 1 and size:
                raise ValueError('Malformed SETTINGS')
        elif kind == 6:
            if stream or size != 8:
                raise ValueError('Malformed PING')
        elif kind == 8:
            if size != 4 or not int.from_bytes(payload, 'big') & 0x7fffffff:
                raise ValueError('Malformed WINDOW_UPDATE')
        elif kind == 7 and (stream or size < 8):
            raise ValueError('Malformed GOAWAY')
        elif kind == 5:
            raise ValueError('Unsupported server push')
    if continuation is not None or not ended or terminal_headers is None:
        raise ValueError('Missing complete stream 1 trailers')
    statuses = [value for headers in header_sets for name, value in headers if name == b'grpc-status']
    if statuses != [b'0'] or (b'grpc-status', b'0') not in terminal_headers:
        raise ValueError('Missing, ambiguous or nonzero gRPC status')
    http_statuses = [value for headers in header_sets for name, value in headers if name == b':status']
    if http_statuses != [b'200']:
        raise ValueError('Missing or invalid HTTP response status')
    if len(grpc_body) < 5 or grpc_body[0] != 0 or int.from_bytes(grpc_body[1:5], 'big') != len(grpc_body) - 5:
        raise ValueError('Incomplete, compressed or non-unary gRPC message')
    protobuf, fields, cursor = bytes(grpc_body[5:]), {}, 0

    def varint():
        nonlocal cursor
        value = 0
        for shift in range(0, 70, 7):
            if cursor >= len(protobuf):
                raise ValueError('Truncated protobuf varint')
            byte = protobuf[cursor]; cursor += 1
            if shift == 63 and byte > 1:
                raise ValueError('Oversized protobuf varint')
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise ValueError('Oversized protobuf varint')

    while cursor < len(protobuf):
        tag = varint(); number = tag >> 3
        if number == 0 or number >= 1 << 29 or tag & 7 != 2:
            raise ValueError('Unexpected PrinterState response field')
        length = varint(); value = protobuf[cursor:cursor + length]; cursor += length
        if len(value) != length or number in fields:
            raise ValueError('Truncated or duplicate PrinterState field')
        fields[number] = value
    if fields.get(1):
        raise ValueError('PrinterState returned a nonempty error object')
    answer = {'state': fields.get(2, b'').decode(), 'state_message': fields.get(3, b'').decode()}
    if answer['state'] != 'ready':
        raise ValueError('PrinterState did not report ready')
    return answer


def verify(text, begin=BEGIN, end=END):
    body = bounded_region(text, begin, end)
    if body is None:
        return None
    status = re.findall(r'(?m)^READY_CLIENT_STATUS=(\d+)\r?\n', body)
    transport = re.findall(r'(?m)^GRPC_PROBE_TRANSPORT_EXIT=(\d+)\r?\n', body)
    if len(status) != 1 or len(transport) != 1 or status != ['0'] or transport != ['0']:
        raise ValueError('Missing, ambiguous or nonzero client/transport status')
    if len(marker_matches(body, 'GRPC_PROBE_DONE')) != 1:
        raise ValueError('Missing or duplicate probe completion marker')
    raw = bounded_region(body, RAW_BEGIN, RAW_END)
    if raw is None:
        raise ValueError('Missing complete raw capture markers')
    response = state_response(read_od(raw))
    return {'client_exit_status': 0, 'transport_exit_status': 0, 'api_response': response,
            'physical_completion_proven': False}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_name')
    parser.add_argument('--seconds', type=int, default=1800)
    args = parser.parse_args(argv)
    if not re.fullmatch('[A-Za-z0-9_-]+', args.run_name):
        parser.error('Invalid run name')
    if not 1 <= args.seconds <= 86400:
        parser.error('--seconds must be between 1 and 86400')
    return args


def main(argv=None):
    args = parse_args(argv)
    directory = ROOT / 'runs' / args.run_name
    if directory.exists():
        raise SystemExit('Run directory already exists')
    env = dict(os.environ, RUN_SECONDS=str(args.seconds), PASSIVE_MOTOR_TRACE='1',
               RECOVERED_NOZZLE_NTC='1', ASSUMED_XY_DIAG_CABLE='1', MOTOR_ENABLE_WIRING='mcu-control-only',
               PASSIVE_NOZZLE_TRACE='1', PASSIVE_HOMING_GPIO='1', PASSIVE_TMC_TRACE='1', NATIVE_NOZZLE_HEATER='0')
    record = {'scope': 'Read-only startup and one PrinterState; no homing, heating or print requests',
              'phase': 'waiting_ready', 'request_count': 0, 'final_export_requested': False}
    token = secrets.token_hex(12)
    begin, end = BEGIN + '_' + token, END + '_' + token
    record['capture_markers'] = {'begin': begin, 'end': end}
    next_poll, start, previous = 0, None, ''

    def save():
        if directory.exists():
            temporary = directory / 'ready-observation.json.tmp'
            temporary.write_text(json.dumps(record, indent=2) + '\n')
            temporary.replace(directory / 'ready-observation.json')

    def request_stop(reason):
        if directory.exists():
            signal = directory / 'stop-request'
            if not signal.exists():
                signal.write_text(reason + '\n')
            record['final_export_requested'] = True

    def append(commands):
        with (directory / 'console-input.commands').open('a') as stream:
            stream.write(commands)

    try:
        process = subprocess.Popen([str(ROOT / 'rv1106-at32-link/scripts/run_native_event_fixture.sh'), args.run_name], env=env)
    except OSError as error:
        record.update(phase='error', error=str(error)); save()
        return 2
    try:
        while process.poll() is None:
            if (directory / 'stop-request').exists():
                record['phase'] = 'stop_requested'; record['final_export_requested'] = True
                break
            if not (directory / 'console.bin').exists():
                time.sleep(.2); continue
            text = (directory / 'console.bin').read_text(errors='replace')
            if not text.startswith(previous):
                raise ValueError('Console was truncated or rewritten; refusing stale capture')
            previous = text
            clock = directory / 'virtual-time.json'
            now = json.loads(clock.read_text())['virtual_time_ns'] if clock.exists() else 0
            if type(now) is not int or now < 0:
                raise ValueError('Invalid virtual-time sample')
            record['last_virtual_time_ns'] = now
            if record['phase'] == 'waiting_ready':
                if native_ready(text):
                    output = directory / 'readiness-stream-end'
                    record['generation_attempts'] = 1
                    subprocess.run([sys.executable, str(ROOT / 'rv1106-at32-link/experimental/stream-end-probe/make_probe.py'),
                                    '--response-mode', 'stream-end', '--method', 'PrinterState',
                                    '--timeout-seconds', '5', '--output', str(output)], check=True, stdout=subprocess.DEVNULL, timeout=30)
                    commands = instrument(output.with_suffix('.commands').read_text())
                    if (directory / 'stop-request').exists():
                        record.update(phase='stop_requested', final_export_requested=True)
                        break
                    start = len(text)
                    record.update(phase='queue_attempted', queued_virtual_time_ns=now, request_count=1, queue_outcome='uncertain')
                    save()
                    append('echo ' + begin + '\ncat /proc/uptime\n' + commands + 'cat /proc/uptime\necho ' + end + '\n')
                    record.update(phase='probe_queued', queue_outcome='appended')
                elif marker_matches(text, 'COUPLED_STARTUP_COMMANDS_DONE') and now >= next_poll:
                    append('tail -100 /data/main.stdout\ntail -100 /data/logs/avata_main.log\n')
                    next_poll = now + 1000000000
            elif record['phase'] == 'probe_queued':
                result = verify(text[start:], begin, end)
                if result is not None:
                    record.update(phase='verified_ready', result=result, finished_virtual_time_ns=now)
                    request_stop('Read-only ready response verified; final export.')
                    save(); break
            save(); time.sleep(.2)
    except Exception as error:
        record.update(phase='error', error=str(error))
        try:
            request_stop('Diagnostic observer error; no retry; final export.')
        except OSError as stop_error:
            record['stop_request_error'] = str(stop_error)
        try:
            save()
        except OSError as save_error:
            record['record_write_error'] = str(save_error)
    finally:
        record['launcher_exit_code'] = process.wait()
        save()
    return record['launcher_exit_code'] or (0 if record['phase'] == 'verified_ready' else 2)


if __name__ == '__main__':
    raise SystemExit(main())
