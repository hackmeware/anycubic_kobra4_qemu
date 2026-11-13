#!/usr/bin/env python3
"""EXPERIMENTAL: one normal Homing X, Y, Z sequence in the explicit synthetic fixture.

Not a calibration/print runner. An empty RPC is acceptance, never rail completion.
Each next axis requires a completed, error-free RPC AND fresh original native rail
begin/complete logs. The firmware's XY/Z guards, force filtering and retries are
not modified. Importing this module or generating packets never starts firmware.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import secrets
import signal
import subprocess
import sys
import time
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROFILE = 'synthetic-functional'
AXES = ('X', 'Y', 'Z')
NANOSECOND = 1_000_000_000
MAX_CONSOLE_BYTES = 64 * 1024 * 1024
ARTIFACTS = (
    'console.bin', 'launcher.log', 'renode.log', 'virtual-time.json', 'renode-step.json',
    'z-probe-profile.json', 'shared-profile.json', 'shared-model-manifest.json', 'scheduling-experiment.json',
    'z-sensor-status.json', 'z-sensor.csv', 'z-nozzle-gpio.csv',
    'z-force-status.json', 'z-force-query.csv',
    'nozzle-z-probe-edges.csv', 'main-z-probe-edges.csv',
    'motor-state.csv', 'contact-transitions.csv', 'main-homing-edges.csv', 'motor-homing-edges.csv',
    'final-main-sram.bin', 'final-motor-sram.bin', 'final-nozzle-sram.bin',
    'final-nozzle-fault-words.bin', 'nozzle-thermal.csv',
)


def load_helper(relative, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ready = load_helper('rv1106-at32-link/scripts/run_native_ready_observation.py', 'xyz_ready_helper')
transport = load_helper('rv1106-at32-link/experimental/stream-end-probe/make_probe.py', 'xyz_stream_end_helper')


def request_packet(method, axis=None):
    """Only two verified schemas, fixed guest loopback, never a G-code escape hatch."""
    if method == 'PrinterState' and axis is None:
        protobuf = b''
    elif method == 'Homing' and axis in AXES:
        protobuf = b'\x0a\x01' + axis.encode('ascii')
    else:
        raise ValueError('Only PrinterState and explicit normal Homing X/Y/Z are permitted')

    def string(value):
        return bytes([len(value)]) + value

    headers = (b'\x83\x86\x04' + string(b'/applink.AppLinkService/' + method.encode()) +
               b'\x01' + string(b'127.0.0.1:50051') + b'\x0f\x10' + string(b'application/grpc') +
               b'\x00' + string(b'te') + string(b'trailers'))
    message = b'\0' + len(protobuf).to_bytes(4, 'big') + protobuf
    return (transport.PREFACE + transport.frame(4, 0, 0) + transport.frame(1, 4, 1, headers) +
            transport.frame(0, 1, 1, message)), protobuf


def prepare_request(directory, stage, token):
    """Offline code/data generation only. Each stage gets distinct capture markers."""
    method, axis = ('PrinterState', None) if stage == 'ready' else ('Homing', stage)
    packet, protobuf = request_packet(method, axis)
    elf = transport.build(packet)
    # Assert the stream-end executable still contains our exact single packet.
    if transport.extract_packet(elf) != packet:
        raise ValueError('Transport generation changed the exact request packet')
    output = directory / ('xyz-' + stage.lower())
    output.with_suffix('.elf').write_bytes(elf)
    output.with_suffix('.protobuf.bin').write_bytes(protobuf)
    output.with_suffix('.http2.bin').write_bytes(packet)
    commands = ready.instrument(transport.commands(elf, 5))
    output.with_suffix('.commands').write_text(commands)
    begin, end = 'XYZ_' + stage.upper() + '_BEGIN_' + token, 'XYZ_' + stage.upper() + '_END_' + token
    return {'begin': begin, 'end': end, 'method': method, 'axis': axis,
            'protobuf_hex': protobuf.hex(), 'packet_sha256': hashlib.sha256(packet).hexdigest(),
            'client_timeout_guest_seconds': 5,
            'commands': 'echo ' + begin + '\n' + commands + 'echo ' + end + '\n'}


def unary_protobuf(data):
    """Strict complete-response parser, generalized from the readiness observer.

    Raw-string/static native HPACK only; unsupported encodings fail closed.
    This parses transport framing, not Homing success or physical effects.
    """
    if len(data) > ready.MAX_CAPTURE:
        raise ValueError('Response exceeds capture limit')
    position, continuation, ended = 0, None, False
    block, body, header_sets, terminal_headers = bytearray(), bytearray(), [], None
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
            block.extend(payload)
            if flags & 4:
                stream, terminal = continuation; continuation = None
                if stream != 1:
                    raise ValueError('Unexpected response stream')
                headers = ready.decode_headers(bytes(block)); header_sets.append(headers)
                if terminal:
                    terminal_headers, ended = headers, True
                block.clear()
        elif kind in (0, 1):
            if stream != 1:
                raise ValueError('Unexpected response stream')
            if flags & 8:
                if not payload or payload[0] >= len(payload):
                    raise ValueError('Invalid HTTP/2 padding')
                payload = payload[1:len(payload) - payload[0]]
            if kind == 1:
                if header_sets and not flags & 1:
                    raise ValueError('Unexpected nonterminal response headers')
                if flags & 32:
                    if len(payload) < 5 or int.from_bytes(payload[:4], 'big') & 0x7fffffff == stream:
                        raise ValueError('Invalid HEADERS priority')
                    payload = payload[5:]
                block = bytearray(payload)
                if flags & 4:
                    headers = ready.decode_headers(bytes(block)); header_sets.append(headers)
                    if flags & 1:
                        terminal_headers, ended = headers, True
                    block.clear()
                else:
                    continuation = (stream, bool(flags & 1))
            else:
                if not header_sets:
                    raise ValueError('DATA arrived before complete response headers')
                body.extend(payload)
                if flags & 1:
                    ended = True
        elif kind == 3:
            raise ValueError('RPC stream reset')
        elif kind == 4:
            if stream or size % 6 or flags & 1 and size:
                raise ValueError('Malformed SETTINGS')
        elif kind == 6:
            if stream or size != 8:
                raise ValueError('Malformed PING')
        elif kind == 8:
            if size != 4 or not int.from_bytes(payload, 'big') & 0x7fffffff:
                raise ValueError('Malformed WINDOW_UPDATE')
        elif kind == 7:
            if stream or size < 8:
                raise ValueError('Malformed GOAWAY')
            if int.from_bytes(payload[4:8], 'big'):
                raise ValueError('Nonzero GOAWAY error')
        elif kind == 2:
            if not stream or size != 5 or int.from_bytes(payload[:4], 'big') & 0x7fffffff == stream:
                raise ValueError('Malformed PRIORITY')
        elif kind == 5:
            raise ValueError('Unsupported server push')
    if continuation is not None or not ended or terminal_headers is None:
        raise ValueError('Missing complete stream 1 trailers')
    statuses = [value for headers in header_sets for name, value in headers if name == b'grpc-status']
    if statuses != [b'0'] or (b'grpc-status', b'0') not in terminal_headers:
        raise ValueError('Missing, ambiguous or nonzero gRPC status')
    if [v for hs in header_sets for k, v in hs if k == b':status'] != [b'200']:
        raise ValueError('Missing or invalid HTTP status')
    if len(body) < 5 or body[0] != 0 or int.from_bytes(body[1:5], 'big') != len(body) - 5:
        raise ValueError('Incomplete, compressed or non-unary gRPC message')
    return bytes(body[5:])


def fields(protobuf, allowed):
    """Decode only the explicit observed wire schema; reject ambiguity/unknowns."""
    position, answer = 0, {}

    def varint():
        nonlocal position
        value = 0
        for shift in range(0, 70, 7):
            if position >= len(protobuf):
                raise ValueError('Truncated protobuf varint')
            byte = protobuf[position]; position += 1
            if shift == 63 and byte > 1:
                raise ValueError('Oversized protobuf varint')
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise ValueError('Oversized protobuf varint')

    while position < len(protobuf):
        tag = varint(); number, wire = tag >> 3, tag & 7
        if number not in allowed or allowed[number] != wire or number in answer:
            raise ValueError('Unknown, duplicate or wrong-wire protobuf field')
        if wire == 0:
            answer[number] = varint()
        else:
            size = varint(); value = protobuf[position:position + size]; position += size
            if len(value) != size:
                raise ValueError('Truncated protobuf field')
            answer[number] = value
    return answer


def homing_response(data):
    protobuf = unary_protobuf(data)
    outer = fields(protobuf, {1: 2})
    error = outer.get(1, b'')
    decoded = fields(error, {1: 0, 2: 2}) if error else {}
    return {'rpc_acceptance_verified': not bool(error), 'response_protobuf_hex': protobuf.hex(),
            'application_error': {'code': decoded.get(1, 0), 'message': decoded.get(2, b'').decode()} if error else None,
            'native_completion_proven_by_rpc': False}


def verify_capture(text, request):
    region = ready.bounded_region(text, request['begin'], request['end'])
    if region is None:
        return None
    statuses = re.findall(r'(?m)^READY_CLIENT_STATUS=(\d+)\r?\n', region)
    transport_statuses = re.findall(r'(?m)^GRPC_PROBE_TRANSPORT_EXIT=(\d+)\r?\n', region)
    if statuses != ['0'] or transport_statuses != ['0']:
        raise ValueError('Missing, ambiguous or nonzero client/transport status; no retry')
    if len(ready.marker_matches(region, 'GRPC_PROBE_DONE')) != 1:
        raise ValueError('Missing or duplicate probe completion')
    raw = ready.bounded_region(region, ready.RAW_BEGIN, ready.RAW_END)
    if raw is None:
        raise ValueError('Missing complete raw dump')
    data = ready.read_od(raw)
    result = {'transport_complete': True, 'client_exit_status': 0, 'transport_exit_status': 0,
              'response_sha256': hashlib.sha256(data).hexdigest()}
    if request['method'] == 'PrinterState':
        unary_protobuf(data)  # Same strict stream restriction for the initial read-only check.
        result['ready_response'] = ready.state_response(data)
    else:
        result.update(homing_response(data))
    return result


LOGGER = re.compile(r'(?m)^(\[(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2}\.\d+)\] '
                    r'\[(info|warning|warn|error|critical)\] \[\d+\] ([^\r\n]*))\r?\n')
KNOWN_ABSENT_VIDEO_SERVICE = ('GetVideoState failed: failed to connect to all addresses; last error: UNKNOWN: '
                            'ipv4:127.0.0.1:50052: Failed to connect to remote host: Connection refused')


def native_entries(text):
    clean = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    return [(m[1], (m[2], int(m[3]), int(m[4]), Decimal(m[5])), m[6], m[7].rstrip())
            for m in LOGGER.finditer(clean)]


def native_failure(severity, message):
    if severity == 'error' and message == KNOWN_ABSENT_VIDEO_SERVICE:
        return False
    return severity in ('error', 'critical') or bool(re.search(
        r'Must home X and Y axes first|Printer is shutdown|MCU shutdown|'
        r'No trigger on .* after full movement|Endstop .* still triggered|'
        r'CS1237 (?:invalid|query timeout)|Homing failed', message, re.I))


class AxisObservation:
    """Passive evidence state. This class cannot send any command or change an axis."""
    def __init__(self, axis, text, request, now):
        self.axis, self.start, self.request = axis, len(text), request
        old = native_entries(text)
        self.seen = {entry[0] for entry in old}
        self.timestamp_floor = max((entry[1] for entry in old), default=None)
        self.begin_stamp = None
        self.state = {'axis': axis, 'request_count': 1, 'queue_outcome': 'uncertain',
                      'queued_at_controller_virtual_time_ns': now, 'transport_complete': False,
                      'rpc_acceptance_verified': False, 'native_begin_log': None,
                      'native_completion_log': None, 'native_failure_lines': [],
                      'known_absent_video_service_lines': [],
                      'unexpected_axis_lines': [], 'physical_causal_chain_verified': False}

    def observe(self, text, now):
        suffix = text[self.start:]
        starts = ready.marker_matches(suffix, self.request['begin'])
        if len(starts) > 1:
            raise ValueError('Duplicate stage begin marker')
        if not starts:
            return
        result = verify_capture(suffix, self.request)
        if result is not None:
            self.state.update(result)
            if not result['rpc_acceptance_verified']:
                self.state['failure'] = 'Native Homing RPC returned an application error'
        for line, stamp, severity, message in native_entries(suffix[starts[0].end():]):
            if line in self.seen:
                continue
            self.seen.add(line)
            if self.timestamp_floor is not None and stamp <= self.timestamp_floor:
                continue
            if severity == 'error' and message == KNOWN_ABSENT_VIDEO_SERVICE:
                # Exact historical unrelated camera failure, retained rather than
                # mistaken for a motion failure. No generic "error" suppression.
                self.state['known_absent_video_service_lines'].append(line)
                continue
            if native_failure(severity, message):
                self.state['native_failure_lines'].append(line)
                self.state['failure'] = 'New native error/guard/shutdown evidence; conservative observation stop'
            rail = re.fullmatch(r'Home Rail (Begin|Complete) - stepper: ([xyz])', message)
            if not rail:
                continue
            if rail[2] != self.axis.lower():
                self.state['unexpected_axis_lines'].append(line)
                self.state['failure'] = 'Unexpected native axis; possible guard fallback or external action'
                continue
            if rail[1] == 'Begin' and self.begin_stamp is None:
                self.begin_stamp = stamp
                self.state['native_begin_log'] = line
                self.state['native_begin_observed_at_controller_virtual_time_ns'] = now
            elif rail[1] == 'Complete' and self.begin_stamp is not None and stamp > self.begin_stamp:
                self.state['native_completion_log'] = line
                self.state['native_completion_observed_at_controller_virtual_time_ns'] = now

    def complete(self):
        return bool(self.state['transport_complete'] and self.state['rpc_acceptance_verified'] and
                    self.state['native_begin_log'] and self.state['native_completion_log'] and
                    not self.state.get('failure'))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_name')
    parser.add_argument('--z-probe-profile', choices=['none', PROFILE], default='none')
    parser.add_argument('--nozzle-tmc-model', choices=['fixed', 'autobaud'], default='fixed',
                        help='Explicit external TMC model; never inherited from the environment')
    parser.add_argument('--seconds', type=int, default=1800, help='Total wall observation limit, including initialization')
    parser.add_argument('--virtual-seconds', type=int, default=180, help='Controller virtual-time absolute observation limit')
    parser.add_argument('--stage-seconds', type=int, default=900, help='Maximum wall time for one RPC/axis stage')
    parser.add_argument('--stage-virtual-seconds', type=int, default=90)
    parser.add_argument('--cleanup-seconds', type=int, default=120)
    args = parser.parse_args(argv)
    if args.z_probe_profile != PROFILE:
        parser.error('Explicit --z-probe-profile synthetic-functional is required; no default Z run')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run_name):
        parser.error('Invalid run name')
    for key, maximum in [('seconds', 86400), ('virtual_seconds', 3600), ('stage_seconds', 86400),
                         ('stage_virtual_seconds', 3600), ('cleanup_seconds', 300)]:
        if not 1 <= getattr(args, key) <= maximum:
            parser.error('--' + key.replace('_', '-') + ' is outside 1..' + str(maximum))
    return args


def validate_tmc_manifest(directory, shared, requested):
    """Require selected metadata and the exact generated-model entry to agree."""
    if requested not in ('fixed', 'autobaud'):
        raise ValueError('Unknown requested nozzle TMC model')
    selected = shared.get('nozzle_tmc_model', {})
    if selected.get('selection') != requested or selected.get('experimental') is not (requested == 'autobaud'):
        raise ValueError('Requested nozzle TMC model differs from shared profile')
    manifest = json.loads((directory / 'shared-model-manifest.json').read_text())
    entries = [entry for entry in manifest if entry.get('generated') == 'nozzle/peripherals/VirtualNozzleTmc2209.cs']
    if len(entries) != 1:
        raise ValueError('Missing or ambiguous nozzle TMC generated-model manifest entry')
    entry = entries[0]
    source = ('nozzle-renode/peripherals/VirtualNozzleTmc2209.cs' if requested == 'fixed' else
              'nozzle-renode/experimental/tmc-native-replay/VirtualNozzleTmc2209Autobaud.cs')
    if (entry.get('board') != 'nozzle' or entry.get('source') != source or
            any(not re.fullmatch(r'[0-9a-f]{64}', entry.get(key, '')) for key in ('source_sha256', 'generated_sha256'))):
        raise ValueError('Nozzle TMC manifest source or hashes do not describe the requested model')
    if requested == 'autobaud':
        if (entry.get('experimental_tmc_model') != requested or
                any(selected.get(key) != entry.get(key) for key in ('source', 'source_sha256', 'generated_sha256')) or
                selected.get('transformation') != 'namespace and class identity only' or
                any(selected.get(key) is not False for key in ('gpio_sync_time_added', 'turnaround_tuned', 'firmware_changed'))):
            raise ValueError('Autobaud profile and generated-model manifest disagree')
    elif 'experimental_tmc_model' in entry:
        raise ValueError('Fixed TMC requested but manifest carries an experimental override')
    scheduling = json.loads((directory / 'scheduling-experiment.json').read_text())
    if (scheduling.get('tmc_model') != requested or scheduling.get('global_quantum_us') != 1 or
            scheduling.get('tmc_model_changes') is not (requested == 'autobaud')):
        raise ValueError('Requested TMC model or 1 us quantum disagrees with scheduling metadata')
    return {'selection': requested, 'profile': selected, 'manifest_entry': entry}


def validate_profile(directory, nozzle_tmc_model='fixed'):
    profile = json.loads((directory / 'z-probe-profile.json').read_text())
    shared = json.loads((directory / 'shared-profile.json').read_text())
    if (profile.get('selection') != PROFILE or profile.get('global_quantum_ns') != 1000 or
            profile.get('maximum_state_age_ns') != 100000 or profile.get('maximum_producer_lead_ns') != 1000 or
            profile.get('physical_timing_fidelity') is not False or profile.get('firmware_changes') is not False or
            profile.get('experimental') is not True or profile.get('clock_or_mips_changes') is not False or
            profile.get('physical_geometry_and_calibration_verified') is not False):
        raise ValueError('Missing or incompatible synthetic-functional profile metadata')
    if shared.get('z_probe_profile') != profile:
        raise ValueError('Shared/profile Z selection metadata disagree')
    validate_tmc_manifest(directory, shared, nozzle_tmc_model)
    wire = profile.get('probe_wiring', {})
    if wire.get('source') != 'actual nozzle PA7 resolved GPIO' or wire.get('destination') != 'main PB2' or wire.get('noninverting_assumption') is not True:
        raise ValueError('Missing original PA7 to PB2 cable declaration')
    expected_parameters = {'bed_relative_mm': -10.0, 'opposite_stop_relative_mm': 252.0, 'bed_side': 'minimum',
                           'stiffness_n_per_mm': 20.0, 'damping_ns_per_mm': 0.05, 'baseline_counts': 0,
                           'counts_per_n': 10000.0, 'signal_polarity': 1, 'history_capacity': 4096,
                           'query_trace_rows': 100000}
    if profile.get('parameters') != expected_parameters:
        raise ValueError('XYZ observer requires the reviewed fixed synthetic fixture parameters')
    return profile


def artifact_inventory(directory):
    answer = {}
    for name in ARTIFACTS:
        path = directory / name
        if not path.is_file():
            answer[name] = {'exists': False}
            continue
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        answer[name] = {'exists': True, 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}
    return answer


def assess_exports(record):
    """Report missing/faulted/incomplete evidence separately from native rail logs."""
    issues, warnings = [], []
    required = ('z-force-status.json', 'z-sensor-status.json', 'motor-state.csv',
                'z-force-query.csv', 'main-z-probe-edges.csv', 'nozzle-z-probe-edges.csv')
    for name in required:
        if not record['artifacts'][name]['exists']:
            issues.append('Missing final evidence: ' + name)
    force = record.get('z-force-status', {})
    sensor = record.get('z-sensor-status', {})
    if force:
        if force.get('faulted') is not False or force.get('last_error') or force.get('bound') is not True:
            issues.append('Force source faulted, unbound, or missing explicit healthy status')
        if force.get('dropped_query_trace_rows', 0):
            warnings.append('Force-query trace is capacity-truncated; not complete Z causal evidence')
    if sensor:
        if (sensor.get('timed_provider_bound') is not True or sensor.get('provider_failures', 0) or
                sensor.get('adapter_errors', 0) or sensor.get('protocol_errors', 0) or
                sensor.get('last_error') or sensor.get('adapter_error')):
            issues.append('Sensor provider/protocol reported a fault or lacks a bound provider')
        if sensor.get('dropped', 0):
            warnings.append('Sensor trace is capacity-truncated and may contain only pre-Z startup samples')
    warnings.append('GPIO bit trace is capped; inspect final dropped-row counters in renode.log. '
                    'File existence and zero semantic errors do not prove complete Z capture.')
    if record.get('cleanup_limit_exceeded'):
        issues.append('Launcher cleanup exceeded its wall limit; final export may be incomplete')
    issues.extend(record.get('artifact_errors', []))
    record['evidence_issues'], record['evidence_warnings'] = issues, warnings
    return issues


def main(argv=None):
    args = parse_args(argv)
    directory = ROOT / 'runs' / args.run_name
    if directory.exists():
        raise SystemExit('Run directory already exists; no retry or overwrite')
    # Known XY fixture plus explicitly selected Z/TMC models. Do not inherit heater,
    # clock-shift, alternate TMC, or geometry overrides accidentally.
    env = {key: value for key, value in os.environ.items() if not key.startswith('Z_')}
    env.update(RUN_SECONDS=str(args.seconds), Z_PROBE_PROFILE=PROFILE, GLOBAL_QUANTUM_US='1',
               ICOUNT_SHIFT='0', NOZZLE_TMC_MODEL=args.nozzle_tmc_model, PASSIVE_MOTOR_TRACE='1', PASSIVE_CONTACT_TRACE='1',
               RECOVERED_NOZZLE_NTC='1', ASSUMED_XY_DIAG_CABLE='1', MOTOR_ENABLE_WIRING='mcu-control-only',
               PASSIVE_NOZZLE_TRACE='1', PASSIVE_HOMING_GPIO='1', PASSIVE_TMC_TRACE='1', NATIVE_NOZZLE_HEATER='0')
    record = {'scope': 'Experimental native Homing X then Y then Z; explicit synthetic-functional fixture only',
              'phase': 'waiting_ready', 'requests': [], 'axes': {}, 'final_export_requested': False,
              'native_xyz_completion_observed': False, 'physical_causal_chain_verified': False,
              'physical_geometry_validated': False, 'calibration_completed': False, 'print_completed': False,
              'direction_assumption': 'Positive rotor angle increases relative Z; native downward sign remains unverified. '
                                      'Review motor-state.csv and force traces. Never retune or synthesize a trigger on mismatch.',
              'force_query_scope': 'Accepted conversion candidates, not all physical captures or necessarily committed conversions',
              'time_scope': 'Controller virtual-time samples are not original native-log timestamps; no guessed clock offset',
              'limits': vars(args)}
    token = secrets.token_hex(12)
    previous, previous_now, pending_poll, next_poll = '', 0, None, 0
    stage, observation, request, request_start = None, None, None, None
    started = time.monotonic(); stage_started, stage_now = started, 0

    def save():
        if directory.exists():
            temporary = directory / 'xyz-observation.json.tmp'
            temporary.write_text(json.dumps(record, indent=2) + '\n')
            temporary.replace(directory / 'xyz-observation.json')

    def request_stop(reason):
        if directory.exists():
            try:
                with (directory / 'stop-request').open('x') as stream:
                    stream.write(reason + '\n')
            except FileExistsError:
                pass
            record['final_export_requested'] = True

    def append(commands):
        with (directory / 'console-input.commands').open('a') as stream:
            stream.write(commands)
            stream.flush()

    def queue(new_stage, text, now):
        nonlocal stage, observation, request, request_start, stage_started, stage_now
        if any(entry['stage'] == new_stage for entry in record['requests']):
            raise ValueError('Duplicate request attempt forbidden')
        # Mark generation attempted before any operation that could fail.
        entry = {'stage': new_stage, 'generation_attempted': True, 'queue_outcome': 'not_attempted'}
        record['requests'].append(entry); save()
        prepared = prepare_request(directory, new_stage, token)
        if (directory / 'stop-request').exists():
            raise ValueError('Stop arrived during request preparation; nothing more queued')
        request_start = len(text)
        entry.update({key: value for key, value in prepared.items() if key != 'commands'})
        entry.update(queue_outcome='uncertain', queued_at_controller_virtual_time_ns=now)
        stage, request, stage_started, stage_now = new_stage, prepared, time.monotonic(), now
        if stage in AXES:
            observation = AxisObservation(stage, text, request, now)
            record['axes'][stage] = observation.state
        record['phase'] = 'queue_attempted_' + stage.lower(); save()
        append(prepared['commands'])
        entry['queue_outcome'] = 'appended'
        if observation is not None:
            observation.state['queue_outcome'] = 'appended'
        record['phase'] = 'observing_' + stage.lower()

    try:
        process = subprocess.Popen([str(ROOT / 'rv1106-at32-link/scripts/run_native_event_fixture.sh'), args.run_name],
                                   env=env, start_new_session=True)
    except OSError as error:
        record.update(phase='error', error=str(error)); save()
        print('Native XYZ launcher could not start: ' + str(error), file=sys.stderr)
        return 2
    try:
        while process.poll() is None:
            wall = time.monotonic()
            if (directory / 'stop-request').exists():
                record.update(phase='stop_requested', final_export_requested=True)
                break
            if wall - started >= args.seconds:
                raise TimeoutError('Total wall observation limit reached')
            if stage is not None and wall - stage_started >= args.stage_seconds:
                raise TimeoutError('Stage wall observation limit reached: ' + stage)
            console = directory / 'console.bin'
            if not console.exists():
                time.sleep(.2); continue
            if console.stat().st_size > MAX_CONSOLE_BYTES:
                raise ValueError('Console capture exceeds observation budget')
            text = console.read_text(errors='replace')
            if not text.startswith(previous):
                raise ValueError('Console truncated or rewritten; refusing stale evidence')
            previous = text
            clock = directory / 'virtual-time.json'
            now = json.loads(clock.read_text())['virtual_time_ns'] if clock.exists() else 0
            if type(now) is not int or now < previous_now:
                raise ValueError('Invalid or backwards controller virtual time')
            previous_now = now; record['last_controller_virtual_time_ns'] = now
            if now >= args.virtual_seconds * NANOSECOND:
                raise TimeoutError('Total virtual observation limit reached')
            if stage is not None and now - stage_now >= args.stage_virtual_seconds * NANOSECOND:
                raise TimeoutError('Stage virtual observation limit reached: ' + stage)
            if stage is None and ready.native_ready(text):
                record['verified_profile'] = validate_profile(directory, args.nozzle_tmc_model)
                record['verified_tmc_selection'] = validate_tmc_manifest(
                    directory, json.loads((directory / 'shared-profile.json').read_text()), args.nozzle_tmc_model)
                queue('ready', text, now)
            elif stage == 'ready':
                before = native_entries(text[:request_start])
                floor = max((entry[1] for entry in before), default=None)
                failures = [line for line, stamp, severity, message in native_entries(text[request_start:])
                            if (floor is None or stamp > floor) and native_failure(severity, message)]
                if failures:
                    record['native_ready_stage_failures'] = sorted(set(failures))
                    raise ValueError('Native error after readiness request; no Homing queued')
                result = verify_capture(text[request_start:], request)
                if result is not None:
                    record['initial_ready_response'] = result
                    queue('X', text, now)
            elif observation is not None:
                observation.observe(text, now)
                if observation.state.get('failure'):
                    record['phase'] = 'native_failure_' + stage.lower()
                    record['failure'] = observation.state['failure']
                    request_stop('Native failure or guard evidence; no repeated request; final export.')
                    save(); break
                if observation.complete():
                    if stage == 'Z':
                        record.update(phase='native_xyz_completion_observed', native_xyz_completion_observed=True)
                        request_stop('Native X/Y/Z rail logs and separate RPC responses observed; final export for causal review.')
                        save(); break
                    queue(AXES[AXES.index(stage) + 1], text, now)
            # At most one passive log dump outstanding; never retry a partial append.
            if pending_poll is not None and ready.marker_matches(text[pending_poll[1]:], pending_poll[0]):
                pending_poll = None
            if pending_poll is None and now >= next_poll and (
                    stage is not None or ready.marker_matches(text, 'COUPLED_STARTUP_COMMANDS_DONE')):
                marker = 'XYZ_LOG_END_' + token + '_' + str(now)
                pending_poll = (marker, len(text))
                append('tail -150 /data/main.stdout\ntail -150 /data/logs/avata_main.log\necho ' + marker + '\n')
                next_poll = now + NANOSECOND
            save(); time.sleep(.2)
        else:
            record['phase'] = 'launcher_ended_before_observation_complete'
    except Exception as error:
        record.update(phase='error', error=str(error))
        try:
            request_stop('XYZ observer error/timeout; no retry; request normal final export.')
        except OSError as stop_error:
            record['stop_request_error'] = str(stop_error)
        try:
            save()
        except OSError as save_error:
            record['record_write_error'] = str(save_error)
    finally:
        try:
            record['launcher_exit_code'] = process.wait(timeout=args.cleanup_seconds)
        except subprocess.TimeoutExpired:
            record['cleanup_limit_exceeded'] = True
            record['final_export_not_verified'] = True
            # Only the new owned session is signaled, never other emulator runs.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                record['launcher_exit_code'] = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    record['launcher_exit_code'] = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    record['launcher_exit_code'] = 2
                    record['cleanup_error'] = 'Owned process did not exit after SIGKILL; wait bound reached'
        record['artifacts'] = artifact_inventory(directory)
        for name in ('z-force-status.json', 'z-sensor-status.json'):
            path = directory / name
            if path.exists():
                try:
                    record[name.replace('.json', '')] = json.loads(path.read_text())
                except (ValueError, OSError) as error:
                    record.setdefault('artifact_errors', []).append(name + ': ' + str(error))
        assess_exports(record)
        save()
    return record.get('launcher_exit_code', 2) or (2 if not record['native_xyz_completion_observed'] else
                                                  3 if record['evidence_issues'] else 0)


if __name__ == '__main__':
    raise SystemExit(main())
