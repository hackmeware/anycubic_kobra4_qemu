#!/usr/bin/env python3
"""Explicitly synthetic NEW fixtures. Offline only: no guest/client/emulator.

No missing historical fixture is reproduced under its old identity. Fake fixture
launches below are Python mocks writing small synthetic console/telemetry files.
"""
if not __debug__:
    raise SystemExit('Offline tests require normal Python; optimized rejection tested separately')

import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('new_ambient_observer_under_test', HERE / 'observer.py')
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)
p = observer.protocol
TOKEN = '0123456789abcdefabcd'
READY_LINE = '[1970-01-01 00:00:06.241] [info] [7] Printer is ready at 6.2416.\n'


def raw_header(name, value):
    return b'\0' + bytes([len(name)]) + name + bytes([len(value)]) + value


def nested(number, content):
    return bytes([number << 3 | 2, len(content)]) + content


def temperature_payload(nozzle=25, bed=25, target=0, bed_target=0):
    def heater(current, requested):
        return (bytes([8, current]) if current else b'') + (bytes([16, requested]) if requested else b'')
    return nested(1, nested(2, heater(nozzle, target)) + nested(3, heater(bed, bed_target)))


def synthetic_wire(method, payloads=None, headers=None):
    if payloads is None:
        payloads = [b'\x12\x05ready'] if method == 'PrinterState' else [temperature_payload(0, 0), temperature_payload()]
    headers = b'\x88' + raw_header(b'content-type', b'application/grpc') if headers is None else headers
    wire = p.frame(4, 0, 0) + p.frame(1, 4, 1, headers)
    for payload in payloads:
        wire += p.frame(0, 0, 1, b'\0' + len(payload).to_bytes(4, 'big') + payload)
    if method == 'PrinterState':
        wire += p.frame(1, 5, 1, raw_header(b'grpc-status', b'0'))
    return wire


def octal_dump(wire):
    lines = [f'{off:07o} ' + ' '.join(f'{byte:03o}' for byte in wire[off:off + 16]) for off in range(0, len(wire), 16)]
    return '\n'.join(lines + [f'{len(wire):07o}']) + '\n'


def synthetic_capture(method, wire=None, exit_code=None):
    mark = p.markers(TOKEN, method)
    wire = synthetic_wire(method) if wire is None else wire
    exit_code = (0 if method == 'PrinterState' else 20) if exit_code is None else exit_code
    return ('echoed commands cannot count as output\n' + mark['begin'] + '\n10.00 0.00\n' + mark['exit'] + '=' + str(exit_code) + '\n' +
            mark['raw_begin'] + '\n' + octal_dump(wire) + mark['raw_end'] + '\n11.01 0.00\n' + mark['end'] + '\n')


def passive_row(time_us, event='sample', updates=None):
    values = [str(time_us), event, '', '', '0', '0', '4', '4', '0', '0', '25', '4023',
              'NTC ZM3863 HNS112HC4570G0', 'none', '0', '0', '0', '0', '0', str(time_us // 10000 if updates is None else updates)]
    return dict(zip(observer.CSV_HEADER.split(','), values))


def csv_bytes(rows):
    return (observer.CSV_HEADER + '\n' + ''.join(','.join(row.values()) + '\n' for row in rows)).encode()


def clock_sample(now=8_000_000_000, sequence=1):
    return {'schema': 1, 'source': 'renode-shared-mcu', 'virtual_time_ns': now, 'sequence': sequence,
            'epoch': 'new-synthetic-epoch', 'enabled': True, 'time_went_backwards': False}


class ProtocolTests(unittest.TestCase):
    def test_exact_request_allowlist(self):
        for method in ('Homing', 'RunGcodeScript', 'StartPrint', 'ExtruderPreheating', 'SetTemperature', '', '../GetStatus', b'GetStatus'):
            with self.subTest(method=method), self.assertRaises(ValueError):
                p.request_packet(method)
        for method in p.METHODS:
            packet = p.request_packet(method)
            for replacement in (packet + b'\0', packet.replace(b'127.0.0.1', b'127.0.0.2'), packet.replace(b'50051', b'50052'), packet[:-1] + b'\x01'):
                with self.assertRaises(ValueError):
                    p.build_client(method, replacement)

    def test_source_only_builders_and_commands(self):
        p._HELPERS = None
        with mock.patch('importlib.machinery.SourceFileLoader.exec_module', side_effect=AssertionError('No bytecode loader allowed')):
            for method in p.METHODS:
                elf = p.build_client(method, p.request_packet(method))
                command = p.command_batch(method, TOKEN, elf)
                self.assertLessEqual(len(command.splitlines()[-1]), 768)
                self.assertEqual(1, command.count('timeout -t 5 '))
                self.assertIn(p._marker_line('RB'), command)
                self.assertNotIn(p.markers(TOKEN, method)['raw_begin'], command)
                self.assertTrue(command.endswith('\n'))
                syntax = subprocess.run(['/bin/sh', '-n'], input=command, text=True, capture_output=True, timeout=5)
                self.assertEqual(syntax.returncode, 0, syntax.stderr)
                for replacement in (command + 'reboot\n', command.replace('timeout -t 5', 'timeout -t 30'), command.replace('cat /proc/uptime', 'cat /proc/1/mem'), command.replace('od -v -b', 'echo'), command.replace('/tmp/amb_', '/tmp/evil_')):
                    with self.assertRaises(ValueError):
                        p.validate_commands(method, TOKEN, elf, replacement)
                with self.assertRaises(ValueError):
                    p.command_batch(method, TOKEN, elf + b'\0')

    def test_helper_hash_failure_precedes_source_execution(self):
        with tempfile.TemporaryDirectory(dir=HERE) as temp:
            root = Path(temp)
            for relative in p.HELPER_PINS:
                path = root / relative; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('raise RuntimeError("must never execute unverified source")\n')
            previous = p._HELPERS
            try:
                p._HELPERS = None
                with mock.patch.object(p, 'ROOT', root), self.assertRaisesRegex(ValueError, 'identity mismatch'):
                    p.load_helpers()
            finally:
                p._HELPERS = previous

    def test_builder_identity_matches_pinned_snapshot(self):
        elf = p.build_client('GetStatus', p.request_packet('GetStatus'))
        self.assertEqual(hashlib.sha256(elf).hexdigest(), '94bacb120ff6378771ab0ece268b69614406ca97058d9683e4317bc471701216')
        _, _, schema = p.load_helpers()
        for wire in (temperature_payload(), temperature_payload(0, 0), temperature_payload(24, 26)):
            self.assertEqual(p.decode_status(wire), schema.decode_get_status_temperatures(wire))

    def test_good_synthetic_ready_and_snapshot(self):
        ready = p.verify_capture(synthetic_capture('PrinterState'), 'PrinterState', TOKEN)
        self.assertEqual(ready['api_response']['state'], 'ready')
        snapshot = p.verify_capture(synthetic_capture('GetStatus'), 'GetStatus', TOKEN)
        self.assertEqual(snapshot['messages'][0]['temperatures']['nozzle']['current'], 0)
        self.assertEqual(snapshot['selected_temperatures']['nozzle']['current'], 25)
        self.assertEqual(snapshot['selected_sequence'], 2)
        self.assertFalse(snapshot['remote_cancel_acknowledged'])
        self.assertIsNone(snapshot['native_sensor_acquisition_timestamp'])

    def test_second_selected_regardless_value(self):
        for samples in ([temperature_payload(), temperature_payload(0, 0)], [temperature_payload(), temperature_payload(40, 25)]):
            with self.assertRaises(ValueError):
                p.verify_capture(synthetic_capture('GetStatus', synthetic_wire('GetStatus', samples)), 'GetStatus', TOKEN)

    def test_targets_nonzero_in_either_message_fail(self):
        for index in (0, 1):
            for hot in (temperature_payload(target=1), temperature_payload(bed_target=1)):
                samples = [temperature_payload(), temperature_payload()]; samples[index] = hot
                with self.assertRaises(ValueError):
                    p.verify_capture(synthetic_capture('GetStatus', synthetic_wire('GetStatus', samples)), 'GetStatus', TOKEN)

    def test_failed_client_outcomes_never_success(self):
        for method in p.METHODS:
            for outcome in (1, 2, 3, 4, 5, 6, 7, 143, 137, 20 if method == 'PrinterState' else 0):
                with self.assertRaises(ValueError):
                    p.verify_capture(synthetic_capture(method, exit_code=outcome), method, TOKEN)

    def test_truncated_repeated_and_contaminated_capture(self):
        for method in p.METHODS:
            good = synthetic_capture(method)
            self.assertIsNone(p.verify_capture(good[:-8], method, TOKEN))
            for invalid in (good + good, good.replace('0000000 ', '0000001 ', 1), good.replace('0000000 ', 'garbage\n0000000 ', 1), good.replace('0000000 ', '*\n0000000 ', 1), good.replace('11.01 0.00', '09.99 0.00'), good.replace('10.00 0.00', 'nan 0.00')):
                with self.assertRaises(ValueError):
                    p.verify_capture(invalid, method, TOKEN)

    def test_http2_all_truncations_fail(self):
        for method in p.METHODS:
            wire = synthetic_wire(method)
            for size in range(len(wire)):
                with self.subTest(method=method, size=size), self.assertRaises(ValueError):
                    p.response_messages(wire[:size], method)

    def test_server_errors_and_bad_frames(self):
        for method in p.METHODS:
            good = synthetic_wire(method)
            bad_headers = (b'\x8e' + raw_header(b'content-type', b'application/grpc'), b'\x88', b'\x88' + raw_header(b'content-type', b'application/grpc') + raw_header(b'grpc-status', b'13'))
            for headers in bad_headers:
                with self.assertRaises(ValueError):
                    p.response_messages(synthetic_wire(method, headers=headers), method)
            for frame in (p.frame(3, 0, 1, bytes(4)), p.frame(7, 0, 0, bytes(8)), p.frame(5, 0, 1), p.frame(99, 0, 0), p.frame(6, 0, 0, b'a'), p.frame(4, 0, 1), p.frame(4, 0, 0, b'\0\2' + bytes(4)), p.frame(8, 0, 0, bytes(4)), p.frame(9, 4, 1), p.frame(1, 128, 1)):
                with self.assertRaises(ValueError):
                    p.response_messages(frame + good, method)
            with self.assertRaises(ValueError):
                p.response_messages(good + p.frame(4, 0, 0), method)
        with self.assertRaises(ValueError):
            p.response_messages(synthetic_wire('PrinterState').replace(raw_header(b'grpc-status', b'0'), raw_header(b'grpc-status', b'1')), 'PrinterState')

    def test_fragmented_messages_and_headers(self):
        headers = b'\x88' + raw_header(b'content-type', b'application/grpc')
        payload = b''.join(b'\0' + len(pb).to_bytes(4, 'big') + pb for pb in (temperature_payload(0, 0), temperature_payload()))
        wire = p.frame(1, 0, 1, headers[:2]) + p.frame(9, 4, 1, headers[2:])
        wire += p.frame(0, 0, 1, payload[:3]) + p.frame(0, 0, 1, payload[3:8]) + p.frame(0, 0, 1, payload[8:])
        self.assertEqual(len(p.response_messages(wire, 'GetStatus')), 2)
        with self.assertRaises(ValueError):
            p.response_messages(p.frame(1, 0, 1, headers[:2]) + p.frame(4, 0, 0) + p.frame(9, 4, 1, headers[2:]), 'GetStatus')

    def test_protobuf_malformed_duplicates_missing(self):
        good = temperature_payload()
        for malformed in (b'', good[:-1], b'\0', b'\x0a\xff', nested(1, nested(2, b'')), nested(1, nested(2, b'\x08\x19\x08\x19') + nested(3, b'')), good + good, nested(1, nested(2, b'\x08\x80\0') + nested(3, b''))):
            with self.assertRaises(ValueError):
                p.decode_status(malformed)
        for malformed in (b'', b'\x12\x05ready\x12\x05ready', b'\x0a\x01x\x12\x05ready', b'\x22\0\x12\x05ready'):
            with self.assertRaises(ValueError):
                p.state_payload(malformed)


class OwnershipTimingTests(unittest.TestCase):
    def test_single_owner_pending_latch_and_external_append(self):
        with tempfile.TemporaryDirectory(dir=HERE) as temp:
            path = Path(temp) / 'console'; path.touch()
            owner = observer.ConsoleOwner(path)
            try:
                with self.assertRaises(BlockingIOError):
                    observer.ConsoleOwner(path)
                owner.append_once('first', 'first\n')
                with self.assertRaises(ValueError):
                    owner.append_once('second', 'second\n')
                with self.assertRaises(ValueError):
                    owner.complete('wrong')
                owner.complete('first'); owner.append_once('second', 'second\n')
                with path.open('ab') as stream:
                    stream.write(b'outside\n')
                with self.assertRaises(ValueError):
                    owner.complete('second')
                self.assertTrue(owner.failed)
            finally:
                owner.close()

    def test_uncertain_partial_write_permanently_latches(self):
        with tempfile.TemporaryDirectory(dir=HERE) as temp:
            path = Path(temp) / 'console'; path.touch()
            owner = observer.ConsoleOwner(path)
            try:
                with mock.patch.object(observer.os, 'write', return_value=1), self.assertRaises(OSError):
                    owner.append_once('rpc', 'abc\n')
                self.assertEqual(owner.pending, 'rpc')
                self.assertTrue(owner.failed)
                with self.assertRaises(ValueError):
                    owner.append_once('retry', 'abc\n')
            finally:
                owner.close()

    def test_symlink_and_preexisting_commands_refused(self):
        with tempfile.TemporaryDirectory(dir=HERE) as temp:
            path = Path(temp) / 'console'; path.write_text('already here\n')
            with self.assertRaises(ValueError):
                observer.ConsoleOwner(path)
            link = Path(temp) / 'link'; link.symlink_to(path)
            with self.assertRaises(OSError):
                observer.ConsoleOwner(link)

    def test_deadlines_and_freshness(self):
        observer.check_deadlines(600, 442, 9_500_000_000)
        for args in ((860, 700, 9_000_000_000), (622, 442, 9_000_000_000), (500, 442, 15_000_000_000)):
            with self.assertRaises(TimeoutError):
                observer.check_deadlines(*args)
        with self.assertRaises(TimeoutError):
            observer.check_deadlines(500, 442, 14_000_000_001, {'queued_host_elapsed_seconds': 450, 'queued_shared_mcu_ns': 9_000_000_000})

    def test_clock_schema_and_monotonicity(self):
        for field, value in [('schema', True), ('enabled', False), ('time_went_backwards', True), ('virtual_time_ns', True), ('sequence', -1), ('epoch', '')]:
            sample = clock_sample(); sample[field] = value
            with self.assertRaises(ValueError):
                observer.Clock().observe(sample)
        clock = observer.Clock(); clock.observe(clock_sample())
        for sample in (clock_sample(7_000_000_000, 2), {**clock_sample(8_100_000_000, 2), 'epoch': 'changed'}, clock_sample(8_100_000_000, 1)):
            with self.assertRaises(ValueError):
                clock.observe(sample)

    def test_optimized_rejected_before_imports_or_files(self):
        for file in ('observer.py', 'protocol.py'):
            for optimization in ('-O', '-OO'):
                code = 'exec(compile(' + repr((HERE / file).read_text()) + ', "<synthetic-no-file-context>", "exec"), {"__file__": "/nonexistent/ambient/file.py"})'
                result = subprocess.run([sys.executable, '-I', optimization, '-c', code], capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('before imports or I/O', result.stderr)

    def test_unrecognized_cli_and_fixed_environment(self):
        for options in (['x', '--method', 'Homing'], ['x', '--target', '0'], ['x', '--seconds', '900'], ['../x']):
            with mock.patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit):
                observer.parse_args(options)
        environment = observer.fixed_environment(868)
        for key, value in {'THERMAL_PROFILE': 'none', 'Z_PROBE_PROFILE': 'none', 'RENODE_BOOTSTRAP': 'legacy', 'CLOCK_CLIENT': 'scalar', 'GLOBAL_QUANTUM_US': '1', 'ICOUNT_SHIFT': '0', 'NATIVE_NOZZLE_HEATER': '0'}.items():
            self.assertEqual(environment[key], value)


class FaultTelemetryTests(unittest.TestCase):
    def test_pinned_baseline_templates_reproduced_without_native_run(self):
        observer.verify_classification_baseline()

    def test_exact_auxiliary_classification_and_unknown_errors(self):
        for message, source in observer.AUXILIARY.items():
            line = f'[1970-01-01 00:00:01.000] [error] [{source}] {message}\n'
            review = observer.NativeReview(); self.assertTrue(review.observe(line + READY_LINE))
            self.assertEqual(len(review.occurrences), 1)
            for bad in (line.replace(f'[{source}]', '[999]'), line.replace('01.000', '07.000'), line.replace(message, message + ' unexpected')):
                with self.assertRaises(ValueError):
                    observer.NativeReview().observe(bad + READY_LINE)
        good_video = '[1970-01-01 00:00:07.000] [error] [211] ' + observer.VIDEO + '\n'
        observer.NativeReview().observe(READY_LINE + good_video)
        for bad in (good_video.replace('50052', '50051'), good_video.replace('[211]', '[212]'), '[error] malformed\n', 'MCU shutdown\n', 'sensor fault\n', '[1970-01-01 00:00:08.000] [warning] [1] MCU timeout\n'):
            with self.assertRaises(ValueError):
                observer.NativeReview().observe(READY_LINE + bad)

    def test_unterminated_final_fault_rejected(self):
        for suffix in ('MCU shutdown', '[error] truncated', 'sensor fault'):
            with self.assertRaises(ValueError):
                observer.NativeReview().observe(READY_LINE + suffix, final=True)
        observer.NativeReview().observe(READY_LINE + '/ # ', final=True)

    def test_passive_missing_fault_nonzero_and_stale(self):
        trace = observer.PassiveNozzle()
        rows = [passive_row(0, 'snapshot:stream_started'), passive_row(100000)]
        trace.consume(csv_bytes(rows), 8_000_000_000)
        self.assertEqual(trace.summary()['row_count'], 2)
        for key, value in [('pb8_level', '1'), ('sensor_fault', 'open'), ('last_heater_duty', '1'), ('physical_temperature_c', 'nan'), ('published_adc_code', '0'), ('model_overtemperature', '1'), ('event', 'snapshot:MCU_reset_observed')]:
            bad = passive_row(200000); bad[key] = value
            with self.assertRaises(ValueError):
                trace.consume(csv_bytes(rows + [bad]), 8_100_000_000)
        with self.assertRaises(ValueError):
            trace.consume(csv_bytes(rows + [passive_row(100000)]), 8_100_000_000)
        with self.assertRaises(ValueError):
            trace.consume(csv_bytes(rows[:-1]), 8_100_000_000)


class FakeFixture:
    """No subprocess. Emits only explicitly synthetic read-only responses."""
    def __init__(self, root, name, *, bad_status=False, uncertain=False):
        self.path = root / 'runs' / name; self.path.mkdir()
        (self.path / 'console-input.commands').touch()
        (self.path / 'console.bin').write_text(READY_LINE + 'COUPLED_STARTUP_COMMANDS_DONE\n')
        self.rows = [passive_row(0, 'snapshot:stream_started'), passive_row(8_000_000)]
        (self.path / 'nozzle-thermal-live.csv').write_bytes(csv_bytes(self.rows))
        self.clock = clock_sample(); self.write_clock()
        self.done = False; self.seen = 0; self.phase = 0; self.bad_status = bad_status

    def write_clock(self):
        (self.path / 'virtual-time.json').write_text(json.dumps(self.clock))

    def export(self):
        (self.path / 'nozzle-thermal.csv').write_bytes(csv_bytes([passive_row(0, 'snapshot:observer_attached')] + self.rows))
        value = {'rows': len(self.rows) + 1, 'stream_rows_written': len(self.rows), 'last_stream_error': ''}
        for key in ('dropped_rows', 'stream_dropped_rows', 'stream_error_count'):
            value[key] = 0
        for key in ('capacity_reached', 'stream_capacity_reached', 'stream_write_outcome_uncertain', 'streaming', 'stream_requested', 'actuator_connection_created', 'firmware_guard_state_recorded'):
            value[key] = False
        (self.path / 'nozzle-thermal-live-status.json').write_text(json.dumps(value))

    def poll(self):
        if (self.path / 'stop-request').exists():
            self.export(); self.done = True; return 0
        commands = (self.path / 'console-input.commands').read_text()
        if len(commands) > self.seen:
            self.seen = len(commands); self.phase += 1
            if self.phase == 1:
                output = p.shell_check_expected(TOKEN)
            elif self.phase <= 3:
                method = 'PrinterState' if self.phase == 2 else 'GetStatus'
                samples = [temperature_payload(), temperature_payload(0, 0)] if self.bad_status and method == 'GetStatus' else None
                output = synthetic_capture(method, synthetic_wire(method, samples))
            else:
                output = 'AMB_' + TOKEN + '_F_B\n' + READY_LINE + 'AMB_' + TOKEN + '_F_E\n'
            with (self.path / 'console.bin').open('a') as stream:
                stream.write(output)
            self.clock['virtual_time_ns'] += 400_000_000 if self.phase == 1 else 1_000_000_000
            self.clock['sequence'] += 1; self.write_clock()
            self.rows.append(passive_row(self.clock['virtual_time_ns'] // 1000))
            (self.path / 'nozzle-thermal-live.csv').write_bytes(csv_bytes(self.rows))
        return None

    def wait(self, timeout=None):
        value = self.poll()
        if value is None:
            raise AssertionError('Mock fixture was not stopped before wait')
        return value


class LifecycleTests(unittest.TestCase):
    def run_synthetic(self, temp, bad_status=False, jump_after_artifact=False, jump_shell_artifact=False, stop_shell_artifact=False):
        root = Path(temp); (root / 'runs').mkdir()
        fixture = None
        tick = [1000.0]
        def monotonic():
            tick[0] += .01
            return tick[0]
        def launch(command, env):
            nonlocal fixture
            self.assertEqual(command, [str(root / 'rv1106-at32-link/scripts/run_native_event_fixture.sh'), 'synthetic-new-run'])
            self.assertEqual(env['THERMAL_PROFILE'], 'none')
            fixture = FakeFixture(root, 'synthetic-new-run', bad_status=bad_status)
            return fixture
        original_create = observer.create_bytes
        def create(path, data):
            original_create(path, data)
            if jump_shell_artifact and path.name == 'shell-check.capture.txt':
                tick[0] += 31
            if stop_shell_artifact and path.name == 'shell-check.capture.txt':
                (path.parent / 'stop-request').write_text('Synthetic stop during persistence')
            if jump_after_artifact and path.name == 'printer-state.commands':
                tick[0] += 700
        cache = str(root / 'synthetic-new-run-python-cache')
        with mock.patch.object(observer, 'ROOT', root), mock.patch.object(observer, 'verify_classification_baseline'), mock.patch.object(observer.subprocess, 'Popen', side_effect=launch) as popen, mock.patch.object(observer.time, 'monotonic', side_effect=monotonic), mock.patch.object(observer.time, 'sleep'), mock.patch.object(observer.secrets, 'token_hex', return_value=TOKEN), mock.patch.object(observer.sys, 'pycache_prefix', cache), mock.patch.object(observer.sys, 'dont_write_bytecode', True), mock.patch.object(observer.sys, 'flags', mock.Mock(isolated=1)), mock.patch.dict(observer.os.environ, {'PYTHONPYCACHEPREFIX': cache}), mock.patch.object(observer, 'create_bytes', side_effect=create):
            code = observer.main(['synthetic-new-run', '--seconds', '868'])
        self.assertEqual(popen.call_count, 1)
        report = json.loads((fixture.path / observer.REPORT_NAME).read_text())
        return code, report, fixture

    def test_complete_new_synthetic_lifecycle(self):
        with tempfile.TemporaryDirectory(dir=HERE) as temp:
            code, report, fixture = self.run_synthetic(temp)
            self.assertEqual(code, 0, report)
            with mock.patch('builtins.open', side_effect=AssertionError('Final gate must be pure')), mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('Final gate must not read files')):
                self.assertIs(observer.validate_final_report(report), report)
            self.assertEqual(report['requests'], ['PrinterState', 'GetStatus'])
            self.assertTrue(report['final_log_verified'])
            self.assertEqual(fixture.phase, 4)
            self.assertFalse(report['passive_bed']['available'])
            self.assertEqual(json.loads((fixture.path / observer.READY_NAME).read_text())['phase'], 'verified_ready')
            self.assertTrue((fixture.path / 'get-status.message2.protobuf.bin').exists())
            self.check_corrupted_reports(report)

    def check_corrupted_reports(self, report):
        changes = [(('shell_check_result',), None), (('shell_check_result', 'exit_status'), 0), (('batches',), []), (('request_count',), 1), (('requests',), ['GetStatus', 'PrinterState']), (('pending_batch',), {'uncertain': True}), (('queue_outcomes',), ['appended', 'uncertain']), (('status_result', 'selected_sequence'), 1), (('status_result', 'transport_exit_status'), 0), (('status_result', 'remote_cancel_acknowledged'), True), (('final_export_requested',), False), (('launcher_exit_code',), 1), (('bounds', 'post_ready_host_seconds'), 900), (('ambient_complete_host_elapsed_seconds',), float('nan')), (('ready_result', 'queued_host_elapsed_seconds'), 681), (('last_shared_mcu_ns',), 15_000_000_000), (('passive_nozzle', 'final_export_verified'), False), (('status_queue_passive_source_us',), int(report['passive_nozzle']['latest']['time_us']))]
        for keys, value in changes:
            bad = copy.deepcopy(report); destination = bad
            for key in keys[:-1]:
                destination = destination[key]
            destination[keys[-1]] = value
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                observer.validate_final_report(bad)
        bad = copy.deepcopy(report)
        bad['status_result']['messages'][1]['temperatures']['nozzle']['current'] = 26
        bad['status_result']['selected_temperatures']['nozzle']['current'] = 26
        with self.assertRaises(ValueError):
            observer.validate_final_report(bad)

    def test_default_zero_second_fails_no_retry(self):
        with tempfile.TemporaryDirectory(dir=HERE) as temp:
            code, report, fixture = self.run_synthetic(temp, bad_status=True)
            self.assertEqual(code, 2)
            self.assertEqual(report['request_count'], 2)
            self.assertEqual(fixture.phase, 3)
            self.assertEqual((fixture.path / 'get-status.message2.protobuf.bin').read_bytes(), temperature_payload(0, 0))
            self.assertTrue((fixture.path / 'get-status.response.http2.bin').exists())
            self.assertTrue(report['final_export_requested'])
            self.assertEqual(json.loads((fixture.path / observer.READY_NAME).read_text())['phase'], 'invalid')
            with self.assertRaises(ValueError):
                observer.validate_final_report(report)

    def test_artifact_write_deadline_does_not_queue(self):
        with tempfile.TemporaryDirectory(dir=HERE) as temp:
            code, report, fixture = self.run_synthetic(temp, jump_after_artifact=True)
            self.assertEqual(code, 2)
            self.assertEqual((fixture.path / 'console-input.commands').read_text(), p.shell_check_command_batch(TOKEN))
            self.assertEqual(fixture.phase, 1)
            self.assertIn('deadline', report['error'].lower())


if __name__ == '__main__':
    unittest.main()
