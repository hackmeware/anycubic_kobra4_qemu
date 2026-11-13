#!/usr/bin/env python3
"""One fresh read-only ambient observation; only the parent launches this file.

New closure, unchanged Legacy scalar fixture. No thermal controller, setter,
motion/print/PID/zero request, process memory inspection, or historical gate
repair. Deadline stops are sampled, not strict bounds on scheduler latency.
"""
if not __debug__:
    raise SystemExit('Ambient observer refuses optimized Python before imports or I/O')

import argparse
import csv
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import types
import time
PROTOCOL_SHA256 = '6d4d12fd2384a598f5a14e1d374ea937c1cbcdb7193f1832af4032ae04a8c929'
_protocol_path = Path(__file__).resolve().with_name('protocol.py')
if _protocol_path.is_symlink():
    raise ValueError('Protocol source may not be a symlink')
_protocol_source = _protocol_path.read_bytes()
if hashlib.sha256(_protocol_source).hexdigest() != PROTOCOL_SHA256:
    raise ValueError('Ambient protocol source identity mismatch')
protocol = types.ModuleType('ambient_readonly_protocol')
protocol.__file__ = str(_protocol_path)
exec(compile(_protocol_source, str(_protocol_path), 'exec'), protocol.__dict__)

ROOT = Path(__file__).resolve().parents[3]
ACTIVE_SECONDS = 868
POST_READY_SECONDS = 180
CAPTURE_ENTRY_SECONDS = 680
SHARED_STOP_NS = 15_000_000_000
OBSERVATION_FRESH_NS = 5_000_000_000
CLEANUP_SECONDS = 8
MAX_CONSOLE = 32 * 1024 * 1024
REPORT_NAME = 'ambient-observation.json'
READY_NAME = 'ready-prerequisite.json'
BASELINE_CONSOLE = 'rv1106-at32-link/experimental/ambient-observation/evidence/ready-baseline.console.txt'
BASELINE_SHA256 = '7fa36cad2dcb78a71d49880c2aeb02c9043252870cde24d9612480c40e3e8c4f'
AUXILIARY = {
    'Unable to read config file /app/etc/avata_main_mutable.cfg': 218,
    'filament hub config file open failed: No such file or directory': 123,
    'Unable to open config file /app/etc/ace_list.json': 360,
    'start wpa_supplicant failed, command: killall wpa_supplicant 2> /dev/null; wpa_supplicant -Dnl80211 -i wlan0 -c /app/etc/wpa_supplicant.conf -B': 58,
    'wifi init failed': 36,
}
VIDEO = 'GetVideoState failed: failed to connect to all addresses; last error: UNKNOWN: ipv4:127.0.0.1:50052: Failed to connect to remote host: Connection refused'
NATIVE_REVIEW_SCOPE = 'captured console and bounded log tails only; complete native log coverage not proven'
CSV_HEADER = 'time_us,event,changed_pin,changed_level,pb8_level,pb9_level,pb8_config,pb9_config,pb8_latch,pb9_latch,physical_temperature_c,published_adc_code,sensor_curve,sensor_fault,curve_out_of_range,model_overtemperature,model_heater_latched_off,last_heater_duty,last_fan_duty,thermal_updates'
LOG_LINE = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\] \[(\w+)\] \[(\d+)\] (.*)$')
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def safe_bytes(path, maximum):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError('Not a bounded regular file: ' + str(path))
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('Evidence exceeds size limit')
    return data


def safe_json(path):
    return json.loads(safe_bytes(path, 4 * 1024 * 1024))


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def create_bytes(path, data):
    with path.open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())


def native_entries(text):
    entries = []
    complete = text[:text.rfind('\n') + 1]
    for line in ANSI.sub('', complete).replace('\r\n', '\n').splitlines():
        match = LOG_LINE.fullmatch(line)
        if match:
            entries.append((line, match[1], match[2], int(match[3]), match[4]))
    return entries


class NativeReview:
    def __init__(self):
        self.ready_stamp = None
        self.occurrences = []

    def observe(self, text, *, final=False):
        if final and text and not text.endswith('\n'):
            tail = ANSI.sub('', text.rsplit('\n', 1)[-1])
            if re.search(r'\[(?:error|critical|fatal)\]|\b(shutdown|fault|emergency)\b|\b(?:MCU|sensor)\b.*\b(error|failed|timeout)\b', tail, re.I):
                raise ValueError('Unterminated final native fault evidence: ' + tail)
        entries = native_entries(text)
        complete = ANSI.sub('', text[:text.rfind('\n') + 1]).replace('\r\n', '\n')
        for line in complete.splitlines():
            if not LOG_LINE.fullmatch(line) and re.search(r'\[(?:error|critical|fatal)\]|\b(shutdown|fault|emergency)\b|\b(?:MCU|sensor)\b.*\b(error|failed|timeout)\b', line, re.I):
                raise ValueError('Unstructured/malformed native fault evidence: ' + line)
        stamps = [stamp for line, stamp, severity, source, message in entries
                  if severity == 'info' and re.fullmatch(r'Printer is ready at [0-9]+\.[0-9]+\.', message)]
        self.ready_stamp = min(stamps) if stamps else None
        occurrences = []
        for line, stamp, severity, source, message in entries:
            if severity == 'error' and source == 211 and message == VIDEO:
                occurrences.append({'line': line, 'classification': 'known absent auxiliary video service', 'startup_only': False})
            elif (severity == 'error' and AUXILIARY.get(message) == source and
                  (self.ready_stamp is None or stamp < self.ready_stamp)):
                occurrences.append({'line': line, 'classification': 'exact auxiliary startup limitation', 'startup_only': True})
            elif (severity in ('error', 'critical', 'fatal') or
                  re.search(r'\b(shutdown|fault|emergency)\b|\b(?:MCU|sensor)\b.*\b(error|failed|timeout)\b', message, re.I)):
                raise ValueError('Unclassified native fault/error: ' + line)
        self.occurrences = occurrences
        return self.ready_stamp is not None


def verify_classification_baseline():
    data = safe_bytes(ROOT / BASELINE_CONSOLE, MAX_CONSOLE)
    if hashlib.sha256(data).hexdigest() != BASELINE_SHA256:
        raise ValueError('Clean Ready console classification source changed')
    review = NativeReview()
    if not review.observe(data.decode('utf-8', errors='replace')):
        raise ValueError('Classification baseline has no genuine Ready log')
    observed = {(severity, source, message) for line, stamp, severity, source, message in native_entries(data.decode('utf-8', errors='replace'))}
    if any(('error', source, message) not in observed for message, source in AUXILIARY.items()) or ('error', 211, VIDEO) not in observed:
        raise ValueError('Classification template absent from pinned baseline')


class Clock:
    def __init__(self):
        self.previous = None

    def observe(self, sample):
        if (type(sample) is not dict or type(sample.get('schema')) is not int or sample.get('schema') != 1 or sample.get('source') != 'renode-shared-mcu' or
                sample.get('enabled') is not True or sample.get('time_went_backwards') is not False or
                type(sample.get('virtual_time_ns')) is not int or sample['virtual_time_ns'] < 0 or
                type(sample.get('sequence')) is not int or sample['sequence'] < 0 or
                type(sample.get('epoch')) is not str or not sample['epoch']):
            raise ValueError('Malformed shared-MCU clock')
        if self.previous is not None:
            if (sample['epoch'] != self.previous['epoch'] or sample['virtual_time_ns'] < self.previous['virtual_time_ns'] or
                    sample['sequence'] < self.previous['sequence'] or
                    (sample['sequence'] == self.previous['sequence'] and sample != self.previous)):
                raise ValueError('Replaced/backwards/inconsistent shared-MCU clock')
        self.previous = sample
        return sample['virtual_time_ns']


class ConsoleOwner:
    """One immutable append transcript and one pending batch, no uncertain retry."""
    def __init__(self, path):
        self.path, self.pending, self.expected, self.failed = path, None, b'', False
        self.fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_NONBLOCK | os.O_NOFOLLOW)
        if not stat.S_ISREG(os.fstat(self.fd).st_mode):
            os.close(self.fd); raise ValueError('Console input is not a regular file')
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.check()
        except BaseException:
            os.close(self.fd); raise
        info = os.fstat(self.fd)
        self.identity = (info.st_dev, info.st_ino)

    def check(self):
        current = safe_bytes(self.path, 2 * 1024 * 1024)
        if current != self.expected:
            self.failed = True
            raise ValueError('Console ownership lost: unexpected append/rewrite')
        if hasattr(self, 'identity'):
            info = self.path.stat(follow_symlinks=False)
            if (info.st_dev, info.st_ino) != self.identity:
                self.failed = True
                raise ValueError('Console ownership lost: replaced file')

    def append_once(self, label, commands):
        if self.failed or self.pending is not None:
            raise ValueError('Console is failed/uncertain or a batch is pending')
        self.check()
        self.pending = label  # Set BEFORE write; even an exception cannot permit retry.
        self.failed = True
        data = commands.encode('ascii')
        count = os.write(self.fd, data)
        if count != len(data):
            raise OSError('Uncertain/partial console append; never retry')
        os.fsync(self.fd)
        self.expected += data
        self.failed = False
        self.check()

    def complete(self, label):
        self.check()
        if self.failed or self.pending != label:
            raise ValueError('Cannot resolve absent/mismatched/uncertain pending batch')
        self.pending = None

    def close(self):
        os.close(self.fd)


class PassiveNozzle:
    def __init__(self):
        self.prefix = b''
        self.rows = []
        self.last_growth_shared_ns = None

    def consume(self, data, observed_shared_ns):
        if not data.startswith(self.prefix):
            raise ValueError('Passive nozzle telemetry truncated/rewritten')
        # Preserve partial bytes until the writer completes its newline.
        complete = data[:data.rfind(b'\n') + 1]
        if not complete:
            return
        text = complete.decode('ascii')
        if text.splitlines()[0] != CSV_HEADER:
            raise ValueError('Unexpected passive nozzle schema')
        rows = list(csv.DictReader(io.StringIO(text)))
        if len(rows) < len(self.rows):
            raise ValueError('Passive rows regressed')
        for index, row in enumerate(rows):
            validate_passive_row(row)
            if index:
                before = rows[index - 1]
                if (int(row['time_us']) < int(before['time_us']) or int(row['thermal_updates']) < int(before['thermal_updates']) or
                        row['event'] == 'sample' and int(row['time_us']) <= int(before['time_us'])):
                    raise ValueError('Stale/backwards passive source sample')
        if len(rows) > len(self.rows):
            self.last_growth_shared_ns = observed_shared_ns
        self.prefix, self.rows = data, rows

    def summary(self):
        return {'available': bool(self.rows), 'row_count': len(self.rows),
                'first': self.rows[0] if self.rows else None, 'latest': self.rows[-1] if self.rows else None,
                'last_growth_observed_shared_ns': self.last_growth_shared_ns,
                'source_time_domain': 'nozzle Renode microseconds since passive observer creation',
                'host_shared_source_clocks_equated': False}


def validate_passive_row(row):
    if set(row) != set(CSV_HEADER.split(',')) or None in row.values():
        raise ValueError('Malformed passive row')
    if (not row['time_us'].isdigit() or not row['thermal_updates'].isdigit() or
            row['event'] not in ('sample', 'snapshot:stream_started', 'snapshot:observer_attached')):
        raise ValueError('Unknown passive event/time/reset')
    for key in ('pb8_level', 'pb8_latch', 'sensor_fault', 'curve_out_of_range', 'model_overtemperature', 'model_heater_latched_off'):
        if row[key] != ('none' if key == 'sensor_fault' else '0'):
            raise ValueError('Passive nozzle demand/fault: ' + key)
    for key in ('physical_temperature_c', 'last_heater_duty', 'last_fan_duty'):
        if not math.isfinite(float(row[key])):
            raise ValueError('Nonfinite passive telemetry')
    if not 23 <= float(row['physical_temperature_c']) <= 27 or float(row['last_heater_duty']) != 0:
        raise ValueError('Nonambient or energized nozzle model')
    if row['published_adc_code'] != '4023' or row['sensor_curve'] != 'NTC ZM3863 HNS112HC4570G0':
        raise ValueError('Unexpected passive sensor/ADC')


def final_passive(directory, trace, now, status_queue_source_us):
    data = safe_bytes(directory / 'nozzle-thermal-live.csv', 8 * 1024 * 1024)
    if not data.endswith(b'\n'):
        raise ValueError('Truncated final passive live file')
    trace.consume(data, now)
    if (not trace.rows or trace.last_growth_shared_ns is None or now - trace.last_growth_shared_ns > 1_000_000_000 or
            int(trace.rows[-1]['time_us']) <= status_queue_source_us):
        raise ValueError('Missing/stale passive observations after status queue')
    status = safe_json(directory / 'nozzle-thermal-live-status.json')
    for key in ('dropped_rows', 'stream_dropped_rows', 'stream_error_count'):
        if type(status.get(key)) is not int or status[key] != 0:
            raise ValueError('Passive export drops/error/unknown: ' + key)
    for key in ('capacity_reached', 'stream_capacity_reached', 'stream_write_outcome_uncertain', 'streaming', 'stream_requested', 'actuator_connection_created', 'firmware_guard_state_recorded'):
        if status.get(key) is not False:
            raise ValueError('Passive final status invalid: ' + key)
    if status.get('last_stream_error') != '' or status.get('stream_rows_written') != len(trace.rows):
        raise ValueError('Passive export incomplete')
    exported = safe_bytes(directory / 'nozzle-thermal.csv', 8 * 1024 * 1024)
    if not exported.endswith(b'\n') or exported.decode('ascii').splitlines()[0] != CSV_HEADER:
        raise ValueError('Malformed passive final CSV')
    final_rows = list(csv.DictReader(io.StringIO(exported.decode('ascii'))))
    if len(final_rows) != len(trace.rows) + 1 or final_rows[1:] != trace.rows or status.get('rows') != len(final_rows):
        raise ValueError('Final passive CSV differs from live evidence')
    for row in final_rows:
        validate_passive_row(row)
    return {**trace.summary(), 'final_export_verified': True, 'stream_status': status,
            'live_sha256': hashlib.sha256(data).hexdigest(), 'final_sha256': hashlib.sha256(exported).hexdigest()}


def fixed_environment(seconds):
    if seconds != ACTIVE_SECONDS:
        raise ValueError('Only the reviewed 868-second active budget is permitted')
    return {'PATH': '/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin:/usr/bin:/bin',
            'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', 'RUN_SECONDS': str(seconds),
            'PYTHONPYCACHEPREFIX': str(sys.pycache_prefix),
            'GLOBAL_QUANTUM_US': '1', 'NOZZLE_TMC_MODEL': 'autobaud', 'HEADLESS_READY_ONLY': '1',
            'THERMAL_PROFILE': 'none', 'Z_PROBE_PROFILE': 'none', 'NATIVE_NOZZLE_HEATER': '0',
            'CLOCK_CLIENT': 'scalar', 'ICOUNT_SHIFT': '0', 'RENODE_BOOTSTRAP': 'legacy',
            'PASSIVE_MOTOR_TRACE': '1', 'RECOVERED_NOZZLE_NTC': '1', 'ASSUMED_XY_DIAG_CABLE': '1',
            'MOTOR_ENABLE_WIRING': 'mcu-control-only', 'PASSIVE_NOZZLE_TRACE': '1',
            'PASSIVE_HOMING_GPIO': '1', 'PASSIVE_TMC_TRACE': '1',
            'QEMU_BINARY': str(ROOT / 'rv1106-at32-link/experimental/clock-snapshot/runtime/run-baseline')}


def check_deadlines(elapsed, ready_elapsed, now, pending=None):
    if elapsed >= ACTIVE_SECONDS - CLEANUP_SECONDS:
        raise TimeoutError('Observer active deadline; cleanup reserve retained')
    if ready_elapsed is not None and elapsed - ready_elapsed >= POST_READY_SECONDS:
        raise TimeoutError('Post-Ready host deadline, including build/upload/capture')
    if now is not None and now >= SHARED_STOP_NS:
        raise TimeoutError('Sampled shared-MCU stop threshold reached; not a strict stepping cap')
    if pending is not None:
        if pending.get('kind') == 'shell_check' and elapsed - pending['queued_host_elapsed_seconds'] >= 30:
            raise TimeoutError('Guest shell builtin check deadline')
        if elapsed - pending['queued_host_elapsed_seconds'] >= POST_READY_SECONDS:
            raise TimeoutError('Pending console batch host deadline')
        if now is not None and now - pending['queued_shared_mcu_ns'] > OBSERVATION_FRESH_NS:
            raise TimeoutError('Pending batch exceeds shared-MCU observation freshness bound')


def validate_final_report(report):
    """Offline final gate. Reads no run files and launches nothing."""
    if type(report) is not dict:
        raise ValueError('Ambient report must be an object')
    if (report.get('phase') != 'verified_ambient' or report.get('success') is not True or
            report.get('final_export_requested') is not True or report.get('launcher_exit_code') != 0 or
            type(report.get('launcher_exit_code')) is not int or report.get('request_count') != 2 or
            type(report.get('request_count')) is not int or report.get('requests') != list(protocol.METHODS)):
        raise ValueError('Incomplete ambient lifecycle')
    if any(key in report for key in ('error', 'stop_request_error', 'record_write_error', 'cleanup_timeout')):
        raise ValueError('Ambient report contains failure')
    if report.get('pending_batch') is not None or report.get('queue_outcomes') != ['appended', 'appended']:
        raise ValueError('Unresolved/uncertain console ownership')
    for key in ('physical_completion_proven', 'shutdown_qualification', 'calibration_completed', 'old_provenance_restored', 'strict_virtual_cap'):
        if report.get(key) is not False:
            raise ValueError('Unsupported qualification claim')
    if report.get('bounds') != {'active_host_seconds': ACTIVE_SECONDS, 'post_ready_host_seconds': POST_READY_SECONDS,
                                'capture_entry_host_seconds': CAPTURE_ENTRY_SECONDS, 'shared_mcu_stop_ns': SHARED_STOP_NS}:
        raise ValueError('Changed observation bounds')
    def finite_number(value):
        return type(value) in (int, float) and math.isfinite(value)
    shell = report.get('shell_check_result')
    batches = report.get('batches')
    if (type(shell) is not dict or shell != {'verified': True, 'scope': 'guest-shell-builtins-only', 'exit_status': 37} or
            type(batches) is not list or not batches or batches[0].get('kind') != 'shell_check' or
            sum(b.get('kind') == 'shell_check' for b in batches) != 1 or
            batches[0].get('queue_outcome') != 'appended'):
        raise ValueError('Missing single first verified guest shell builtin check')
    shell_batch = batches[0]
    sq, sd = shell_batch.get('queued_host_elapsed_seconds'), shell_batch.get('complete_host_elapsed_seconds')
    if not all(finite_number(v) for v in (sq, sd)) or not 0 <= sq <= sd < CAPTURE_ENTRY_SECONDS or sd - sq >= 30:
        raise ValueError('Invalid guest shell builtin check timing')
    qs, cs = shell_batch.get('queued_shared_mcu_ns'), shell_batch.get('complete_shared_mcu_ns')
    if (type(qs) is not int or type(cs) is not int or not 0 <= qs <= cs < SHARED_STOP_NS or
            cs - qs > OBSERVATION_FRESH_NS):
        raise ValueError('Invalid guest shell builtin check shared timing')
    if any(not finite_number(b.get('queued_host_elapsed_seconds')) or b['queued_host_elapsed_seconds'] < sd for b in batches[1:]):
        raise ValueError('Log/RPC queued before guest shell check')
    ready_time = report.get('ready_host_elapsed_seconds')
    finished = report.get('ambient_complete_host_elapsed_seconds')
    if (not finite_number(ready_time) or not finite_number(finished) or not 0 <= ready_time <= finished or
            finished - ready_time >= POST_READY_SECONDS or finished >= ACTIVE_SECONDS - CLEANUP_SECONDS or
            report.get('final_log_verified') is not True):
        raise ValueError('Missing/out-of-budget final observation time/log')
    final_clock = report.get('last_shared_mcu_ns')
    if type(final_clock) is not int or not 0 <= final_clock < SHARED_STOP_NS:
        raise ValueError('Invalid/over-threshold final shared-MCU sample')
    last_host, last_shared = ready_time, 0
    generations = report.get('generation_attempts')
    if type(generations) is not list or [g.get('method') for g in generations] != list(protocol.METHODS):
        raise ValueError('Wrong generation attempts')
    for index, key in enumerate(('ready_result', 'status_result')):
        result = report.get(key, {})
        queued, done = result.get('queued_host_elapsed_seconds'), result.get('completed_host_elapsed_seconds')
        genstart, genend = generations[index].get('started_host_elapsed_seconds'), generations[index].get('finished_host_elapsed_seconds')
        if (not all(finite_number(value) for value in (queued, done, genstart, genend)) or
                not last_host <= genstart <= genend <= queued < CAPTURE_ENTRY_SECONDS or
                not queued <= done <= finished or done - ready_time >= POST_READY_SECONDS):
            raise ValueError('Unordered/stale/out-of-budget host request boundaries')
        shared_start, shared_done = result.get('queued_shared_mcu_ns'), result.get('completed_shared_mcu_ns')
        if (type(shared_start) is not int or type(shared_done) is not int or
                not last_shared <= shared_start <= shared_done <= final_clock or
                shared_done - shared_start > OBSERVATION_FRESH_NS):
            raise ValueError('Unordered/stale shared-MCU observation boundaries')
        last_host, last_shared = done, shared_done
    ready = report.get('ready_result', {})
    status = report.get('status_result', {})
    if (any(type(ready.get(key)) is not int for key in ('client_exit_status', 'transport_exit_status', 'terminal_grpc_status')) or
            ready.get('client_exit_status') != 0 or ready.get('transport_exit_status') != 0 or
            ready.get('api_response', {}).get('state') != 'ready' or ready.get('terminal_grpc_status') != 0):
        raise ValueError('Missing strict ready result')
    if (any(type(status.get(key)) is not int for key in ('client_exit_status', 'transport_exit_status', 'selected_sequence')) or
            status.get('client_exit_status') != 20 or status.get('transport_exit_status') != 20 or
            status.get('selected_sequence') != 2 or status.get('local_cancel_frame_sent') is not True or
            status.get('local_socket_shutdown_and_close') is not True or status.get('unary_completion') is not False or
            status.get('remote_cancel_acknowledged') is not False or status.get('terminal_grpc_status') is not None or
            status.get('native_sensor_acquisition_timestamp') is not None):
        raise ValueError('Invalid snapshot outcome claim')
    messages = status.get('messages')
    if type(messages) is not list or [row.get('sequence') for row in messages] != [1, 2]:
        raise ValueError('Not two ordered messages')
    for sequence, row in enumerate(messages, 1):
        protocol.validate_ambient(row['temperatures'], selected=sequence == 2)
    if status.get('selected_temperatures') != messages[1]['temperatures']:
        raise ValueError('Selected value differs from sequence2')
    for method, result in (('PrinterState', ready), ('GetStatus', status)):
        if result.get('physical_completion_proven') is not False or result.get('guest_uptime_is_sensor_timestamp') is not False:
            raise ValueError('Unsupported RPC physical/time claim')
        wire = bytes.fromhex(result['wire_hex'])
        if hashlib.sha256(wire).hexdigest() != result['wire_sha256']:
            raise ValueError('Wire identity mismatch')
        payloads = protocol.response_messages(wire, method)
        expected = [result['protobuf_hex']] if method == 'PrinterState' else [row['protobuf_hex'] for row in messages]
        if [payload.hex() for payload in payloads] != expected:
            raise ValueError('Protobuf/wire evidence mismatch')
        if method == 'PrinterState' and protocol.state_payload(payloads[0]) != result['api_response']:
            raise ValueError('Ready protobuf does not match interpreted state')
        if method == 'GetStatus' and [protocol.decode_status(payload) for payload in payloads] != [row['temperatures'] for row in messages]:
            raise ValueError('Status protobuf does not match interpreted temperatures')
    passive = report.get('passive_nozzle', {})
    if passive.get('available') is not True or passive.get('final_export_verified') is not True or passive.get('row_count', 0) < 2:
        raise ValueError('Missing verified final passive nozzle evidence')
    validate_passive_row(passive['first']); validate_passive_row(passive['latest'])
    source_boundary = report.get('status_queue_passive_source_us')
    if type(source_boundary) is not int or source_boundary < 0 or int(passive['latest']['time_us']) <= source_boundary:
        raise ValueError('No newer passive source observation after GetStatus queue')
    if passive.get('host_shared_source_clocks_equated') is not False or int(passive['latest']['time_us']) <= int(passive['first']['time_us']):
        raise ValueError('Passive source timing invalid')
    for key in ('dropped_rows', 'stream_dropped_rows', 'stream_error_count'):
        if type(passive.get('stream_status', {}).get(key)) is not int or passive['stream_status'][key] != 0:
            raise ValueError('Passive final error/drop evidence')
    for key in ('capacity_reached', 'stream_capacity_reached', 'stream_write_outcome_uncertain', 'streaming', 'stream_requested', 'actuator_connection_created', 'firmware_guard_state_recorded'):
        if passive.get('stream_status', {}).get(key) is not False:
            raise ValueError('Passive final fault/unknown status')
    if report.get('passive_bed') != {'available': False, 'reason': 'No passive bed telemetry in unchanged no-profile fixture'}:
        raise ValueError('Unsupported bed passive evidence')
    if report.get('native_error_review_scope') != NATIVE_REVIEW_SCOPE:
        raise ValueError('Unsupported native error coverage claim')
    if report.get('baseline_classification_sha256') != BASELINE_SHA256:
        raise ValueError('Unbound error classification')
    if report.get('helper_sha256') != protocol.HELPER_PINS:
        raise ValueError('Wrong helper closure')
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_name')
    parser.add_argument('--seconds', type=int, choices=[ACTIVE_SECONDS], default=ACTIVE_SECONDS)
    args = parser.parse_args(argv)
    if not re.fullmatch('[A-Za-z0-9_-]+', args.run_name):
        parser.error('Invalid run name')
    return args


def main(argv=None):
    args = parse_args(argv)
    directory = ROOT / 'runs' / args.run_name
    if directory.exists() or directory.is_symlink():
        raise SystemExit('Fresh run directory required; no attach/resume')
    if (type(sys.pycache_prefix) is not str or not Path(sys.pycache_prefix).is_absolute() or
            str(Path(sys.pycache_prefix).resolve()) != sys.pycache_prefix or
            Path(sys.pycache_prefix).name != args.run_name + '-python-cache' or
            not Path(sys.pycache_prefix).parent.is_dir() or directory in Path(sys.pycache_prefix).parents or
            Path(sys.pycache_prefix).exists() or Path(sys.pycache_prefix).is_symlink() or
            os.environ.get('PYTHONPYCACHEPREFIX') != sys.pycache_prefix or not sys.dont_write_bytecode or not sys.flags.isolated):
        raise SystemExit('Fresh isolated supervisor cache prefix and disabled bytecode writes required')
    started = time.monotonic()
    verify_classification_baseline()
    protocol.load_helpers()
    token = secrets.token_hex(10)
    record = {'schema_version': 1, 'scope': 'New read-only ambient interface/model observation',
              'phase': 'waiting_ready', 'success': False, 'request_count': 0, 'requests': [],
              'queue_outcomes': [], 'pending_batch': None, 'final_export_requested': False,
              'physical_completion_proven': False, 'shutdown_qualification': False,
              'calibration_completed': False, 'old_provenance_restored': False, 'strict_virtual_cap': False,
              'token': token, 'helper_sha256': protocol.HELPER_PINS,
              'baseline_classification_sha256': BASELINE_SHA256,
              'native_error_review_scope': NATIVE_REVIEW_SCOPE,
              'passive_bed': {'available': False, 'reason': 'No passive bed telemetry in unchanged no-profile fixture'},
              'bounds': {'active_host_seconds': ACTIVE_SECONDS, 'post_ready_host_seconds': POST_READY_SECONDS,
                         'capture_entry_host_seconds': CAPTURE_ENTRY_SECONDS, 'shared_mcu_stop_ns': SHARED_STOP_NS},
              'time_domains': ['host_monotonic_elapsed_seconds', 'shared_mcu_virtual_time_ns', 'guest_uptime_seconds',
                               'native_log_timestamp', 'passive_nozzle_microseconds_since_creation'],
              'sensor_acquisition_age_known': False, 'generation_attempts': [], 'batches': []}
    process, owner, now, ready_elapsed, pending = None, None, None, None, None
    previous_console, log_count, next_log_ns = b'', 0, 0
    status_queue_source_us = None
    clock, trace, review = Clock(), PassiveNozzle(), NativeReview()

    def save():
        record.update(pending_batch=pending, host_elapsed_seconds=time.monotonic() - started, last_shared_mcu_ns=now,
                      passive_nozzle=trace.summary(), native_auxiliary_occurrences=review.occurrences,
                      native_ready_log_timestamp=review.ready_stamp)
        if directory.is_dir():
            atomic_json(directory / REPORT_NAME, record)

    def stop(reason):
        if directory.is_dir():
            path = directory / 'stop-request'
            if not path.exists():
                create_bytes(path, (reason + '\n').encode())
            record['final_export_requested'] = True

    def queue_rpc(method, text):
        nonlocal pending, status_queue_source_us
        if record.get('shell_check_result', {}).get('verified') is not True:
            raise ValueError('Guest shell builtin check required before RPC')
        elapsed = time.monotonic() - started
        check_deadlines(elapsed, ready_elapsed, now)
        if elapsed >= CAPTURE_ENTRY_SECONDS:
            raise TimeoutError('Too late to start a new RPC build/upload/capture')
        if method == 'GetStatus':
            if not trace.rows:
                raise ValueError('Missing passive nozzle baseline before GetStatus')
            status_queue_source_us = int(trace.rows[-1]['time_us'])
            record['status_queue_passive_source_us'] = status_queue_source_us
        generation = {'method': method, 'started_host_elapsed_seconds': elapsed, 'started_shared_mcu_ns': now}
        record['generation_attempts'].append(generation); save()
        packet = protocol.request_packet(method)
        elf = protocol.build_client(method, packet)
        commands = protocol.command_batch(method, token, elf)
        protocol.validate_commands(method, token, elf, commands)
        generation['finished_host_elapsed_seconds'] = time.monotonic() - started
        check_deadlines(generation['finished_host_elapsed_seconds'], ready_elapsed, now)
        if generation['finished_host_elapsed_seconds'] >= CAPTURE_ENTRY_SECONDS:
            raise TimeoutError('Build exhausted capture-entry deadline; no console append')
        name = 'printer-state' if method == 'PrinterState' else 'get-status'
        create_bytes(directory / (name + '.request.bin'), packet)
        create_bytes(directory / (name + '.client.elf'), elf)
        create_bytes(directory / (name + '.commands'), commands.encode())
        if (directory / 'stop-request').exists():
            raise ValueError('Stop arrived before RPC append')
        pending = {'kind': 'rpc', 'method': method, 'offset': len(text),
                   'queued_host_elapsed_seconds': time.monotonic() - started, 'queued_shared_mcu_ns': now,
                   'queue_outcome': 'uncertain'}
        record['requests'].append(method); record['request_count'] += 1
        record['queue_outcomes'].append('uncertain'); record['phase'] = 'queue_attempted'; save()
        # Durable intent/artifact writes may consume the remaining budget.
        # Recheck immediately before the single irreversible append.
        latest_elapsed = time.monotonic() - started
        check_deadlines(latest_elapsed, ready_elapsed, now)
        if latest_elapsed >= CAPTURE_ENTRY_SECONDS or (directory / 'stop-request').exists():
            raise TimeoutError('Stop/deadline before console append; no retry')
        pending['queued_host_elapsed_seconds'] = latest_elapsed
        owner.append_once(method, commands)
        pending['queue_outcome'] = 'appended'; record['queue_outcomes'][-1] = 'appended'
        record['phase'] = 'awaiting_' + name
        save()

    try:
        process = subprocess.Popen([str(ROOT / 'rv1106-at32-link/scripts/run_native_event_fixture.sh'), args.run_name],
                                   env=fixed_environment(args.seconds))
        while process.poll() is None:
            elapsed = time.monotonic() - started
            check_deadlines(elapsed, ready_elapsed, now, pending)
            if (directory / 'stop-request').exists():
                record['phase'] = 'external_stop'; record['final_export_requested'] = True
                break
            if not (directory / 'console.bin').exists():
                time.sleep(.1); continue
            raw = safe_bytes(directory / 'console.bin', MAX_CONSOLE)
            if not raw.startswith(previous_console):
                raise ValueError('Console capture truncated/rewritten')
            previous_console = raw
            text = raw.decode('utf-8', errors='replace')
            if (directory / 'virtual-time.json').exists():
                now = clock.observe(safe_json(directory / 'virtual-time.json'))
                check_deadlines(time.monotonic() - started, ready_elapsed, now, pending)
            if now is not None and (directory / 'nozzle-thermal-live.csv').exists():
                trace.consume(safe_bytes(directory / 'nozzle-thermal-live.csv', 8 * 1024 * 1024), now)
            is_ready = review.observe(text)
            if is_ready and ready_elapsed is None:
                ready_elapsed = time.monotonic() - started
                record['ready_host_elapsed_seconds'] = ready_elapsed
            startup = re.findall(r'(?m)^COUPLED_STARTUP_COMMANDS_DONE\r?\n', text)
            if len(startup) > 1:
                raise ValueError('Repeated startup completion marker')
            if owner is None and startup and now is not None:
                owner = ConsoleOwner(directory / 'console-input.commands')
            if owner is not None:
                owner.check()
            if pending is not None:
                tail = text[pending['offset']:]
                if pending['kind'] == 'shell_check':
                    result = protocol.verify_shell_check(tail, token)
                    if result is not None:
                        check_deadlines(time.monotonic() - started, ready_elapsed, now, pending)
                        create_bytes(directory / 'shell-check.capture.txt', tail.encode('utf-8'))
                        check_deadlines(time.monotonic() - started, ready_elapsed, now, pending)
                        if (directory / 'stop-request').exists():
                            raise ValueError('Stop after shell builtin capture persistence')
                        owner.complete(pending['label'])
                        record['batches'].append({**pending, 'complete_host_elapsed_seconds': time.monotonic() - started, 'complete_shared_mcu_ns': now})
                        record['shell_check_result'] = result
                        pending = None
                        record['phase'] = 'shell_check_verified'
                elif pending['kind'] == 'log':
                    complete = protocol.bounded_region(tail, pending['begin'], pending['end'])
                    if complete is not None:
                        owner.complete(pending['label']); record['batches'].append({**pending, 'complete_host_elapsed_seconds': time.monotonic() - started, 'complete_shared_mcu_ns': now})
                        final_log = pending.get('final_log') is True
                        pending = None
                        if final_log:
                            check_deadlines(time.monotonic() - started, ready_elapsed, now)
                            record.update(phase='ambient_captured', final_log_verified=True, ambient_complete_host_elapsed_seconds=time.monotonic() - started)
                            stop('Read-only ambient pair and final log validated; normal final export.'); save(); break
                else:
                    method = pending['method']
                    mark = protocol.markers(token, method)
                    if protocol.bounded_region(tail, mark['begin'], mark['end']) is not None:
                        # Preserve complete console/raw/protobuf evidence BEFORE
                        # native ambient validation. A default-zero second sample
                        # still fails, but its real bytes remain available.
                        name = 'printer-state' if method == 'PrinterState' else 'get-status'
                        create_bytes(directory / (name + '.capture.txt'), tail.encode('utf-8'))
                        extracted = protocol.capture_transport(tail, method, token)
                        wire = extracted[0]
                        create_bytes(directory / (name + '.response.http2.bin'), wire)
                        payloads = protocol.response_messages(wire, method)
                        for sequence, payload in enumerate(payloads, 1):
                            create_bytes(directory / (name + '.message' + str(sequence) + '.protobuf.bin'), payload)
                        result = protocol.verify_capture(tail, method, token)
                        check_deadlines(time.monotonic() - started, ready_elapsed, now, pending)
                        result.update(queued_host_elapsed_seconds=pending['queued_host_elapsed_seconds'],
                                      queued_shared_mcu_ns=pending['queued_shared_mcu_ns'],
                                      completed_host_elapsed_seconds=time.monotonic() - started, completed_shared_mcu_ns=now)
                        record['ready_result' if method == 'PrinterState' else 'status_result'] = result
                        owner.complete(method); record['batches'].append({**pending, 'complete_host_elapsed_seconds': time.monotonic() - started, 'complete_shared_mcu_ns': now})
                        pending = None
                        if method == 'GetStatus':
                            record['phase'] = 'awaiting_final_log'
            if pending is None and owner is not None:
                if 'shell_check_result' not in record:
                    label = 'AMB_' + token + '_C'
                    commands = protocol.shell_check_command_batch(token)
                    create_bytes(directory / 'shell-check.commands', commands.encode('ascii'))
                    pending = {'kind': 'shell_check', 'label': label, 'offset': len(text),
                               'queued_host_elapsed_seconds': time.monotonic() - started, 'queued_shared_mcu_ns': now,
                               'queue_outcome': 'uncertain'}
                    record['phase'] = 'awaiting_shell_check'; save()
                    check_deadlines(time.monotonic() - started, ready_elapsed, now, pending)
                    if (directory / 'stop-request').exists():
                        raise ValueError('Stop before shell builtin check append')
                    owner.append_once(label, commands); pending['queue_outcome'] = 'appended'
                elif is_ready:
                    if record['request_count'] == 0:
                        queue_rpc('PrinterState', text)
                    elif record['request_count'] == 1 and 'ready_result' in record:
                        queue_rpc('GetStatus', text)
                    elif record['request_count'] == 2 and 'status_result' in record and not record.get('final_log_verified'):
                        prefix = 'AMB_' + token + '_F'
                        begin, end = prefix + '_B', prefix + '_E'
                        commands = protocol.log_command_batch(token, 'F')
                        pending = {'kind': 'log', 'label': prefix, 'begin': begin, 'end': end, 'offset': len(text),
                                   'queued_host_elapsed_seconds': time.monotonic() - started, 'queued_shared_mcu_ns': now,
                                   'queue_outcome': 'uncertain', 'final_log': True}
                        save()
                        check_deadlines(time.monotonic() - started, ready_elapsed, now)
                        if (directory / 'stop-request').exists():
                            raise ValueError('Stop before final log append')
                        owner.append_once(prefix, commands); pending['queue_outcome'] = 'appended'
                    elif record['request_count'] > 1:
                        raise ValueError('No further RPCs permitted')
                elif now >= next_log_ns:
                    if log_count >= 20:
                        raise ValueError('Finite Ready log poll budget exhausted')
                    log_count += 1
                    prefix = 'AMB_' + token + '_L' + str(log_count)
                    begin, end = prefix + '_B', prefix + '_E'
                    commands = protocol.log_command_batch(token, 'L' + str(log_count))
                    pending = {'kind': 'log', 'label': prefix, 'begin': begin, 'end': end, 'offset': len(text),
                               'queued_host_elapsed_seconds': time.monotonic() - started, 'queued_shared_mcu_ns': now,
                               'queue_outcome': 'uncertain'}
                    save(); check_deadlines(time.monotonic() - started, ready_elapsed, now)
                    if (directory / 'stop-request').exists():
                        raise ValueError('Stop before log append')
                    owner.append_once(prefix, commands); pending['queue_outcome'] = 'appended'
                    next_log_ns = now + 1_000_000_000
            save(); time.sleep(.1)
        if process.poll() is not None and record['phase'] != 'ambient_captured':
            raise ValueError('Fixture exited before full ambient observation')
    except (Exception, KeyboardInterrupt) as error:
        record.update(phase='error', error=type(error).__name__ + ': ' + str(error))
        try:
            stop('Ambient observer failed; no retry or actuator request; final export.')
        except OSError as stop_error:
            record['stop_request_error'] = str(stop_error)
    finally:
        if process is not None:
            try:
                record['launcher_exit_code'] = process.wait(timeout=CLEANUP_SECONDS)
            except subprocess.TimeoutExpired:
                # The unchanged 880/900 supervisors own escalation and descendants.
                # Stay alive for their stop/TERM/KILL; do not orphan a fixture by
                # returning a completed leader while a child is still running.
                record.update(phase='error', cleanup_timeout=True)
                save()
                record['launcher_exit_code'] = process.wait()
        if owner is not None:
            try:
                owner.check()
            except Exception as error:
                record.update(phase='error', error=str(error))
            owner.close()
        try:
            save()
            if record['phase'] == 'ambient_captured' and record.get('launcher_exit_code') == 0:
                if (directory / 'virtual-time.json').exists():
                    now = clock.observe(safe_json(directory / 'virtual-time.json'))
                final_raw = safe_bytes(directory / 'console.bin', MAX_CONSOLE)
                if not final_raw.startswith(previous_console):
                    raise ValueError('Final console truncated/rewritten')
                review.observe(final_raw.decode('utf-8', errors='replace'), final=True)
                # Reverify full suffixes to reject duplicate late captures too.
                for batch in record['batches']:
                    if batch['kind'] == 'shell_check':
                        if protocol.verify_shell_check(final_raw.decode('utf-8', errors='replace')[batch['offset']:], token) != record.get('shell_check_result'):
                            raise ValueError('Final guest shell builtin check mismatch')
                    elif batch['kind'] == 'rpc':
                        protocol.verify_capture(final_raw.decode('utf-8', errors='replace')[batch['offset']:], batch['method'], token)
                nozzle = final_passive(directory, trace, now, status_queue_source_us)
                record.update(phase='verified_ambient', success=True)
                save(); record['passive_nozzle'] = nozzle
                validate_final_report(record)
                atomic_json(directory / REPORT_NAME, record)
            ready_record = {'scope': 'Only the one genuine PrinterState prerequisite; not ambient success',
                            'phase': 'verified_ready' if record.get('success') is True and record['phase'] == 'verified_ambient' else 'invalid',
                            'request_count': 1 if 'ready_result' in record else 0,
                            'total_run_request_count': record['request_count'], 'result': record.get('ready_result'),
                            'final_export_requested': record['final_export_requested'],
                            'launcher_exit_code': record.get('launcher_exit_code')}
            if directory.is_dir():
                atomic_json(directory / READY_NAME, ready_record)
        except Exception as error:
            record.update(phase='error', success=False, error=type(error).__name__ + ': ' + str(error))
            if directory.is_dir():
                atomic_json(directory / REPORT_NAME, record)
                atomic_json(directory / READY_NAME, {'scope': 'PrinterState prerequisite invalid after ambient failure', 'phase': 'invalid', 'error': str(error)})
    return 0 if record.get('success') is True and record['phase'] == 'verified_ambient' else 2


if __name__ == '__main__':
    raise SystemExit(main())
