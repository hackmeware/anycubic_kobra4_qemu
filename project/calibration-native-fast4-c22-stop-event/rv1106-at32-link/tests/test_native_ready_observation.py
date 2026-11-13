"""Offline helpers and mocked controller. Never starts a launcher or RPC client."""
import contextlib
import importlib.util
import io
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'rv1106-at32-link/scripts/run_native_ready_observation.py'
SPEC = importlib.util.spec_from_file_location('ready_observation', SCRIPT)
m = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(m)
TOKEN = 'ab' * 12
BEGIN, END = m.BEGIN + '_' + TOKEN, m.END + '_' + TOKEN
NATIVE = '\x1b[32m[1970-01-01 00:00:10.604] [info] [527] Printer is ready at 10.60463492.\x1b[m\r\n'
COMMANDS = ("printf '\\177' > /tmp/grpc-probe\nchmod +x /tmp/grpc-probe\n"
            'timeout -t 5 /tmp/grpc-probe > /tmp/grpc-probe.out\n'
            'GRPC_PROBE_TRANSPORT_EXIT=$?\nod -v -b /tmp/grpc-probe.out\n'
            'echo GRPC_PROBE_TRANSPORT_EXIT=$GRPC_PROBE_TRANSPORT_EXIT\necho GRPC_PROBE_DONE\n')


def frame(kind, flags, payload=b'', stream=1):
    return len(payload).to_bytes(3, 'big') + bytes([kind, flags]) + stream.to_bytes(4, 'big') + payload


def literal(name, value):
    return b'\x40' + bytes([len(name)]) + name + bytes([len(value)]) + value


def wire(state=b'ready', error=b'', status=b'0', protobuf=None):
    if protobuf is None:
        protobuf = (b'\x0a' + bytes([len(error)]) + error if error else b'') + b'\x12' + bytes([len(state)]) + state
    message = b'\0' + len(protobuf).to_bytes(4, 'big') + protobuf
    return frame(1, 4, b'\x88') + frame(0, 0, message) + frame(1, 5, literal(b'grpc-status', status))


def od(data):
    return '\n'.join(f'{i:07o}  ' + ' '.join(f'{value:03o}' for value in data[i:i + 16])
                     for i in range(0, len(data), 16)) + f'\n{len(data):07o}\n'


def capture(data=None, status=0, transport=0, begin=m.BEGIN, end=m.END):
    return (begin + '\n' + f'READY_CLIENT_STATUS={status}\n' + m.RAW_BEGIN + '\n' +
            od(wire() if data is None else data) + m.RAW_END + '\n' +
            f'GRPC_PROBE_TRANSPORT_EXIT={transport}\nGRPC_PROBE_DONE\n' + end + '\n')


def live_capture(**kwargs):
    return capture(begin=BEGIN, end=END, **kwargs)


class HelperTests(unittest.TestCase):
    def test_instrument_preserves_status_and_one_invocation(self):
        output = m.instrument(COMMANDS)
        self.assertEqual(output.count('timeout -t '), 1)
        self.assertIn('timeout -t 5 /tmp/grpc-probe > /tmp/grpc-probe.out\n'
                      'GRPC_PROBE_TRANSPORT_EXIT=$?\nREADY_CLIENT_STATUS=$GRPC_PROBE_TRANSPORT_EXIT\n', output)
        self.assertEqual(output.count('$?'), 1)
        self.assertIn('echo READY_RAW_BEGIN\nod -v -b /tmp/grpc-probe.out\necho READY_RAW_END\n', output)

    def test_instruments_actual_candidate_without_running_generated_elf(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / 'probe'
            result = subprocess.run([m.sys.executable, str(ROOT / 'rv1106-at32-link/experimental/stream-end-probe/make_probe.py'),
                                     '--response-mode', 'stream-end', '--method', 'PrinterState', '--timeout-seconds', '5',
                                     '--output', str(output)], capture_output=True, check=True)
            commands = m.instrument(output.with_suffix('.commands').read_text())
            self.assertEqual(commands.count('timeout -t '), 1)
            self.assertEqual(commands.count('$?'), 1)
            self.assertIn(b'/applink.AppLinkService/PrinterState', output.read_bytes())

    def test_instrument_rejects_extra_or_changed_commands(self):
        cases = [COMMANDS + 'timeout -t 5 /tmp/grpc-probe\n', COMMANDS + '/tmp/grpc-probe\n',
                 COMMANDS.replace('timeout -t 5', 'timeout -t 0'),
                 COMMANDS.replace('GRPC_PROBE_TRANSPORT_EXIT=$?\n', ''),
                 COMMANDS.replace('GRPC_PROBE_TRANSPORT_EXIT=$?\n', 'echo bad\nGRPC_PROBE_TRANSPORT_EXIT=$?\n'),
                 COMMANDS.replace('chmod +x', 'chmod 777'), COMMANDS.replace("printf '\\177'", "echo malicious"),
                 COMMANDS.replace('timeout -t 5', 'echo timeout -t 5')]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError): m.instrument(value)

    def test_native_ready_requires_complete_original_logger_line(self):
        self.assertTrue(m.native_ready(NATIVE))
        for value in [NATIVE.rstrip('\r\n'), 'Printer is ready at 10.4.\n',
                      'echo Printer is ready at 10.4.\n', 'prefix ' + NATIVE,
                      NATIVE.replace('[info]', '[error]'), NATIVE.replace('ready at', 'not ready at')]:
            with self.subTest(value=value): self.assertFalse(m.native_ready(value))

    def test_complete_response(self):
        self.assertEqual(m.verify(capture())['api_response']['state'], 'ready')
        self.assertFalse(m.verify(capture())['physical_completion_proven'])
        self.assertEqual(m.verify(capture().replace('\n', '\r\n'))['client_exit_status'], 0)

    def test_known_native_wire_fixture(self):
        data = bytes.fromhex((ROOT / 'rv1106-at32-link/tests/fixtures/native-ready-response.hex').read_text())
        self.assertEqual(m.verify(capture(data))['api_response'], {'state': 'ready', 'state_message': 'Printer is ready'})

    def test_partial_and_echo_markers_do_not_verify(self):
        full = capture()
        for value in ['', 'echo ' + m.BEGIN + '\necho ' + m.END + '\n', full[:full.index(m.END)], full[:-1]]:
            with self.subTest(value=value): self.assertIsNone(m.verify(value))
        self.assertIsNone(m.verify(full, BEGIN, END))
        self.assertIsNone(m.verify(m.BEGIN[:-1]))

    def test_ambiguous_stale_and_reversed_markers_rejected(self):
        full = capture()
        for value in [m.END + '\n', m.END + '\n' + full, full + full, m.BEGIN + '\n' + full,
                      full.replace(m.RAW_END + '\n', ''), full.replace(m.RAW_BEGIN + '\n', m.RAW_BEGIN + '\n' + m.RAW_BEGIN + '\n')]:
            with self.subTest(value=value), self.assertRaises(ValueError): m.verify(value)

    def test_exit_codes_and_complete_markers_required(self):
        for status, transport in [(5, 5), (0, 5), (5, 0), (143, 143), (2, 2)]:
            with self.subTest(status=status, transport=transport), self.assertRaises(ValueError):
                m.verify(capture(status=status, transport=transport))
        for value in [capture().replace('READY_CLIENT_STATUS=0\n', ''),
                      capture().replace('READY_CLIENT_STATUS=0\n', 'echo READY_CLIENT_STATUS=0\n'),
                      capture().replace('READY_CLIENT_STATUS=0\n', 'READY_CLIENT_STATUS=0\nREADY_CLIENT_STATUS=0\n'),
                      capture().replace('GRPC_PROBE_DONE\n', ''), capture().replace('GRPC_PROBE_TRANSPORT_EXIT=0\n', '')]:
            with self.subTest(value=value), self.assertRaises(ValueError): m.verify(value)

    def test_raw_dump_offsets_and_final_count(self):
        text = od(wire())
        self.assertEqual(m.read_od(text), wire())
        for value in [text.replace('0000020', '0000030'), text + text,
                      text[:text.rfind('\n', 0, len(text) - 1)] + '\n', text.replace('0000000', '0000001', 1),
                      text.replace('0000000', '0000000 999', 1), text + '*\n', text.replace('0000000', '0000000 777', 1)]:
            with self.subTest(value=value), self.assertRaises(ValueError): m.read_od(value)

    def test_complete_frames_envelope_status_and_ready_required(self):
        valid = wire()
        cases = [valid + bytes(n) for n in range(1, 10)] + [valid[:-n] for n in (1, 5, 9)]
        cases += [wire(state=b'shutdown'), wire(error=b'error'), wire(status=b'1'), wire(status=b'00'),
                  wire(protobuf=b'\x12\x05ready\x12\x05ready'), wire(protobuf=b'\0\0'),
                  frame(1, 4, b'\x88') + frame(0, 0, b'\0\0\0\0\x01') + frame(1, 5, literal(b'grpc-status', b'0')),
                  frame(1, 4, b'\x88') + frame(3, 0, bytes(4)),
                  frame(1, 4, b'\x88') + frame(1, 5, literal(b'grpc-status', b'0')),
                  valid.replace(b'\x88', b'\x8c', 1),
                  valid.replace(literal(b'grpc-status', b'0'), b'grpc-status\x010'),
                  valid.replace(literal(b'grpc-status', b'0'), literal(b'grpc-message', b'grpc-status\x010'))]
        for data in cases:
            with self.subTest(data=data), self.assertRaises((ValueError, UnicodeError)): m.verify(capture(data))

    def test_fragmented_data_and_header_continuation(self):
        protobuf = b'\x12\x05ready'; message = b'\0' + len(protobuf).to_bytes(4, 'big') + protobuf
        trailers = literal(b'grpc-status', b'0')
        data = (frame(1, 4, b'\x88') + frame(0, 0, message[:2]) + frame(0, 0, message[2:]) +
                frame(1, 1, trailers[:4]) + frame(9, 0, trailers[4:7]) + frame(9, 4, trailers[7:]))
        self.assertEqual(m.verify(capture(data))['api_response']['state'], 'ready')
        for broken in [data[:-1], data + frame(6, 0, bytes(8), 0),
                       data.replace(frame(9, 0, trailers[4:7]), frame(9, 0, trailers[4:7], 3))]:
            with self.subTest(broken=broken), self.assertRaises(ValueError): m.verify(capture(broken))

    def test_duplicate_status_and_unsupported_hpack_fail_closed(self):
        base = frame(1, 4, b'\x88') + frame(0, 0, b'\0\0\0\0\x07\x12\x05ready')
        for block in [literal(b'grpc-status', b'0') * 2, literal(b'grpc-status', b'0') + literal(b'grpc-status', b'1'),
                      b'\xbe', b'\x40\x8bgrpc-status\x010', literal(b':status', b'200') + literal(b'grpc-status', b'0')]:
            with self.subTest(block=block), self.assertRaises(ValueError): m.verify(capture(base + frame(1, 5, block)))


class ControllerTests(unittest.TestCase):
    def run_fake(self, steps, *, generator_error=False, bad_commands=False, write_failure=False,
                 returncode=0, existing_stop=False, stop_during_generation=False, environment=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary); directory = root / 'runs' / 'test'
            calls, launched, timeline = [], [], []
            original_open = pathlib.Path.open

            class FakeProcess:
                def __init__(self):
                    directory.mkdir(parents=True); (directory / 'console-input.commands').write_text('')
                    self.index, self.text, self.waits = 0, '', 0
                    if existing_stop: (directory / 'stop-request').write_text('Existing authorized stop\n')

                def poll(self):
                    if self.index >= len(steps): return returncode
                    now, addition = steps[self.index]; self.index += 1
                    if isinstance(addition, tuple): self.text = addition[0]
                    else: self.text += addition
                    (directory / 'console.bin').write_text(self.text)
                    (directory / 'virtual-time.json').write_text(json.dumps({'virtual_time_ns': now}))
                    timeline.append((now, (directory / 'console-input.commands').read_text()))
                    return None

                def wait(self):
                    self.waits += 1
                    # This is only a mock final-export witness, not runtime evidence.
                    (directory / 'mock-final-export').write_text('normal launcher cleanup reached')
                    return returncode

            process = None

            def launch(args, **kwargs):
                nonlocal process
                launched.append((args, kwargs)); process = FakeProcess(); return process

            def generate(args, **kwargs):
                calls.append(args)
                if stop_during_generation: (directory / 'stop-request').write_text('Stop arrived during preparation\n')
                if generator_error: raise subprocess.CalledProcessError(1, args)
                output = pathlib.Path(args[args.index('--output') + 1])
                output.with_suffix('.commands').write_text('echo invalid\n' if bad_commands else COMMANDS)

            def intercept_open(path, mode='r', *args, **kwargs):
                if write_failure and path.name == 'console-input.commands' and mode == 'a':
                    class PartialFailure:
                        def __enter__(self): return self
                        def __exit__(self, *args): return False
                        def write(self, text):
                            with original_open(path, 'a') as stream: stream.write(text[:17])
                            raise OSError('injected uncertain partial append')
                    return PartialFailure()
                return original_open(path, mode, *args, **kwargs)

            with mock.patch.object(m, 'ROOT', root), mock.patch.object(m.secrets, 'token_hex', return_value=TOKEN), \
                 mock.patch.object(m.subprocess, 'Popen', side_effect=launch), mock.patch.object(m.subprocess, 'run', side_effect=generate), \
                 mock.patch.object(m.time, 'sleep'), mock.patch.object(pathlib.Path, 'open', intercept_open), \
                 mock.patch.dict(m.os.environ, environment or {}, clear=False):
                result = m.main(['test', '--seconds', '50'])
            return {'result': result, 'record': json.loads((directory / 'ready-observation.json').read_text()),
                    'commands': (directory / 'console-input.commands').read_text(), 'calls': calls,
                    'stop': (directory / 'stop-request').read_text() if (directory / 'stop-request').exists() else None,
                    'export': (directory / 'mock-final-export').exists(), 'waits': process.waits,
                    'launched': launched, 'timeline': timeline}

    def test_exactly_one_read_only_request_and_normal_stop_export(self):
        result = self.run_fake([(0, NATIVE), (1, live_capture()), (2, NATIVE + live_capture())],
                               environment={'NOZZLE_TMC_MODEL': 'autobaud', 'GLOBAL_QUANTUM_US': '1', 'NATIVE_NOZZLE_HEATER': '1'})
        self.assertEqual(result['result'], 0); self.assertEqual(result['record']['phase'], 'verified_ready')
        self.assertEqual(result['record']['request_count'], 1); self.assertEqual(len(result['calls']), 1)
        args = result['calls'][0]
        self.assertEqual(args[args.index('--method') + 1], 'PrinterState')
        self.assertEqual(args[args.index('--response-mode') + 1], 'stream-end')
        self.assertEqual(args[args.index('--timeout-seconds') + 1], '5')
        self.assertNotIn('--homing-axis', args); self.assertNotIn('--temperature-c', args)
        self.assertEqual(result['commands'].count('timeout -t '), 1)
        for forbidden in ['Homing', 'StartPrint', 'ExtruderPreheating', 'RunGcodeScript', 'G28', 'M104', 'M140']:
            self.assertNotIn(forbidden, result['commands'])
        self.assertIn('verified; final export', result['stop'])
        self.assertTrue(result['export']); self.assertEqual(result['waits'], 1)
        self.assertTrue(result['record']['final_export_requested'])
        env = result['launched'][0][1]['env']
        self.assertEqual(env['NATIVE_NOZZLE_HEATER'], '0')
        self.assertEqual(env['NOZZLE_TMC_MODEL'], 'autobaud'); self.assertEqual(env['GLOBAL_QUANTUM_US'], '1')

    def test_polling_is_read_only_throttled_and_does_not_queue_without_ready(self):
        result = self.run_fake([(0, 'COUPLED_STARTUP_COMMANDS_DONE\n'), (500_000_000, ''), (1_000_000_000, '')])
        self.assertEqual(result['calls'], []); self.assertEqual(result['record']['request_count'], 0)
        self.assertEqual(result['commands'].count('tail -100 /data/main.stdout'), 2)
        self.assertEqual(result['commands'].count('tail -100 /data/logs/avata_main.log'), 2)
        self.assertEqual(result['result'], 2); self.assertIsNone(result['stop']); self.assertTrue(result['export'])

    def test_stale_fixed_markers_and_prequeue_complete_capture_do_not_pass(self):
        result = self.run_fake([(0, live_capture() + NATIVE), (1, capture()), (2, '')])
        self.assertEqual(result['result'], 2); self.assertEqual(result['record']['phase'], 'probe_queued')
        self.assertEqual(result['record']['request_count'], 1); self.assertEqual(len(result['calls']), 1)
        result = self.run_fake([(0, NATIVE), (1, capture()), (2, live_capture())])
        self.assertEqual(result['result'], 0)

    def test_partial_end_marker_waits_without_retry(self):
        response = live_capture()
        result = self.run_fake([(0, NATIVE), (1, response[:-1]), (2, '\n')])
        self.assertEqual(result['result'], 0); self.assertEqual(len(result['calls']), 1)
        self.assertNotIn('result', self.run_fake([(0, NATIVE), (1, response[:-1])])['record'])

    def test_response_errors_stop_and_export_without_retry(self):
        for bad in [live_capture(status=5, transport=5), live_capture(data=wire(status=b'1')),
                    live_capture(data=wire() + b'\0'), live_capture(data=wire(state=b'error')),
                    live_capture() + live_capture()]:
            with self.subTest(bad=bad):
                result = self.run_fake([(0, NATIVE), (1, bad), (2, live_capture())])
                self.assertEqual(result['result'], 2); self.assertEqual(result['record']['phase'], 'error')
                self.assertEqual(len(result['calls']), 1); self.assertIn('no retry', result['stop']); self.assertTrue(result['export'])

    def test_generation_or_instrument_error_never_queues(self):
        for options in [{'generator_error': True}, {'bad_commands': True}]:
            with self.subTest(options=options):
                result = self.run_fake([(0, NATIVE), (1, NATIVE)], **options)
                self.assertEqual(result['result'], 2); self.assertEqual(len(result['calls']), 1)
                self.assertEqual(result['record']['request_count'], 0); self.assertEqual(result['commands'], '')
                self.assertIn('no retry', result['stop']); self.assertEqual(result['waits'], 1)

    def test_uncertain_partial_queue_failure_is_not_retried(self):
        result = self.run_fake([(0, NATIVE), (1, NATIVE)], write_failure=True)
        self.assertEqual(result['result'], 2); self.assertEqual(result['record']['request_count'], 1)
        self.assertEqual(result['record']['queue_outcome'], 'uncertain'); self.assertEqual(len(result['calls']), 1)
        self.assertIn('partial append', result['record']['error']); self.assertIn('no retry', result['stop'])
        self.assertEqual(result['waits'], 1)

    def test_existing_stop_is_respected_and_preserved(self):
        result = self.run_fake([(0, NATIVE)], existing_stop=True)
        self.assertEqual(result['result'], 2); self.assertEqual(result['calls'], [])
        self.assertEqual(result['stop'], 'Existing authorized stop\n'); self.assertEqual(result['record']['phase'], 'stop_requested')
        self.assertEqual(result['waits'], 1)

    def test_stop_during_generation_prevents_queueing(self):
        result = self.run_fake([(0, NATIVE)], stop_during_generation=True)
        self.assertEqual(result['result'], 2); self.assertEqual(result['record']['request_count'], 0)
        self.assertEqual(result['commands'], ''); self.assertEqual(result['record']['phase'], 'stop_requested')
        self.assertEqual(result['stop'], 'Stop arrived during preparation\n'); self.assertEqual(result['waits'], 1)

    def test_console_rewrite_or_invalid_clock_stops_without_more_requests(self):
        for steps in [[(0, NATIVE), (1, ('rewritten console\n',))], [(0, NATIVE), (-1, '')], [(0, NATIVE), (True, '')]]:
            with self.subTest(steps=steps):
                result = self.run_fake(steps)
                self.assertEqual(result['record']['phase'], 'error'); self.assertEqual(len(result['calls']), 1)
                self.assertIn('no retry', result['stop'])

    def test_launcher_failure_not_reported_as_success(self):
        result = self.run_fake([(0, NATIVE), (1, live_capture())], returncode=9)
        self.assertEqual(result['result'], 9); self.assertEqual(result['record']['launcher_exit_code'], 9)
        self.assertEqual(result['record']['phase'], 'verified_ready'); self.assertEqual(result['waits'], 1)

    def test_invalid_arguments_and_existing_directory_never_launch(self):
        for arguments in [['../bad'], ['test', '--seconds', '0'], ['test', '--seconds', '-1'], ['test', '--seconds', '86401']]:
            with self.subTest(arguments=arguments), mock.patch.object(m.subprocess, 'Popen') as launch, \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit): m.main(arguments)
            launch.assert_not_called()
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary); (root / 'runs' / 'exists').mkdir(parents=True)
            with mock.patch.object(m, 'ROOT', root), mock.patch.object(m.subprocess, 'Popen') as launch, self.assertRaises(SystemExit):
                m.main(['exists'])
            launch.assert_not_called()

    def test_launcher_creation_failure_no_retry(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(m, 'ROOT', pathlib.Path(temporary)), \
             mock.patch.object(m.subprocess, 'Popen', side_effect=OSError('offline launch failure')) as launch, \
             mock.patch.object(m.subprocess, 'run') as generate:
            self.assertEqual(m.main(['test']), 2)
            self.assertEqual(launch.call_count, 1); generate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
