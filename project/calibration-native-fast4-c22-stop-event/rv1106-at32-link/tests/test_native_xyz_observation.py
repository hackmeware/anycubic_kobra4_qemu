"""Offline only: captured wire/log tests plus mocked controller; no emulator/client runs."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('native_xyz_observation', ROOT / 'rv1106-at32-link/scripts/run_native_xyz_observation.py')
m = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(m)
TOKEN = 'ab' * 12
READY = '[1970-01-01 00:00:10.604] [info] [527] Printer is ready at 10.60463492.\n'
CAPTURED_LOG = (ROOT / 'evidence/native-xy-quantum1-final/native-home-log-extract.txt').read_text()
PROFILE = {'selection': m.PROFILE, 'global_quantum_ns': 1000, 'maximum_state_age_ns': 100000,
           'maximum_producer_lead_ns': 1000, 'physical_timing_fidelity': False, 'firmware_changes': False,
           'experimental': True, 'clock_or_mips_changes': False, 'physical_geometry_and_calibration_verified': False,
           'parameters': {'bed_relative_mm': -10.0, 'opposite_stop_relative_mm': 252.0, 'bed_side': 'minimum',
                          'stiffness_n_per_mm': 20.0, 'damping_ns_per_mm': 0.05, 'baseline_counts': 0,
                          'counts_per_n': 10000.0, 'signal_polarity': 1, 'history_capacity': 4096, 'query_trace_rows': 100000},
           'probe_wiring': {'source': 'actual nozzle PA7 resolved GPIO', 'destination': 'main PB2', 'noninverting_assumption': True}}


def write_profiles(directory, tmc_model='fixed', *, bad_profile=False, wrong_manifest=False):
    """Only test metadata, with hashes identifying mock source bytes, never a native run."""
    model = tmc_model
    if wrong_manifest:
        model = 'autobaud' if tmc_model == 'fixed' else 'fixed'
    source = ('nozzle-renode/peripherals/VirtualNozzleTmc2209.cs' if model == 'fixed' else
              'nozzle-renode/experimental/tmc-native-replay/VirtualNozzleTmc2209Autobaud.cs')
    entry = {'board': 'nozzle', 'source': source, 'source_sha256': '1' * 64,
             'generated': 'nozzle/peripherals/VirtualNozzleTmc2209.cs', 'generated_sha256': '2' * 64}
    selected = {'selection': tmc_model, 'experimental': tmc_model == 'autobaud'}
    if model == 'autobaud':
        entry['experimental_tmc_model'] = 'autobaud'
    if tmc_model == 'autobaud':
        selected.update({key: entry[key] for key in ('source', 'source_sha256', 'generated_sha256')})
        selected.update(transformation='namespace and class identity only', gpio_sync_time_added=False,
                        turnaround_tuned=False, firmware_changed=False)
    (directory / 'z-probe-profile.json').write_text(json.dumps(PROFILE))
    (directory / 'shared-profile.json').write_text(json.dumps({'z_probe_profile': {} if bad_profile else PROFILE,
                                                             'nozzle_tmc_model': selected}))
    (directory / 'shared-model-manifest.json').write_text(json.dumps([entry]))
    (directory / 'scheduling-experiment.json').write_text(json.dumps({'tmc_model': tmc_model, 'global_quantum_us': 1,
                                                                    'tmc_model_changes': tmc_model == 'autobaud'}))


def frame(kind, flags, payload=b'', stream=1):
    return len(payload).to_bytes(3, 'big') + bytes([kind, flags]) + stream.to_bytes(4, 'big') + payload


def literal(name, value):
    return b'\0' + bytes([len(name)]) + name + bytes([len(value)]) + value


def wire(protobuf=b'', status=b'0'):
    return (frame(1, 4, b'\x88') + frame(0, 0, b'\0' + len(protobuf).to_bytes(4, 'big') + protobuf) +
            frame(1, 5, literal(b'grpc-status', status)))


def req(stage):
    return {'begin': 'XYZ_' + stage.upper() + '_BEGIN_' + TOKEN,
            'end': 'XYZ_' + stage.upper() + '_END_' + TOKEN,
            'method': 'PrinterState' if stage == 'ready' else 'Homing'}


def od(data):
    return ''.join(f'{i:07o} ' + ' '.join(f'{byte:03o}' for byte in data[i:i+16]) + '\n'
                   for i in range(0, len(data), 16)) + f'{len(data):07o}\n'


def capture(stage, data=None, status=0, transport=0):
    if data is None:
        data = bytes.fromhex((ROOT / 'rv1106-at32-link/tests/fixtures/native-ready-response.hex').read_text()) if stage == 'ready' else wire()
    request = req(stage)
    return (request['begin'] + '\nREADY_CLIENT_STATUS=' + str(status) + '\n' + m.ready.RAW_BEGIN + '\n' + od(data) +
            m.ready.RAW_END + '\nGRPC_PROBE_TRANSPORT_EXIT=' + str(transport) + '\nGRPC_PROBE_DONE\n' + request['end'] + '\n')


def rail(axis, event='Complete', stamp='31.000'):
    return '[1970-01-01 00:00:' + stamp + '] [info] [447] Home Rail ' + event + ' - stepper: ' + axis.lower() + '\n'


def rail_pair(axis):
    if axis in ('X', 'Y'):
        return ''.join(line + '\n' for line in CAPTURED_LOG.splitlines() if line.endswith(axis.lower()))
    # Artificial parser/controller fixture only. Never claimed as native Z evidence.
    return rail(axis, 'Begin', '28.000') + rail(axis, 'Complete', '31.000')


class PacketAndParserTests(unittest.TestCase):
    def test_exact_allowed_schemas_and_inert_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = pathlib.Path(temporary)
            for stage in ('ready', 'X', 'Y', 'Z'):
                with self.subTest(stage=stage):
                    request = m.prepare_request(directory, stage, TOKEN)
                    expected = b'' if stage == 'ready' else b'\x0a\x01' + stage.encode()
                    self.assertEqual(bytes.fromhex(request['protobuf_hex']), expected)
                    packet = (directory / ('xyz-' + stage.lower() + '.http2.bin')).read_bytes()
                    elf = (directory / ('xyz-' + stage.lower() + '.elf')).read_bytes()
                    self.assertEqual(m.transport.extract_packet(elf), packet)
                    self.assertIn(b'127.0.0.1:50051', packet)
                    self.assertEqual(request['commands'].count('timeout -t 5 '), 1)
                    self.assertEqual(request['commands'].count('$?'), 1)
                    self.assertNotIn('RunGcodeScript', request['commands'])
            self.assertEqual((directory / 'xyz-z.protobuf.bin').read_bytes(),
                             (ROOT / 'evidence/normal-z-calibration/homing-z.protobuf.bin').read_bytes())

    def test_disallows_gcode_empty_or_multiple_axes(self):
        for method, axis in [('StartPrint', None), ('RunGcodeScript', None), ('Homing', None), ('Homing', ''),
                             ('Homing', 'XYZ'), ('Homing', 'z'), ('PrinterState', 'Z')]:
            with self.subTest(method=method, axis=axis), self.assertRaises(ValueError): m.request_packet(method, axis)

    def test_xy_packets_byte_identical_to_historical_generated_packets(self):
        for axis, name in [('X', 'auto-home'), ('Y', 'auto-home-y')]:
            old = (ROOT / 'runs/native-xy-quantum1' / name).read_bytes()
            packet, _ = m.request_packet('Homing', axis)
            self.assertEqual(packet, m.transport.extract_packet(old))

    def test_historical_rpc_fixtures_match_saved_console_and_are_only_acceptance(self):
        text = (ROOT / 'runs/native-xy-quantum1/console.bin').read_text(errors='replace')
        for axis, end in [('X', 'AUTO_G28_X_SENT'), ('Y', 'AUTO_G28_Y_PROBE_DONE')]:
            region = m.ready.bounded_region(text, 'AUTO_G28_' + axis + '_BEGIN', end)
            original = m.ready.read_od(region)
            saved = bytes.fromhex((ROOT / 'evidence/native-xyz-observer' / ('historical-homing-' + axis.lower() + '.hex')).read_text())
            self.assertEqual(saved, original)
            result = m.homing_response(saved)
            self.assertTrue(result['rpc_acceptance_verified'])
            self.assertFalse(result['native_completion_proven_by_rpc'])

    def test_complete_capture_and_readiness(self):
        self.assertTrue(m.verify_capture(capture('X'), req('X'))['rpc_acceptance_verified'])
        self.assertEqual(m.verify_capture(capture('ready'), req('ready'))['ready_response']['state'], 'ready')

    def test_empty_error_and_nested_application_error(self):
        self.assertTrue(m.homing_response(wire(b'\x0a\0'))['rpc_acceptance_verified'])
        error = b'\x08\xff\xff\x03\x12\x04busy'
        result = m.homing_response(wire(b'\x0a' + bytes([len(error)]) + error))
        self.assertFalse(result['rpc_acceptance_verified'])
        self.assertEqual(result['application_error'], {'code': 65535, 'message': 'busy'})
        # Even a serialized default-valued nonempty error object is not guessed successful.
        self.assertFalse(m.homing_response(wire(b'\x0a\x02\x08\x00'))['rpc_acceptance_verified'])

    def test_bad_protobufs_rejected(self):
        for pb in [b'\0', b'\x12\0', b'\x0a\0\x0a\0', b'\x08\0', b'\x0a\x03x', b'\x0a\x02\x18\0',
                   b'\x0a\x04\x08\0\x08\0', b'\x0a\x0b\x08' + b'\x80' * 9 + b'\x02']:
            with self.subTest(pb=pb), self.assertRaises(ValueError): m.homing_response(wire(pb))

    def test_incomplete_echo_stale_and_duplicate_captures(self):
        full = capture('X')
        for text in ['', full[:-1], 'echo ' + req('X')['begin'] + '\n', full[:full.index(req('X')['end'])]]:
            with self.subTest(text=text): self.assertIsNone(m.verify_capture(text, req('X')))
        self.assertIsNone(m.verify_capture(full, req('Y')))
        for text in [full + full, req('X')['end'] + '\n', full.replace('READY_RAW_END\n', ''),
                     full.replace('READY_CLIENT_STATUS=0\n', 'READY_CLIENT_STATUS=0\nREADY_CLIENT_STATUS=0\n'),
                     full.replace('0000000', '0000001', 1)]:
            with self.subTest(text=text), self.assertRaises(ValueError): m.verify_capture(text, req('X'))

    def test_nonzero_or_missing_transport_status_never_accepts(self):
        for status, transport in [(0, 5), (5, 0), (143, 143), (2, 2)]:
            with self.subTest(status=status), self.assertRaises(ValueError):
                m.verify_capture(capture('X', status=status, transport=transport), req('X'))
        with self.assertRaises(ValueError):
            m.verify_capture(capture('X').replace('GRPC_PROBE_TRANSPORT_EXIT=0\n', ''), req('X'))

    def test_framing_and_nonzero_status_fail_closed(self):
        good = wire()
        for data in [good[:-1], good + b'\0', wire(status=b'1'), wire(status=b'00'),
                     frame(1, 4, b'\x88') + frame(3, 0, bytes(4)),
                     frame(1, 5, b'\x88' + literal(b'grpc-status', b'0')),
                     frame(1, 4, b'\x88') + frame(0, 1, bytes(5)),
                     good.replace(b'\x88', b'\x8c', 1),
                     good.replace(literal(b'grpc-status', b'0'), literal(b'grpc-message', b'grpc-status\x010')),
                     good.replace(literal(b'grpc-status', b'0'), literal(b'grpc-status', b'0') * 2),
                     frame(1, 4, b'\x88', 3) + good,
                     frame(0, 0, bytes(5)) + frame(1, 4, b'\x88') + frame(1, 5, literal(b'grpc-status', b'0')),
                     frame(7, 0, bytes(4) + b'\0\0\0\x01', 0) + good]:
            with self.subTest(data=data), self.assertRaises(ValueError): m.homing_response(data)

    def test_fragmented_frames_and_continuation_supported(self):
        trailer = literal(b'grpc-status', b'0')
        data = (frame(1, 4, b'\x88') + frame(0, 0, b'\0\0') + frame(0, 0, b'\0\0\0') +
                frame(1, 1, trailer[:3]) + frame(9, 4, trailer[3:]))
        self.assertTrue(m.homing_response(data)['rpc_acceptance_verified'])
        with self.assertRaises(ValueError): m.homing_response(data.replace(frame(9, 4, trailer[3:]), frame(9, 4, trailer[3:], 3)))


class SequencingTests(unittest.TestCase):
    def new(self, axis='X', initial=READY):
        return m.AxisObservation(axis, initial, req(axis), 0)

    def test_native_rail_log_and_rpc_are_both_required(self):
        for suffix in [capture('X'), req('X')['begin'] + '\n' + rail_pair('X'), capture('X') + rail('X')]:
            observer = self.new(); observer.observe(READY + suffix, 1)
            self.assertFalse(observer.complete())
        observer = self.new(); observer.observe(READY + capture('X') + rail_pair('X'), 1)
        self.assertTrue(observer.complete())
        self.assertFalse(observer.state['physical_causal_chain_verified'])

    def test_completion_before_response_end_is_supported(self):
        full = capture('X'); end = full.index(req('X')['end'])
        observer = self.new(); text = READY + full[:end] + rail_pair('X')
        observer.observe(text, 1); self.assertFalse(observer.complete())
        observer.observe(text + full[end:], 2); self.assertTrue(observer.complete())

    def test_stale_echo_partial_or_wrong_axis_cannot_complete(self):
        for logs in [rail_pair('X').rstrip('\n'), 'echo ' + rail_pair('X'), rail_pair('Y'),
                     rail_pair('X').replace('stepper: x', 'stepper: x2'), rail('X') + rail('X', 'Begin', '32.000')]:
            observer = self.new(); observer.observe(READY + capture('X') + logs, 1)
            self.assertFalse(observer.complete())
        initial = READY + rail_pair('X')
        observer = self.new(initial=initial); observer.observe(initial + capture('X') + rail_pair('X'), 1)
        self.assertFalse(observer.complete())
        observer = self.new(initial=READY + '[1970-01-01 00:00:20.000] [info] [2] Current state\n')
        observer.observe(READY + '[1970-01-01 00:00:20.000] [info] [2] Current state\n' + capture('X') + rail_pair('X'), 1)
        self.assertFalse(observer.complete())

    def test_unexpected_guard_fallback_axis_stops_z(self):
        observer = self.new('Z'); observer.observe(READY + capture('Z') + rail_pair('X'), 1)
        self.assertIn('Unexpected native axis', observer.state['failure'])
        self.assertFalse(observer.complete())

    def test_native_failures_preserved_and_block_progress(self):
        for message in ['Must home X and Y axes first', 'Homing failed', 'No trigger on z after full movement']:
            observer = self.new('Z')
            observer.observe(READY + capture('Z') + rail_pair('Z') +
                             '[1970-01-01 00:00:32.000] [error] [12] ' + message + '\n', 1)
            self.assertFalse(observer.complete()); self.assertTrue(observer.state['native_failure_lines'])

    def test_exact_known_camera_error_retained_without_masking_other_errors(self):
        observer = self.new()
        camera = '[1970-01-01 00:00:17.608] [error] [211] ' + m.KNOWN_ABSENT_VIDEO_SERVICE + '\n'
        observer.observe(READY + capture('X') + rail_pair('X') + camera, 1)
        self.assertTrue(observer.complete()); self.assertEqual(observer.state['known_absent_video_service_lines'], [camera.rstrip()])
        observer.observe(READY + capture('X') + rail_pair('X') + camera + camera.replace('50052', '50053'), 2)
        self.assertFalse(observer.complete())

    def test_profile_metadata_must_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary)
            write_profiles(path)
            self.assertEqual(m.validate_profile(path), PROFILE)
            for key, value in [('selection', 'none'), ('global_quantum_ns', 10000), ('maximum_state_age_ns', 100001),
                               ('maximum_producer_lead_ns', 0), ('physical_timing_fidelity', True), ('firmware_changes', True)]:
                changed = dict(PROFILE, **{key: value})
                (path / 'z-probe-profile.json').write_text(json.dumps(changed))
                with self.subTest(key=key), self.assertRaises(ValueError): m.validate_profile(path)

    def test_tmc_selection_matches_shared_profile_manifest_and_schedule(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary)
            for model in ('fixed', 'autobaud'):
                with self.subTest(model=model):
                    write_profiles(path, model)
                    self.assertEqual(m.validate_profile(path, model), PROFILE)
                    other = 'autobaud' if model == 'fixed' else 'fixed'
                    with self.assertRaisesRegex(ValueError, 'differs from shared profile'):
                        m.validate_profile(path, other)
                    write_profiles(path, model, wrong_manifest=True)
                    with self.assertRaisesRegex(ValueError, 'manifest'):
                        m.validate_profile(path, model)

    def test_bad_tmc_hash_duplicate_entry_or_schedule_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary)
            for fault in ('mismatched_hash', 'malformed_hash', 'missing_entry', 'duplicate_entry', 'schedule_model', 'quantum'):
                with self.subTest(fault=fault):
                    write_profiles(path, 'autobaud')
                    manifest_file = path / 'shared-model-manifest.json'
                    entries = json.loads(manifest_file.read_text())
                    if fault == 'mismatched_hash': entries[0]['source_sha256'] = '3' * 64
                    if fault == 'malformed_hash': entries[0]['generated_sha256'] = 'not-a-hash'
                    if fault == 'missing_entry': entries = []
                    if fault == 'duplicate_entry': entries += copy.deepcopy(entries)
                    manifest_file.write_text(json.dumps(entries))
                    schedule_file = path / 'scheduling-experiment.json'
                    schedule = json.loads(schedule_file.read_text())
                    if fault == 'schedule_model': schedule['tmc_model'] = 'fixed'
                    if fault == 'quantum': schedule['global_quantum_us'] = 10
                    schedule_file.write_text(json.dumps(schedule))
                    with self.assertRaises(ValueError): m.validate_profile(path, 'autobaud')

    def test_capped_trace_is_not_physical_validation(self):
        record = {'artifacts': {name: {'exists': True} for name in m.ARTIFACTS},
                  'z-force-status': {'bound': True, 'faulted': False, 'last_error': '', 'dropped_query_trace_rows': 9},
                  'z-sensor-status': {'timed_provider_bound': True, 'dropped': 100}}
        self.assertEqual(m.assess_exports(record), [])
        self.assertEqual(len(record['evidence_warnings']), 3)
        record['z-force-status']['faulted'] = True
        self.assertTrue(m.assess_exports(record))


class ControllerTests(unittest.TestCase):
    def run_fake(self, steps, *, options=(), fail_generation=None, partial_write=False, existing_stop=False,
                 stop_during_generation=False, bad_profile=False, force_fault=False, missing_exports=False,
                 wall_ticks=None, cleanup_timeout=False, manifest_model=None, wrong_manifest=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary); directory = root / 'runs' / 'test'
            calls, timeline = [], []
            real_prepare, original_open = m.prepare_request, pathlib.Path.open

            class FakeProcess:
                pid = 987654321
                def __init__(self):
                    directory.mkdir(parents=True)
                    (directory / 'console-input.commands').write_text('')
                    model = options[options.index('--nozzle-tmc-model') + 1] if '--nozzle-tmc-model' in options else 'fixed'
                    write_profiles(directory, manifest_model or model, bad_profile=bad_profile, wrong_manifest=wrong_manifest)
                    if existing_stop: (directory / 'stop-request').write_text('External stop\n')
                    self.index, self.text, self.waits = 0, '', 0
                def poll(self):
                    if self.index >= len(steps): return 0
                    now, addition = steps[self.index]; self.index += 1
                    self.text = addition[0] if isinstance(addition, tuple) else self.text + addition
                    (directory / 'console.bin').write_text(self.text)
                    (directory / 'virtual-time.json').write_text(json.dumps({'virtual_time_ns': now}))
                    timeline.append((now, (directory / 'console-input.commands').read_text()))
                    return None
                def wait(self, timeout=None):
                    self.waits += 1
                    if cleanup_timeout and self.waits == 1: raise subprocess.TimeoutExpired('mock', timeout)
                    (directory / 'mock-final-export').write_text('Mock witness only')
                    if not missing_exports:
                        (directory / 'z-force-status.json').write_text(json.dumps({'faulted': force_fault, 'bound': True, 'last_error': ''}))
                        (directory / 'z-sensor-status.json').write_text(json.dumps({'timed_provider_bound': True, 'dropped': 100}))
                        for name in ['motor-state.csv', 'z-force-query.csv', 'main-z-probe-edges.csv', 'nozzle-z-probe-edges.csv']:
                            (directory / name).write_text('Mock trace only\n')
                    return 0
            process = FakeProcess()
            def prepare(directory, stage, token):
                calls.append(stage)
                if fail_generation == stage: raise RuntimeError('Injected generation failure')
                result = real_prepare(directory, stage, token)
                if stop_during_generation: (directory / 'stop-request').write_text('Stop during generation\n')
                return result
            def intercept_open(path, mode='r', *args, **kwargs):
                if partial_write and path.name == 'console-input.commands' and mode == 'a':
                    class Failure:
                        def __enter__(self): return self
                        def __exit__(self, *args): return False
                        def write(self, value):
                            with original_open(path, 'a') as stream: stream.write(value[:17])
                            raise OSError('Injected partial append uncertainty')
                    return Failure()
                return original_open(path, mode, *args, **kwargs)
            clock = mock.Mock(side_effect=wall_ticks) if wall_ticks else mock.Mock(return_value=0)
            # Popen creates the directory in production, not the observer's preflight.
            import shutil
            shutil.rmtree(directory)
            def launch(*args, **kwargs):
                nonlocal process
                process = FakeProcess(); return process
            with mock.patch.object(m, 'ROOT', root), mock.patch.object(m.subprocess, 'Popen', side_effect=launch) as launcher, \
                 mock.patch.object(m, 'prepare_request', side_effect=prepare), mock.patch.object(m.secrets, 'token_hex', return_value=TOKEN), \
                 mock.patch.object(m.time, 'sleep'), mock.patch.object(m.time, 'monotonic', clock), \
                 mock.patch.object(pathlib.Path, 'open', intercept_open), mock.patch.object(m.os, 'killpg') as kill:
                result = m.main(['test', '--z-probe-profile', m.PROFILE, *options])
            return {'result': result, 'record': json.loads((directory / 'xyz-observation.json').read_text()),
                    'commands': (directory / 'console-input.commands').read_text(), 'calls': calls,
                    'stop': (directory / 'stop-request').exists(), 'waits': process.waits,
                    'timeline': timeline, 'env': launcher.call_args.kwargs['env'], 'kill_calls': kill.call_args_list}

    def steps(self):
        return [(0, READY), (1, capture('ready')), (2, capture('X') + rail_pair('X')),
                (3, capture('Y') + rail_pair('Y')), (4, capture('Z') + rail_pair('Z'))]

    def test_explicit_profile_required_before_launch_even_if_environment_set(self):
        for args in [['test'], ['test', '--z-probe-profile', 'none'], ['../escape', '--z-probe-profile', m.PROFILE],
                     ['test', '--z-probe-profile', m.PROFILE, '--seconds', '0']]:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), \
                 mock.patch.object(m.subprocess, 'Popen') as launch, mock.patch.dict(m.os.environ, {'Z_PROBE_PROFILE': m.PROFILE}), \
                 self.assertRaises(SystemExit): m.main(args)
            launch.assert_not_called()

    def test_exact_once_ordered_xyz_normal_stop_and_honest_scope(self):
        result = self.run_fake(self.steps())
        self.assertEqual(result['result'], 0); self.assertEqual(result['calls'], ['ready', 'X', 'Y', 'Z'])
        self.assertEqual(result['commands'].count('timeout -t 5 '), 4)
        self.assertEqual(result['record']['phase'], 'native_xyz_completion_observed')
        self.assertTrue(result['stop']); self.assertEqual(result['waits'], 1)
        for key in ('physical_causal_chain_verified', 'physical_geometry_validated', 'calibration_completed', 'print_completed'):
            self.assertFalse(result['record'][key])
        self.assertTrue(result['record']['evidence_warnings'])
        for axis in m.AXES:
            self.assertEqual(result['record']['axes'][axis]['request_count'], 1)
            self.assertTrue(result['record']['axes'][axis]['rpc_acceptance_verified'])
        self.assertNotIn('XYZ_Y_BEGIN', result['timeline'][2][1]); self.assertNotIn('XYZ_Z_BEGIN', result['timeline'][3][1])

    def test_never_advances_from_acknowledgement_or_rail_log_alone(self):
        for suffix in [capture('X'), req('X')['begin'] + '\n' + rail_pair('X')]:
            result = self.run_fake(self.steps()[:2] + [(2, suffix)])
            self.assertEqual(result['calls'], ['ready', 'X']); self.assertNotEqual(result['result'], 0)

    def test_missing_y_stops_before_z(self):
        result = self.run_fake(self.steps()[:3] + [(3, capture('Y'))])
        self.assertEqual(result['calls'], ['ready', 'X', 'Y']); self.assertNotEqual(result['result'], 0)

    def test_bad_x_transport_no_retry_or_y(self):
        result = self.run_fake(self.steps()[:2] + [(2, capture('X', status=143, transport=143) + rail_pair('X'))])
        self.assertEqual(result['calls'], ['ready', 'X']); self.assertEqual(result['record']['phase'], 'error')
        self.assertTrue(result['stop']); self.assertNotEqual(result['result'], 0)

    def test_native_z_failure_stops_and_is_not_repeated(self):
        steps = self.steps()[:4] + [(4, capture('Z') + '[1970-01-01 00:00:30.000] [error] [3] CS1237 query timeout\n')]
        result = self.run_fake(steps)
        self.assertEqual(result['calls'], ['ready', 'X', 'Y', 'Z']); self.assertTrue(result['stop'])
        self.assertEqual(result['record']['phase'], 'native_failure_z'); self.assertNotEqual(result['result'], 0)

    def test_partial_append_uncertainty_is_durable_and_not_retried(self):
        result = self.run_fake(self.steps(), partial_write=True)
        self.assertEqual(result['calls'], ['ready']); self.assertTrue(result['stop'])
        self.assertEqual(result['record']['requests'][0]['queue_outcome'], 'uncertain')
        self.assertNotEqual(result['result'], 0)

    def test_generation_failure_does_not_queue_or_retry(self):
        result = self.run_fake(self.steps(), fail_generation='Y')
        self.assertEqual(result['calls'], ['ready', 'X', 'Y'])
        self.assertNotIn('XYZ_Y_BEGIN', result['commands']); self.assertTrue(result['stop'])
        self.assertEqual(result['record']['requests'][-1]['queue_outcome'], 'not_attempted')

    def test_existing_and_mid_generation_stops_respected(self):
        result = self.run_fake(self.steps(), existing_stop=True)
        self.assertEqual(result['calls'], []); self.assertEqual(result['commands'], '')
        result = self.run_fake(self.steps(), stop_during_generation=True)
        self.assertEqual(result['calls'], ['ready']); self.assertEqual(result['commands'], '')

    def test_profile_mismatch_blocks_even_readiness_rpc(self):
        result = self.run_fake(self.steps(), bad_profile=True)
        self.assertEqual(result['calls'], []); self.assertTrue(result['stop'])

    def test_new_native_failure_during_ready_check_blocks_x(self):
        result = self.run_fake([(0, READY), (1, capture('ready') +
                               '[1970-01-01 00:00:11.000] [error] [2] MCU shutdown\n')])
        self.assertEqual(result['calls'], ['ready'])
        self.assertTrue(result['record']['native_ready_stage_failures']); self.assertTrue(result['stop'])

    def test_console_rewrite_or_clock_backwards_stops(self):
        for steps in [[(1, READY), (2, ('rewritten\n',))], [(1, READY), (0, '')], [(0, READY), (-1, '')], [(True, READY)]]:
            with self.subTest(steps=steps):
                result = self.run_fake(steps)
                self.assertEqual(result['record']['phase'], 'error'); self.assertTrue(result['stop'])

    def test_wall_and_virtual_time_limits(self):
        result = self.run_fake([(0, '')], options=['--seconds', '1'], wall_ticks=[0, 2])
        self.assertIn('wall', result['record']['error']); self.assertTrue(result['stop'])
        result = self.run_fake([(1_000_000_000, READY)], options=['--virtual-seconds', '1'])
        self.assertIn('Total virtual', result['record']['error'])
        result = self.run_fake([(0, READY), (1_000_000_000, '')], options=['--stage-virtual-seconds', '1'])
        self.assertIn('Stage virtual', result['record']['error'])
        result = self.run_fake([(0, READY), (1, '')], options=['--stage-seconds', '1'], wall_ticks=[0, 0, 0, 2])
        self.assertIn('Stage wall', result['record']['error'])

    def test_owned_cleanup_is_bounded(self):
        result = self.run_fake(self.steps(), cleanup_timeout=True)
        self.assertTrue(result['record']['cleanup_limit_exceeded']); self.assertEqual(result['waits'], 2)
        self.assertEqual(result['kill_calls'], [mock.call(987654321, m.signal.SIGTERM)])

    def test_force_fault_or_missing_exports_not_a_clean_observation(self):
        for kwargs in [{'force_fault': True}, {'missing_exports': True}]:
            with self.subTest(kwargs=kwargs):
                result = self.run_fake(self.steps(), **kwargs)
                self.assertTrue(result['record']['native_xyz_completion_observed'])
                self.assertEqual(result['result'], 3); self.assertTrue(result['record']['evidence_issues'])

    def test_inherited_z_heater_timing_overrides_not_used(self):
        with mock.patch.dict(m.os.environ, {'Z_BED_RELATIVE_MM': '999', 'NATIVE_NOZZLE_HEATER': '1', 'GLOBAL_QUANTUM_US': '10',
                                            'ICOUNT_SHIFT': '9', 'NOZZLE_TMC_MODEL': 'autobaud'}):
            result = self.run_fake(self.steps())
        env = result['env']
        self.assertNotIn('Z_BED_RELATIVE_MM', env)
        for key, value in {'NATIVE_NOZZLE_HEATER': '0', 'GLOBAL_QUANTUM_US': '1', 'ICOUNT_SHIFT': '0',
                           'NOZZLE_TMC_MODEL': 'fixed', 'Z_PROBE_PROFILE': m.PROFILE, 'ASSUMED_XY_DIAG_CABLE': '1',
                           'PASSIVE_MOTOR_TRACE': '1', 'PASSIVE_CONTACT_TRACE': '1'}.items():
            self.assertEqual(env[key], value)

    def test_explicit_autobaud_overrides_environment_and_preserves_quantum(self):
        with mock.patch.dict(m.os.environ, {'NOZZLE_TMC_MODEL': 'fixed', 'GLOBAL_QUANTUM_US': '10'}):
            result = self.run_fake(self.steps(), options=['--nozzle-tmc-model', 'autobaud'])
        self.assertEqual(result['result'], 0)
        self.assertEqual(result['env']['NOZZLE_TMC_MODEL'], 'autobaud')
        self.assertEqual(result['env']['GLOBAL_QUANTUM_US'], '1')
        self.assertEqual(result['record']['verified_tmc_selection']['selection'], 'autobaud')

    def test_wrong_tmc_manifest_prevents_all_rpc_requests(self):
        for options in [[], ['--nozzle-tmc-model', 'autobaud']]:
            requested = 'autobaud' if options else 'fixed'
            other = 'fixed' if requested == 'autobaud' else 'autobaud'
            for kwargs in [{'manifest_model': other}, {'wrong_manifest': True}]:
                with self.subTest(options=options, kwargs=kwargs):
                    result = self.run_fake(self.steps(), options=options, **kwargs)
                    self.assertEqual(result['calls'], []); self.assertTrue(result['stop'])
                    self.assertEqual(result['record']['phase'], 'error')

    def test_planned_longer_bounded_budget_is_explicit(self):
        args = m.parse_args(['test', '--z-probe-profile', m.PROFILE, '--nozzle-tmc-model', 'autobaud',
                             '--seconds', '4800', '--stage-seconds', '1800', '--virtual-seconds', '60'])
        self.assertEqual((args.seconds, args.stage_seconds, args.virtual_seconds), (4800, 1800, 60))
        defaults = m.parse_args(['test', '--z-probe-profile', m.PROFILE])
        self.assertEqual(defaults.nozzle_tmc_model, 'fixed'); self.assertEqual(defaults.seconds, 1800)


if __name__ == '__main__': unittest.main()
