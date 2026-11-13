#!/usr/bin/env python3
"""Opt-in synthetic heater regulation observer. Import/generation never starts a run.

Normal native setters only. No G-code, PID flags, factory mode, memory/ADC/duty
writes, guard changes or retry after uncertain transport. No PID-calibration claim.
"""
import argparse
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
import pathlib
import re
import secrets
import signal
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
NS = 1_000_000_000
TARGETS = {'nozzle': 230, 'bed': 60}
CAPS = {'nozzle': 250, 'bed': 75}
METHODS = {'nozzle': 'ExtruderPreheating', 'bed': 'HotbedPreheating'}
MAX_CONSOLE = 128 * 1024 * 1024
PROFILE_RULES = {
    'synthetic-calibration': {'factor': 1, 'band_seconds': 30, 'heat_cap_seconds': 240, 'zero_lead_seconds': 232},
    'accelerated-functional-4x': {'factor': 4, 'band_seconds': 5, 'heat_cap_seconds': 60, 'zero_lead_seconds': 52},
}
GRACEFUL_STOP_FILE = 'graceful-stop-request.json'


def helper(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


xyz = helper(ROOT / 'rv1106-at32-link/scripts/run_native_xyz_observation.py', 'thermal_xyz')
ready, transport = xyz.ready, xyz.transport
errors = helper(ROOT / 'rv1106-at32-link/scripts/decode_extruder_preheating_response.py', 'thermal_errors')
temperature = helper(HERE / 'schema-temperature/temperature_schema.py', 'thermal_temperature')
replay = helper(HERE / 'analyze_trace.py', 'thermal_replay')
snapshot = helper(HERE / 'status_snapshot.py', 'thermal_status_snapshot')
if (temperature.RPC_METHOD != '/applink.AppLinkService/GetStatus' or temperature.REQUEST != b'' or
        temperature.RPC_CARDINALITY != 'server_streaming'):
    raise ValueError('Unexpected recovered native temperature route')


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def request_packet(method, target=None):
    """Fixed guest loopback. No arbitrary method/target or general script interface."""
    if method == 'PrinterState' and target is None:
        protobuf = b''
    elif method == 'GetStatus' and target is None:
        protobuf = b''
    elif method in METHODS.values():
        heater = next(k for k, v in METHODS.items() if v == method)
        if type(target) is not int or target not in (0, TARGETS[heater]):
            raise ValueError('Only explicit synthetic heater target or zero is allowed')
        protobuf = b'\x10' + varint(target) if target else b''
    else:
        raise ValueError('Unverified or unapproved method')
    return frame_request(method, protobuf), protobuf


def frame_request(method, protobuf):
    def string(value):
        if len(value) >= 127:
            raise ValueError('Header string too long')
        return bytes([len(value)]) + value
    headers = (b'\x83\x86\x04' + string(b'/applink.AppLinkService/' + method.encode()) +
               b'\x01' + string(b'127.0.0.1:50051') + b'\x0f\x10' + string(b'application/grpc') +
               b'\x00' + string(b'te') + string(b'trailers'))
    message = b'\0' + len(protobuf).to_bytes(4, 'big') + protobuf
    return (transport.PREFACE + transport.frame(4, 0, 0) + transport.frame(1, 4, 1, headers) +
            transport.frame(0, 1, 1, message))


def prepare_request(directory, stage, token, method, target=None):
    packet, protobuf = request_packet(method, target)
    elf = snapshot.build_snapshot(packet) if method == 'GetStatus' else transport.build(packet)
    if transport.extract_packet(elf) != packet:
        raise ValueError('Transport changed exact request packet')
    output = directory / ('thermal-' + stage)
    output.with_suffix('.elf').write_bytes(elf)
    output.with_suffix('.protobuf.bin').write_bytes(protobuf)
    output.with_suffix('.http2.bin').write_bytes(packet)
    commands = ready.instrument(transport.commands(elf, 5))
    begin, end = 'THERMAL_' + stage.upper() + '_BEGIN_' + token, 'THERMAL_' + stage.upper() + '_END_' + token
    # Finish uploads first. The entire execution/capture suffix is ONE shell
    # input line, echoed before it executes. No later input is permitted until
    # the actual end marker and strict response are validated. This protects
    # even an instant unary reply from intra-batch TTY echo contamination.
    lines = commands.rstrip('\n').splitlines()
    boundary = next(i for i, line in enumerate(lines) if line == 'chmod +x /tmp/grpc-probe')
    tail = lines[boundary:] + ['echo ' + end]
    # Empty shell quotes keep even a wrapped input echo from being an exact
    # standalone static marker. Actual shell output is unchanged.
    tail = [line + "''" if re.fullmatch(r'echo [A-Za-z0-9_]+', line) else line for line in tail]
    final_line = '; '.join(tail)
    if len(final_line) > 768:
        raise ValueError('Capture command exceeds reviewed shell-line bound')
    commands = 'echo ' + begin + '\n' + '\n'.join(lines[:boundary]) + '\n' + final_line + '\n'
    output.with_suffix('.commands').write_text(commands)
    return {'stage': stage, 'begin': begin, 'end': end, 'method': method, 'target_c': target,
            'protobuf_hex': protobuf.hex(), 'packet_sha256': hashlib.sha256(packet).hexdigest(),
            'client_timeout_guest_seconds': 5,
            'response_cardinality': 'server-streaming-two-messages-cancel' if method == 'GetStatus' else 'unary',
            'commands': commands}


def verify_capture(text, request):
    region = ready.bounded_region(text, request['begin'], request['end'])
    if region is None:
        return None
    for marker in ('READY_CLIENT_STATUS', 'GRPC_PROBE_TRANSPORT_EXIT'):
        expected_status = str(snapshot.SNAPSHOT_CANCELLED) if request['method'] == 'GetStatus' else '0'
        if re.findall(r'(?m)^' + marker + r'=(\d+)\r?\n', region) != [expected_status]:
            raise ValueError('Uncertain or unsuccessful transport; never retry')
    if len(ready.marker_matches(region, 'GRPC_PROBE_DONE')) != 1:
        raise ValueError('Missing or duplicate probe completion')
    raw = ready.bounded_region(region, ready.RAW_BEGIN, ready.RAW_END)
    if raw is None:
        raise ValueError('Incomplete raw response capture')
    data = ready.read_od(raw)
    protobufs = (snapshot.snapshot_protobufs(data, ready.decode_headers) if request['method'] == 'GetStatus'
                 else [xyz.unary_protobuf(data)])
    protobuf = protobufs[-1]
    result = {'transport_complete': True, 'transport_exit_status': 0,
              'response_sha256': hashlib.sha256(data).hexdigest(), 'response_protobuf_hex': protobuf.hex(),
              'physical_completion_proven': False}
    if request['method'] == 'PrinterState':
        result['ready_response'] = ready.state_response(data)
    elif request['method'] == 'GetStatus':
        samples = [temperature.decode_get_status_temperatures(pb) for pb in protobufs]
        sample = samples[-1]
        result['captured_native_messages'] = samples
        result['captured_message_protobuf_hexs'] = [pb.hex() for pb in protobufs]
        result['selected_native_message_index'] = 2
        result['native_temperatures'] = {h: {'current_c': v['current'], 'target_c': v['target']}
                                         for h, v in sample.items()}
        result.update(transport_complete=False, transport_exit_status=snapshot.SNAPSHOT_CANCELLED,
                      two_stream_messages_validated=True, unary_rpc_completion=False, grpc_trailers_observed=False,
                      local_cancel_frame_sent=True, local_socket_shutdown_and_close=True,
                      remote_cancellation_acknowledged=False,
                      stream_scope='Two validated messages, sequence2 selected regardless of content; local CANCEL+close. No terminal RPC status.')
    else:
        decoded = errors.decode_response(protobuf)
        result.update(decoded=decoded, rpc_acceptance_verified=not decoded['error_reported'])
    return result


# Exact rendered messages and source-line identifiers corroborated by the
# original ELF templates/control paths plus prior successful native starts.
# This is not a generic error suppression rule. Paths, ENOENT, source IDs and
# severity must all match; the exceptions apply strictly before native ready.
KNOWN_STARTUP_AUXILIARY = {
    'Unable to read config file /app/etc/avata_main_mutable.cfg': (218, 'optional mutable overlay absent'),
    'filament hub config file open failed: No such file or directory': (123, 'absent auxiliary filament-hub configuration'),
    'Unable to open config file /app/etc/ace_list.json': (360, 'absent auxiliary ACE list'),
    'start wpa_supplicant failed, command: killall wpa_supplicant 2> /dev/null; wpa_supplicant -Dnl80211 -i wlan0 -c /app/etc/wpa_supplicant.conf -B': (58, 'absent emulated Wi-Fi service'),
    'wifi init failed': (36, 'absent emulated Wi-Fi service'),
}


class NativeErrorReview:
    """Retain startup errors separately; never suppress an unknown native guard.

    First-ready timestamps and error timestamps are both original native-log
    timestamps. No controller/thermal clock is mixed into this comparison.
    A readiness line arriving later retroactively invalidates any startup-only
    exception whose native timestamp was actually at/after native ready.
    """
    def __init__(self):
        self.seen = set()
        self.ready_stamp = None
        self.startup_errors = []
        self.known_startup_errors = []
        self.failures = []
        self.known_camera = []
        self._known_stamps = []

    def observe(self, text):
        entries = xyz.native_entries(text)
        stamps = [stamp for line, stamp, severity, message in entries
                  if severity == 'info' and re.fullmatch(r'Printer is ready at [0-9]+\.[0-9]+\.', message)]
        if stamps:
            first = min(stamps)
            self.ready_stamp = min(self.ready_stamp, first) if self.ready_stamp is not None else first
        for line, stamp in self._known_stamps:
            if self.ready_stamp is not None and stamp >= self.ready_stamp and line not in self.failures:
                self.failures.append(line)
        new = []
        for line, stamp, severity, message in entries:
            if line in self.seen:
                continue
            self.seen.add(line)
            new.append((line, stamp, severity, message))
            startup = self.ready_stamp is None or stamp < self.ready_stamp
            if startup and severity in ('error', 'critical'):
                self.startup_errors.append(line)
            if severity == 'error' and message == xyz.KNOWN_ABSENT_VIDEO_SERVICE:
                self.known_camera.append(line)
                continue
            known = KNOWN_STARTUP_AUXILIARY.get(message)
            source = re.search(r'\] \[(?:error|critical)\] \[(\d+)\] ', line)
            if (startup and severity == 'error' and known is not None and source is not None and
                    int(source[1]) == known[0]):
                self.known_startup_errors.append({'line': line, 'context': known[1],
                    'classification': 'exact known auxiliary startup failure; readiness still required',
                    'source_evidence': 'startup-error-review/source-evidence.json',
                    'successful_startup_evidence': 'startup-error-review/captured-startups.json'})
                self._known_stamps.append((line, stamp))
            elif xyz.native_failure(severity, message):
                self.failures.append(line)
        return new


def finite(value, name):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Nonfinite ' + name)
    return result


class ThermalTrace:
    """Append-only passive reader. Clocks stay in their original domains."""
    def __init__(self, heater):
        self.heater = heater
        self.prefix = b''
        self.last_time = None
        self.last_update = None
        self.latest = None
        self.last_growth_controller_ns = None
        self.rows = 0
        self.samples = 0
        self.last_periodic_us = None
        self.max_temperature = None
        self.physical_band_start_us = None
        self.physical_band_duration_s = 0
        self.off_start_us = None
        self.off_start_temperature = None
        self.off_duration_s = 0
        self.cooling_c = 0
        self.target_observation = False
        self.faults_seen = set()

    def consume(self, raw, controller_ns, *, target=None, zero_confirmed=False):
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError('Thermal trace exceeds bounded capture size')
        complete = raw[:raw.rfind(b'\n') + 1]
        if not complete.startswith(self.prefix):
            raise ValueError('Thermal trace truncated or rewritten')
        if complete == self.prefix:
            return []
        all_rows = list(csv.DictReader(io.StringIO(complete.decode('ascii'))))
        if len(all_rows) < self.rows or len(all_rows) > 100000:
            raise ValueError('Thermal trace count invalid or capacity reached')
        new = []
        for row in all_rows[self.rows:]:
            pin = 'pb8_level' if self.heater == 'nozzle' else 'pa0_level'
            stamp = int(row['time_us'])
            updates = int(row['thermal_updates'])
            temp = finite(row['physical_temperature_c'], 'physical temperature')
            adc, level = int(row['published_adc_code']), int(row[pin])
            duty = finite(row['last_heater_duty'], 'heater duty')
            if (stamp < 0 or updates < 0 or not 0 <= adc <= 4095 or level not in (0, 1) or
                    not 0 <= duty <= 1 or finite(row['last_fan_duty'], 'fan duty') != 0):
                raise ValueError('Invalid thermal telemetry or unexpected fan thermal coupling')
            if self.last_time is not None and (stamp < self.last_time or updates < self.last_update):
                raise ValueError('Backwards physical observer time/update counter')
            if self.last_time is not None and stamp - self.last_time > 500000:
                raise ValueError('Missing physical telemetry interval')
            if row['event'] == 'sample':
                if self.last_periodic_us is not None and stamp - self.last_periodic_us > 500000:
                    raise ValueError('Missing periodic thermal samples')
                self.last_periodic_us = stamp
                self.samples += 1
            faults = [key for key in ('model_overtemperature', 'model_heater_latched_off') if row[key] != '0']
            if self.heater == 'nozzle' and row.get('curve_out_of_range') != '0':
                faults.append('curve_out_of_range')
            if row['sensor_fault'] != 'none' or adc in (0, 4095):
                faults.append('sensor_fault_or_rail')
            if row['sensor_curve'] != ('NTC ZM3863 HNS112HC4570G0' if self.heater == 'nozzle' else 'B3950 100k 4700ohm illustrative divider'):
                raise ValueError('Unexpected sensor curve')
            normalized = {'time_us': stamp, 'physical_c': temp, 'adc_code': adc, 'level': level,
                          'duty': duty, 'faults': faults, 'thermal_updates': updates, 'event': row['event']}
            if self.heater == 'nozzle':
                normalized['pb9_level'] = int(row['pb9_level'])
            self.faults_seen.update(faults)
            self.max_temperature = temp if self.max_temperature is None else max(self.max_temperature, temp)
            if target is not None and not faults and abs(temp - target) <= 2:
                if self.physical_band_start_us is None:
                    self.physical_band_start_us = stamp
                self.physical_band_duration_s = (stamp - self.physical_band_start_us) / 1e6
            else:
                self.physical_band_start_us = None
                self.physical_band_duration_s = 0
            if zero_confirmed and level == 0 and duty == 0:
                if self.off_start_us is None:
                    self.off_start_us, self.off_start_temperature = stamp, temp
                self.off_duration_s = (stamp - self.off_start_us) / 1e6
                self.cooling_c = self.off_start_temperature - temp
            else:
                self.off_start_us, self.off_start_temperature = None, None
                self.off_duration_s, self.cooling_c = 0, 0
            self.latest = normalized
            self.last_time, self.last_update = stamp, updates
            new.append(normalized)
        self.rows = len(all_rows)
        self.prefix = complete
        if new:
            self.last_growth_controller_ns = controller_ns
        return new

    def stale(self, controller_ns):
        return self.last_growth_controller_ns is None or controller_ns - self.last_growth_controller_ns > 3 * NS

    def summary(self):
        return {'rows': self.rows, 'periodic_samples': self.samples, 'latest': self.latest,
                'max_physical_c': self.max_temperature, 'faults_seen': sorted(self.faults_seen), 'physical_band_duration_s': self.physical_band_duration_s,
                'actual_off_duration_s': self.off_duration_s, 'physical_cooling_c': self.cooling_c}


class Regulation:
    """Report-only independent physical and native sample windows, never a PID flag."""
    def __init__(self, heater, profile_selection='synthetic-calibration'):
        self.rules = PROFILE_RULES[profile_selection]
        self.heater, self.target = heater, TARGETS[heater]
        self.native_band_start_ns = None
        self.native_band_duration_s = 0
        self.last_native_ns = None
        self.native_samples = []
        self.response_accepted = False
        self.native_target_observed = False
        self.target_queue_ns = None
        self.response_accepted_ns = None
        self.baseline_physical = None
        self.failure = None
        self.zero_response_verified = False

    def observe_native(self, sample, controller_ns, expected_target):
        # Decoder supplies native interpreted values, not ADC/model inversion.
        for heater in TARGETS:
            for key in ('current_c', 'target_c'):
                finite(sample[heater][key], 'native ' + heater + ' ' + key)
        other = 'bed' if self.heater == 'nozzle' else 'nozzle'
        if sample[other]['target_c'] != 0:
            self.failure = 'Unexpected demand on the other heater'
        native = sample[self.heater]
        if expected_target is not None and native['target_c'] != expected_target:
            self.failure = 'Native target differs from expected target'
        if self.last_native_ns is not None and controller_ns - self.last_native_ns > 5 * NS:
            self.failure = 'Gap in native interpreted temperature samples'
            self.native_band_start_ns = None
        self.last_native_ns = controller_ns
        self.native_samples.append({'observed_controller_ns': controller_ns, **sample})
        if len(self.native_samples) > 400:
            raise ValueError('Native sample budget exceeded')
        self.native_target_observed |= expected_target == self.target and native['target_c'] == self.target
        if expected_target == self.target and abs(native['current_c'] - self.target) <= 2:
            if self.native_band_start_ns is None:
                self.native_band_start_ns = controller_ns
            self.native_band_duration_s = (controller_ns - self.native_band_start_ns) / NS
        else:
            self.native_band_start_ns = None
            self.native_band_duration_s = 0

    def stop_reason(self, traces, now):
        if self.failure:
            return self.failure
        for heater, trace in traces.items():
            if trace.stale(now):
                return 'Stale ' + heater + ' thermal telemetry'
            if trace.faults_seen or trace.latest['faults']:
                return heater + ' sensor/model fault: ' + ', '.join(sorted(trace.faults_seen) or trace.latest['faults'])
            if trace.latest['physical_c'] >= CAPS[heater] or trace.max_temperature is not None and trace.max_temperature >= CAPS[heater]:
                return heater + ' external physical-temperature cap reached'
        if self.last_native_ns is None or now - self.last_native_ns > 5 * NS:
            return 'Stale native interpreted temperature'
        # Queue time is conservatively earlier than the unobserved acceptance
        # instant. Never add a guessed guest/observer clock offset.
        if self.target_queue_ns is not None and now - self.target_queue_ns >= self.rules['zero_lead_seconds'] * NS:
            return str(self.rules['zero_lead_seconds']) + '-second normal-zero lead-in to hard' + str(self.rules['heat_cap_seconds']) + '-second conservative virtual cap'
        if self.response_accepted and self.native_target_observed and (
                traces[self.heater].physical_band_duration_s >= self.rules['band_seconds'] and
                self.native_band_duration_s >= self.rules['band_seconds']):
            return 'Independent physical and native target±2°C windows each sustained' + str(self.rules['band_seconds']) + 's'
        return None


def validate_profile(directory, selection='synthetic-calibration'):
    profile = json.loads((directory / 'thermal-profile.json').read_text())
    shared = json.loads((directory / 'shared-profile.json').read_text())
    if shared.get('thermal_profile') != profile:
        raise ValueError('Shared/profile thermal selection differs')
    rules = PROFILE_RULES[selection]
    required = {'selection': selection, 'hypothetical_fixture': True, 'global_quantum_ns': 1000,
                'firmware_changes': False, 'native_guards_unchanged': True,
                'direct_duty_or_temperature_overrides': False}
    if any(profile.get(k) != v for k, v in required.items()):
        raise ValueError('Missing or incompatible explicit synthetic thermal profile')
    if rules['factor'] != 1:
        fast_required = {'functional_acceleration_factor': rules['factor'], 'unrealistic_dynamics': True,
                         'real_pid_validation': False, 'capacity_scaling_only': True,
                         'native_pid_and_sensor_smoothing_unchanged': True,
                         'emulation_clock_scale': 1, 'automatic_factor_fallback': False}
        if any(profile.get(k) != v for k, v in fast_required.items()):
            raise ValueError('Missing or incompatible explicit accelerated functional metadata')
        selected_scenario = ROOT / 'printer-shared-mcu/experimental/accelerated-functional-thermal/profiles/4x/parameters.json'
        if profile.get('accelerated_scenario') != json.loads(selected_scenario.read_text()):
            raise ValueError('Accelerated scenario differs from fixed reviewed4x parameters')
        helper_path = ROOT / 'rv1106-at32-link/scripts/accelerated_thermal_profile_selection.py'
        baseline_path = ROOT / 'rv1106-at32-link/scripts/thermal_profile_selection.py'
        if (profile.get('integration_helper_sha256') != hashlib.sha256(helper_path.read_bytes()).hexdigest() or
                profile.get('baseline_integration_helper_sha256') != hashlib.sha256(baseline_path.read_bytes()).hexdigest()):
            raise ValueError('Accelerated integration helper identity mismatch')
    for heater, values in {'nozzle': (60, 20 / rules['factor'], .2, 400, 0),
                           'bed': (200, 600 / rules['factor'], 1.5, 150, 8)}.items():
        expected = dict(zip(('heater_power_w', 'heat_capacity_j_per_k', 'conductance_w_per_k',
                             'environment_maximum_c', 'adc_channel'), values), ambient_c=25, pull_resistance_ohm=4700)
        if any(profile['parameters'][heater].get(k) != v for k, v in expected.items()):
            raise ValueError('Unexpected hypothetical thermal parameters')
    return profile


def read_graceful_stop(path):
    """Dedicated intent, never a native fault or a direct console command."""
    if not path.exists():
        return None
    raw = path.read_bytes()
    if len(raw) > 4096:
        raise ValueError('Graceful-stop intent exceeds4096bytes')
    intent = json.loads(raw)
    if (type(intent) is not dict or set(intent) != {'action', 'reason'} or
            intent['action'] != 'stop_heating' or type(intent['reason']) is not str or
            not 1 <= len(intent['reason']) <= 1000 or
            any(ord(ch) < 32 for ch in intent['reason'])):
        raise ValueError('Invalid graceful-stop intent; require action stop_heating and plain reason')
    return dict(intent, sha256=hashlib.sha256(raw).hexdigest())


def verify_dependencies():
    expected = json.loads((HERE / 'reviewed-dependencies.json').read_text())
    for relative, digest in expected.items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != digest:
            raise ValueError('Reviewed dependency changed: ' + relative)
    return expected


def final_status_issues(directory):
    issues = []
    for heater in TARGETS:
        path = directory / (heater + '-thermal-live-status.json')
        if not path.exists():
            issues.append('Missing ' + path.name)
            continue
        status = json.loads(path.read_text())
        for key in ('dropped_rows', 'stream_dropped_rows', 'stream_error_count'):
            if status.get(key) != 0:
                issues.append(path.name + ': missing/nonzero ' + key)
        for key in ('capacity_reached', 'stream_capacity_reached', 'stream_write_outcome_uncertain', 'streaming'):
            if status.get(key) is not False:
                issues.append(path.name + ': missing/true ' + key)
        if status.get('last_stream_error'):
            issues.append(path.name + ': ' + str(status['last_stream_error']))
        trace = directory / (heater + '-thermal-live.csv')
        if not trace.exists() or status.get('stream_rows_written') != len(list(csv.DictReader(io.StringIO(trace.read_text())))):
            issues.append('Final stream row count differs for ' + heater)
        binding_path = directory / (heater + '-heater-binding.json')
        if not binding_path.exists():
            issues.append('Missing ' + binding_path.name)
        else:
            binding = json.loads(binding_path.read_text())
            for key in ('direct_duty_override_used', 'temperature_override_used'):
                if binding.get(key) is not False:
                    issues.append(binding_path.name + ': missing/true ' + key)
            levelkey = 'current_resolved_pb8_level' if heater == 'nozzle' else 'current_resolved_level'
            if binding.get(levelkey) is not False:
                issues.append('Final actual heater GPIO not low for ' + heater)
    return issues


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_name')
    parser.add_argument('--thermal-profile', choices=PROFILE_RULES, required=True)
    parser.add_argument('--heater', choices=TARGETS, required=True)
    parser.add_argument('--nozzle-tmc-model', choices=['fixed', 'autobaud'], required=True)
    parser.add_argument('--execute', action='store_true', help='Explicitly launch virtual firmware; default prepares only')
    parser.add_argument('--seconds', type=int, default=28800, help='Wall cap, default8h for ~74x slower-than-virtual runs')
    parser.add_argument('--cleanup-seconds', type=int, default=120)
    args = parser.parse_args(argv)
    if not re.fullmatch('[A-Za-z0-9_-]+', args.run_name):
        parser.error('Invalid run name')
    if not 60 <= args.seconds <= 43200 or not 1 <= args.cleanup_seconds <= 300:
        parser.error('Wall cap must be60..43200s; cleanup1..300s')
    return args


def main(argv=None):
    args = parse_args(argv)
    if not args.execute:
        directory = HERE / 'prepared' / args.run_name
        directory.mkdir(parents=True, exist_ok=False)
        for stage, method, target in [('ready', 'PrinterState', None), ('target', METHODS[args.heater], TARGETS[args.heater]),
                                      ('zero', METHODS[args.heater], 0)]:
            prepare_request(directory, stage, 'PREPARE_ONLY', method, target)
        print('Prepared exact requests only; no emulator or generated client executed: ' + str(directory))
        return 0
    return run(args)


def run(args):
    dependencies = verify_dependencies()
    rules = PROFILE_RULES[args.thermal_profile]
    accelerated = rules['factor'] != 1
    directory = ROOT / 'runs' / args.run_name
    if directory.exists():
        raise SystemExit('Run directory already exists; never overwrite or retry')
    # Only explicit reviewed startup settings. Do not inherit override/QEMU/clock knobs.
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'HOME')}
    env.update(RUN_SECONDS=str(args.seconds + args.cleanup_seconds), THERMAL_PROFILE=args.thermal_profile,
               Z_PROBE_PROFILE='none', GLOBAL_QUANTUM_US='1', ICOUNT_SHIFT='0',
               NOZZLE_TMC_MODEL=args.nozzle_tmc_model, RECOVERED_NOZZLE_NTC='1',
               ASSUMED_XY_DIAG_CABLE='1', MOTOR_ENABLE_WIRING='mcu-control-only',
               PASSIVE_MOTOR_TRACE='0', PASSIVE_CONTACT_TRACE='0', PASSIVE_NOZZLE_TRACE='0',
               PASSIVE_TMC_TRACE='0', PASSIVE_HOMING_GPIO='0', NATIVE_NOZZLE_HEATER='0')
    record = {'scope': ('Accelerated functional target-band and safe-off test; not real PID validation' if accelerated else
                        'Explicit hypothetical thermal regulation test, separate normal heater invocation'),
              'thermal_profile_selection': args.thermal_profile, 'functional_acceleration_factor': rules['factor'],
              'real_pid_validation': False, 'functional_band_criterion_met': False,
              'complete_functional_evidence': False, 'graceful_stop_intent': None,
              'graceful_stop_completed': False, 'complete_graceful_stop_evidence': False, 'console_batches': [],
              'heater': args.heater, 'target_c': TARGETS[args.heater], 'phase': 'waiting_ready',
              'reviewed_dependencies': dependencies, 'requests': [], 'native_failure_lines': [], 'known_absent_camera_lines': [],
              'native_target_logs': [], 'source_or_clock_failure': False,
              'regulation_criterion_met': False, 'pid_calibration_completed': False,
              'print_completed': False, 'zero_response_verified': False,
              'native_zero_target_observed': False, 'actual_heater_off_observed': False,
              'physical_cooling_observed': False, 'final_export_requested': False,
              'clock_note': 'Controller time, source-local thermal times and native log stamps remain separate. '
                            'Cap begins conservatively at queue time, earlier than native acceptance. '
                            'Physical/native band windows are each measured in their own observed time domain. '
                            'Native GetStatus temperatures are rounded whole degrees.',
              'limits': {'heat_virtual_seconds': rules['heat_cap_seconds'],
                         'zero_lead_virtual_seconds': rules['zero_lead_seconds'],
                         'physical_and_native_band_seconds': rules['band_seconds'], 'physical_cap_c': CAPS[args.heater],
                         'cooling_virtual_seconds': 30, 'wall_seconds': args.seconds,
                         'native_status_cadence_virtual_s': 1, 'native_status_max_age_s': 5,
                         'baseline_max_successful_snapshots': 3, 'baseline_virtual_seconds': 10}}
    traces = {heater: ThermalTrace(heater) for heater in TARGETS}
    error_review = NativeErrorReview()
    record['startup_error_lines'] = error_review.startup_errors
    record['known_auxiliary_startup_errors'] = error_review.known_startup_errors
    record['native_failure_lines'] = error_review.failures
    record['known_absent_camera_lines'] = error_review.known_camera
    regulation = Regulation(args.heater, args.thermal_profile)
    token = secrets.token_hex(12)
    previous_console, previous_now, epoch = '', 0, None
    pending, pending_entry, request_start, request_clock = None, None, None, None
    log_pending, next_log, next_native, status_index = None, 0, 0, 0
    start = last_clock_wall = time.monotonic()
    zero_clock = None
    baseline_clock = None
    observed_stop_reason = None
    graceful_intent = None
    console_batch = None

    def save():
        if not directory.exists():
            return
        record['thermal_observations'] = {k: v.summary() for k, v in traces.items()}
        record['native_samples'] = regulation.native_samples
        record['native_target_observed'] = regulation.native_target_observed
        record['native_band_duration_s'] = regulation.native_band_duration_s
        record['target_response_accepted'] = regulation.response_accepted
        record['accepted_response_observed_controller_ns'] = regulation.response_accepted_ns
        tmp = directory / 'thermal-observation.json.tmp'
        tmp.write_text(json.dumps(record, indent=2) + '\n')
        tmp.replace(directory / 'thermal-observation.json')

    def stop(reason):
        record['stop_reason'] = reason
        if directory.exists():
            try:
                with (directory / 'stop-request').open('x') as stream:
                    stream.write(reason + '\n')
            except FileExistsError:
                pass
            record['final_export_requested'] = True

    def append(commands, kind, marker, now):
        nonlocal console_batch
        if console_batch is not None:
            raise ValueError('Console batch overlap forbidden: ' + console_batch['kind'])
        console_batch = {'kind': kind, 'completion_marker': marker, 'queued_controller_ns': now,
                         'queue_outcome': 'uncertain', 'commands_sha256': hashlib.sha256(commands.encode()).hexdigest()}
        record['console_batches'].append(console_batch)
        save()
        with (directory / 'console-input.commands').open('a') as stream:
            stream.write(commands)
            stream.flush()
        console_batch['queue_outcome'] = 'appended'
        save()

    def finish_batch(kind, now):
        nonlocal console_batch
        if console_batch is None or console_batch['kind'] != kind:
            raise ValueError('Console completion without matching batch')
        console_batch['validated_completion_controller_ns'] = now
        console_batch = None

    def latch_intent(now):
        nonlocal graceful_intent
        if graceful_intent is None:
            graceful_intent = read_graceful_stop(directory / GRACEFUL_STOP_FILE)
            if graceful_intent is not None:
                record['graceful_stop_intent'] = dict(graceful_intent, observed_controller_ns=now,
                    pending_rpc=pending['stage'] if pending is not None else None,
                    pending_console_batch=console_batch['kind'] if console_batch is not None else None)

    def queue(stage, method, target, text, now):
        nonlocal pending, pending_entry, request_start, request_clock
        if stage == 'target':
            latch_intent(now)
            if graceful_intent is not None:
                return False
        if (pending is not None or log_pending is not None or console_batch is not None or
                any(item['stage'] == stage for item in record['requests'])):
            raise ValueError('Duplicate or overlapping RPC request forbidden')
        pending_entry = {'stage': stage, 'generation_attempted': True, 'queue_outcome': 'not_attempted'}
        record['requests'].append(pending_entry)
        save()
        prepared = prepare_request(directory, stage, token, method, target)
        if (directory / 'stop-request').exists():
            raise ValueError('Stop arrived during request preparation; no further command')
        if stage == 'target':
            latch_intent(now)  # Recheck after generation, immediately before the one append.
            if graceful_intent is not None:
                pending_entry['queue_outcome'] = 'cancelled_before_append'
                save()
                return False
        pending_entry.update({k: v for k, v in prepared.items() if k != 'commands'})
        pending_entry.update(queue_outcome='uncertain', queued_controller_ns=now)
        pending, request_start, request_clock = prepared, len(text), now
        save()  # Persist uncertain queue BEFORE append. Never retry a partial write.
        append(prepared['commands'], 'rpc:' + stage, prepared['end'], now)
        pending_entry['queue_outcome'] = 'appended'
        if stage == 'target':
            regulation.target_queue_ns = now
        if stage == 'zero':
            record['phase'] = 'zero_response_pending'
        save()
        return True

    process = subprocess.Popen([str(ROOT / 'rv1106-at32-link/scripts/run_native_event_fixture.sh'), args.run_name],
                               env=env, start_new_session=True)
    try:
        while process.poll() is None:
            wall = time.monotonic()
            if (directory / 'stop-request').exists():
                record['phase'] = 'external_stop_requested'
                break
            if wall - start >= args.seconds:
                stop('Total wall limit; stopped virtual run without claiming cleared target')
                record['phase'] = 'wall_limit'
                break
            if wall - last_clock_wall > 300:
                raise ValueError('Controller virtual clock made no progress for300wall seconds')
            console = directory / 'console.bin'
            if not console.exists():
                time.sleep(.2)
                continue
            if console.stat().st_size > MAX_CONSOLE:
                raise ValueError('Console budget exceeded')
            text = console.read_text(errors='replace')
            if not text.startswith(previous_console):
                raise ValueError('Console truncated or rewritten')
            previous_console = text
            clock_path = directory / 'virtual-time.json'
            if not clock_path.exists():
                time.sleep(.2)
                continue
            clock = json.loads(clock_path.read_text())
            now = clock['virtual_time_ns']
            if (type(now) is not int or now < previous_now or clock.get('time_went_backwards') is not False or
                    clock.get('enabled') is not True or not clock.get('epoch') or
                    epoch is not None and clock['epoch'] != epoch):
                raise ValueError('Invalid, restarted or backwards controller virtual clock')
            epoch = clock['epoch']
            if now != previous_now:
                last_clock_wall = wall
            previous_now = now
            record['last_controller_virtual_time_ns'] = now
            latch_intent(now)
            if log_pending is not None:
                matches = ready.marker_matches(text[log_pending[1]:], log_pending[0])
                if len(matches) > 1:
                    raise ValueError('Duplicate log batch completion marker')
                if matches:
                    finish_batch('log', now)
                    log_pending = None
                elif now - log_pending[2] > 3 * NS:
                    raise ValueError('Console log batch deadline; no further input or RPC')
            for source_name in ('launcher.log', 'renode.log'):
                source_path = directory / source_name
                if source_path.exists():
                    if source_path.stat().st_size > MAX_CONSOLE:
                        raise ValueError('Source log capture budget exceeded: ' + source_name)
                    source_text = source_path.read_text(errors='replace')
                    if re.search(r'There was an error executing command|Unhandled exception|Traceback \(most recent call last\)|Assertion failed|Failed to load platform', source_text, re.I):
                        raise ValueError('Source/monitor failure in ' + source_name)
            if regulation.target_queue_ns is not None and not regulation.zero_response_verified and now - regulation.target_queue_ns >= rules['heat_cap_seconds'] * NS:
                stop('Hard' + str(rules['heat_cap_seconds']) + '-second virtual cap reached before confirmed normal zero; stop without cleared-target claim')
                record['phase'] = 'hard_heat_cap'
                break
            if now > 360 * NS:
                stop('Absolute360-second virtual limit; no target-clear claim')
                record['phase'] = 'absolute_virtual_limit'
                break
            for heater, trace in traces.items():
                path = directory / (heater + '-thermal-live.csv')
                if path.exists():
                    trace.consume(path.read_bytes(), now,
                                  target=TARGETS[heater] if heater == args.heater and regulation.response_accepted else None,
                                  zero_confirmed=heater == args.heater and regulation.zero_response_verified)
            # Exact reviewed startup-only auxiliary errors are retained, not
            # confused with printer/thermal guards. No blanket timestamp floor.
            for line, stamp, severity, message in error_review.observe(text):
                if re.fullmatch(r"Heater '[^']+' target temperature updated to [0-9.]+", message):
                    record['native_target_logs'].append(line)
            if error_review.failures:
                regulation.failure = 'Native fault/error/shutdown evidence'
            # Startup failures are not silently discarded. No high target after them.
            if regulation.failure and regulation.target_queue_ns is None:
                stop(regulation.failure)
                record['phase'] = 'startup_native_failure'
                break
            if pending is not None:
                result = verify_capture(text[request_start:], pending)
                if result is not None:
                    stage = pending['stage']
                    pending_entry['response'] = result
                    pending_entry['response_observed_controller_ns'] = now
                    pending = None
                    finish_batch('rpc:' + stage, now)
                    if stage == 'ready':
                        record['phase'] = 'baseline'
                        baseline_clock = now
                    elif stage == 'target':
                        if not result['rpc_acceptance_verified']:
                            stop('Native target request returned application error; no further heat request')
                            record['phase'] = 'target_rejected'
                            break
                        regulation.response_accepted = True
                        regulation.response_accepted_ns = now
                        record['phase'] = 'heating'
                        next_native = now
                    elif stage == 'zero':
                        record['zero_response_verified'] = result['rpc_acceptance_verified']
                        regulation.zero_response_verified = result['rpc_acceptance_verified']
                        if not regulation.zero_response_verified:
                            stop('Normal target-zero rejected; virtual run stopped, target not claimed cleared')
                            record['phase'] = 'zero_rejected'
                            break
                        zero_clock = now
                        record['phase'] = 'cooling'
                        next_native = now
                    elif stage.startswith('status'):
                        expected = 0 if record['phase'] in ('baseline', 'cooling') else TARGETS[args.heater]
                        regulation.observe_native(result['native_temperatures'], now, expected)
                        if record['phase'] == 'baseline':
                            record['baseline_successful_snapshots'] = record.get('baseline_successful_snapshots', 0) + 1
                            healthy = all(t.latest and not t.stale(now) and not t.latest['faults'] and
                                          t.samples >= 2 and abs(t.latest['physical_c'] - 25) <= 2 and
                                          t.latest['level'] == 0 and t.latest['duty'] == 0 and
                                          t.latest['adc_code'] == (4023 if h == 'nozzle' else 3911)
                                          for h, t in traces.items())
                            native_ok = all(v['target_c'] == 0 and abs(v['current_c'] - 25) <= 3
                                            for v in result['native_temperatures'].values())
                            if not healthy or regulation.failure:
                                raise ValueError('Initial physical/ADC/native target baseline not healthy')
                            if native_ok and graceful_intent is None:
                                regulation.baseline_physical = traces[args.heater].latest['physical_c']
                                if queue('target', METHODS[args.heater], TARGETS[args.heater], text, now):
                                    record['phase'] = 'target_response_pending'
                            elif not native_ok:
                                # r2 genuinely returned a first startup message with
                                # absent current scalars (default0); never relabel
                                # that value as25C. A fresh successful snapshot is
                                # a new observation, not retry of uncertain I/O.
                                record.setdefault('native_baseline_wait_samples', []).append(result['native_temperatures'])
                                if record['baseline_successful_snapshots'] >= 3 or now - baseline_clock >= 10 * NS:
                                    raise ValueError('Native interpreted temperatures did not establish ambient baseline within3successful snapshots/10virtual seconds')
                        elif record['phase'] == 'cooling':
                            record['native_zero_target_observed'] = result['native_temperatures'][args.heater]['target_c'] == 0
                    save()
                elif now - request_clock > 8 * NS:
                    raise ValueError('RPC transport/response deadline; outcome uncertain, no retry')
            if (graceful_intent is not None and regulation.target_queue_ns is None and
                    pending is None and console_batch is None):
                record['phase'] = 'graceful_stopped_before_heat'
                record['graceful_stop_completed'] = True
                stop('Graceful stop before any target command; no heating requested')
                break
            if (record['phase'] == 'waiting_ready' and ready.native_ready(text) and console_batch is None and
                    ready.marker_matches(text, 'COUPLED_STARTUP_COMMANDS_DONE')):
                record['verified_profile'] = validate_profile(directory, args.thermal_profile)
                record['verified_tmc_selection'] = xyz.validate_tmc_manifest(
                    directory, json.loads((directory / 'shared-profile.json').read_text()), args.nozzle_tmc_model)
                queue('ready', 'PrinterState', None, text, now)
                record['phase'] = 'ready_response_pending'
            if record['phase'] == 'baseline' and now - baseline_clock >= 10 * NS:
                raise ValueError('Native baseline observation cap reached before heating')
            if record['phase'] == 'heating':
                reason = ('Graceful stop requested: ' + graceful_intent['reason'] if graceful_intent is not None
                          else regulation.stop_reason(traces, now))
                if reason:
                    observed_stop_reason = observed_stop_reason or reason
                    band_met = reason.startswith('Independent physical and native')
                    record['regulation_criterion_met'] = band_met and not accelerated
                    record['functional_band_criterion_met'] = band_met and accelerated
                    if band_met and 'band_criterion_evidence' not in record:
                        record['band_criterion_evidence'] = {
                            'observed_controller_ns': now, 'physical_observer_latest_us': traces[args.heater].last_time,
                            'physical_band_seconds': traces[args.heater].physical_band_duration_s,
                            'native_band_seconds': regulation.native_band_duration_s,
                            'required_seconds': rules['band_seconds'], 'tolerance_c': 2,
                            'native_last_observed_controller_ns': regulation.last_native_ns,
                            'native_status_sample_count': len(regulation.native_samples),
                            'native_last_sample': regulation.native_samples[-1],
                            'physical_row_count': traces[args.heater].rows,
                            'native_and_physical_clocks_not_equated': True}
                    record['heat_stop_criterion'] = reason
                    if console_batch is None:
                        queue('zero', METHODS[args.heater], 0, text, now)
                elif observed_stop_reason is not None and console_batch is None:
                    queue('zero', METHODS[args.heater], 0, text, now)
            if record['phase'] == 'target_response_pending':
                danger = any(t.latest and (t.latest['faults'] or t.latest['physical_c'] >= CAPS[h]) for h, t in traces.items())
                if danger or regulation.failure:
                    stop('Fault/cap before target transport confirmed; virtual stop, no retry or clear claim')
                    record['phase'] = 'target_outcome_uncertain'
                    break
            if record['phase'] == 'cooling':
                if regulation.failure and record['native_samples'] and record['native_samples'][-1][args.heater]['target_c'] != 0:
                    stop('Native target-zero not observed; no further commands')
                    record['phase'] = 'native_zero_unverified'
                    break
                if any(t.stale(now) for t in traces.values()):
                    stop('Stale cooling telemetry; no off/cooling claim')
                    record['phase'] = 'cooling_telemetry_stale'
                    break
                trace = traces[args.heater]
                record['actual_heater_off_observed'] = trace.off_duration_s >= 5
                record['physical_cooling_observed'] = trace.off_duration_s >= 5 and trace.cooling_c >= .1
                if (record['native_zero_target_observed'] and record['actual_heater_off_observed'] and
                        record['physical_cooling_observed'] and console_batch is None):
                    record['graceful_stop_completed'] = graceful_intent is not None
                    record['phase'] = 'observed_and_cleared'
                    stop('Normal zero response, native zero target, actual heater low and subsequent cooling observed')
                    break
                if now - zero_clock >= 30 * NS:
                    record['phase'] = 'cooling_unverified'
                    stop('Cooling observation cap; preserve missing off/cooling/native-target evidence')
                    break
            # One shared console latch covers RPC uploads, captures AND log reads.
            # A log batch is one shell input line, so all echo precedes its output.
            # Normal zero above has priority over both status and routine log reads.
            if (console_batch is None and now >= next_log and
                    ready.marker_matches(text, 'COUPLED_STARTUP_COMMANDS_DONE')):
                marker = 'THERMAL_LOG_END_' + token + '_' + str(now)
                log_pending = (marker, len(text), now)
                append('tail -100 /data/main.stdout; tail -100 /data/logs/avata_main.log; echo ' + marker + "''\n",
                       'log', marker, now)
                next_log = now + 2 * NS
            if (console_batch is None and record['phase'] in ('baseline', 'heating', 'cooling') and
                    now >= next_native and (graceful_intent is None or record['phase'] == 'cooling')):
                status_index += 1
                queue('status%03d' % status_index, 'GetStatus', None, text, now)
                next_native = now + NS
            save()
            time.sleep(.2)
        else:
            record['phase'] = 'launcher_ended_before_controller_completion'
    except Exception as error:
        record.update(phase='error', error=str(error), source_or_clock_failure=True)
        try:
            stop('Controller/transport/source error; stopped virtual run; no target-clear claim: ' + str(error))
        except OSError as stop_error:
            record['stop_request_error'] = str(stop_error)
    finally:
        try:
            record['launcher_exit_code'] = process.wait(timeout=args.cleanup_seconds)
        except subprocess.TimeoutExpired:
            record['cleanup_limit_exceeded'] = True
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    pass
                try:
                    record['launcher_exit_code'] = process.wait(timeout=5)
                    break
                except subprocess.TimeoutExpired:
                    record['launcher_exit_code'] = None
        record['evidence_issues'] = []
        try:
            record['evidence_issues'] = final_status_issues(directory)
        except (ValueError, OSError) as error:
            record['evidence_issues'].append(str(error))
        try:
            verify_dependencies()
            record['independent_gpio_replay'] = {h: replay.analyze(directory / (h + '-thermal-live.csv'), h, profile_selection=args.thermal_profile) for h in TARGETS}
        except (ValueError, OSError, KeyError) as error:
            record['evidence_issues'].append('Independent causal/source review: ' + str(error))
        if record.get('cleanup_limit_exceeded'):
            record['evidence_issues'].append('Cleanup limit exceeded; final export not confirmed')
        record['complete_regulation_evidence'] = bool(
            record['regulation_criterion_met'] and record['phase'] == 'observed_and_cleared' and
            not record['evidence_issues'] and not record['native_failure_lines'] and graceful_intent is None and
            record.get('launcher_exit_code') == 0)
        record['complete_functional_evidence'] = bool(
            accelerated and record['functional_band_criterion_met'] and record['phase'] == 'observed_and_cleared' and
            not record['evidence_issues'] and not record['native_failure_lines'] and graceful_intent is None and
            record.get('launcher_exit_code') == 0)
        record['complete_graceful_stop_evidence'] = bool(
            record['graceful_stop_completed'] and record['phase'] in ('observed_and_cleared', 'graceful_stopped_before_heat') and
            not record['evidence_issues'] and record.get('launcher_exit_code') == 0)
        save()
    return 0 if record.get('complete_regulation_evidence') or record.get('complete_functional_evidence') else 2


if __name__ == '__main__':
    raise SystemExit(main())
