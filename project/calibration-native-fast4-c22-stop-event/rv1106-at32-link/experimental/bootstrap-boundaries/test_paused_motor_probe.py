"""Offline fixture/mocked-monitor tests. No Renode, QEMU or firmware is launched."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

c = load('probe_compare', HERE/'compare.py')
p = load('probe_validation', HERE/'paused_motor_probe.py')
a = load('probe_aggregate', HERE/'aggregate.py')


def json_write(path, value):
    path.write_text(json.dumps(value))


def observation_fixture(out):
    for board in p.BOARDS:
        for index, phase in enumerate(p.PHASES):
            json_write(out/f'probe-{phase}-{board}.json', {
                'schema': 1, 'source': p.SOURCE, 'board': board, 'phase': phase,
                'phase_index': index, 'paused_before': True, 'paused_after': True,
                'local_time_before_ns': 20000000, 'local_time_after_ns': 20000000})
    for name in p.EXPECTED_CAPTURES:
        (out/name).write_bytes(b'\xa5'*p.DUMP_SIZE if name.endswith('-sram.bin') else b'')
    for suffix in ('anchor', 'a', 'b'):
        (out/f'motor-probe-{suffix}.bin').write_bytes((out/'motor-sram.bin').read_bytes())


def guarded_fixture(out):
    observation_fixture(out)
    ack = {'schema': 1, 'source': 'renode-shared-mcu-step', 'enabled': True,
           'paused': True, 'time_went_backwards': False, 'epoch': 'offline-fixture',
           'virtual_time_ns': 20000000, 'step_id': 0}
    json_write(out/'renode-step.json', ack)
    json_write(out/'acknowledgments.json', {'actual_times_ns': [20000000], 'final_ack': ack})
    record = {'passed': True, 'clean_exit': True, 'exit_code': 0, 'process_group_absent': True,
              'watchdog_stopped': True, 'forced_signals': [], 'forced_termination': False,
              'vendor_firmware_ran': True, 'kind': 'native-prefix', 'mode': 'legacy',
              'compared_duration_ns': 20000000, 'global_quantum_ns': 1000,
              'paused_motor_probe_enabled': True, 'equivalence_established': False,
              'full_native_one_second_proven': False, 'acknowledged_time_ns': 20000000,
              'captures_sha256': {name: hashlib.sha256((out/name).read_bytes()).hexdigest()
                                 for name in p.EXPECTED_CAPTURES},
              'paused_motor_probe': p.validate_probe(out)}
    json_write(out/'result.json', record)
    guard = {'schema': 1, 'passed': True, 'status': 'finished', 'failure': None,
             'comparator_exit_code': 0, 'whole_groups_absent': True,
             'all_descendants_absent': True, 'signals': [], 'surviving_processes': [],
             'surviving_group_members': [], 'wall_budget_s': 45,
             'command': ['python3', str(HERE/'compare.py'), '--kind', 'native-prefix',
                         '--mode', 'legacy', '--wall-seconds', '42', '--paused-motor-probe',
                         '--output', str(out)]}
    json_write(out/'outer.json', guard)
    return record, guard


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=HERE)
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)

    def mutate_fence(self, changes, board='motor', phase='between-a-b'):
        path = self.out/f'probe-{phase}-{board}.json'
        row = json.loads(path.read_text())
        row.update(changes)
        json_write(path, row)

    def test_flag_validation_before_launch(self):
        for kind, mode in [('synthetic', None), ('synthetic', 'legacy'), ('native-prefix', 'segmented')]:
            argv = ['compare.py', '--kind', kind, '--output', str(self.out/'unused'),
                    '--wall-seconds', '42', '--paused-motor-probe']
            if mode:
                argv += ['--mode', mode]
            with self.subTest(kind=kind, mode=mode), patch.object(sys, 'argv', argv), \
                    patch.object(c, 'run_arm') as run, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    c.main()
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()
        with patch.object(c.subprocess, 'Popen', side_effect=AssertionError('Forbidden runtime launch')):
            with self.assertRaises(ValueError):
                c.run_arm('native-prefix', 'segmented', self.out/'unused', 0, paused_motor_probe=True)
        self.assertFalse((self.out/'unused').exists())

    def test_valid_flag_forwarded_and_default_unchanged(self):
        for enabled in (False, True):
            argv = ['compare.py', '--kind', 'native-prefix', '--mode', 'legacy',
                    '--wall-seconds', '42', '--output', str(self.out/'unused')]
            if enabled:
                argv += ['--paused-motor-probe']
            with patch.object(sys, 'argv', argv), patch.object(c, 'run_arm', return_value={'passed': True}) as run:
                self.assertEqual(c.main(), 0)
                self.assertEqual(run.call_args.kwargs, {'paused_motor_probe': True} if enabled else {})

    def test_exact_command_plan(self):
        expected = ['mach set "motor"',
                    f'dump_file 0x20000000 0x18000 @{self.out}/motor-probe-anchor.bin',
                    'cpu PC', 'cpu SP', f'include @{HERE}/PausedMotorProbe.cs']
        for board in ('main', 'nozzle', 'motor'):
            expected += [f'mach set "{board}"', 'machine LoadPlatformDescriptionFromString "pausedMotorProbe: BootstrapExperiment.PausedMotorProbe @ sysbus"']
        def fences(phase):
            return [line for board in ('main', 'nozzle', 'motor') for line in (
                f'mach set "{board}"', f'sysbus.pausedMotorProbe Export "{self.out}/probe-{phase}-{board}.json" "{board}" "{phase}"')]
        expected += fences('before-a')
        expected += ['mach set "motor"', f'dump_file 0x20000000 0x18000 @{self.out}/motor-probe-a.bin', 'cpu PC', 'cpu SP']
        expected += fences('between-a-b')
        expected += ['mach set "motor"', f'dump_file 0x20000000 0x18000 @{self.out}/motor-probe-b.bin', 'cpu PC', 'cpu SP']
        expected += fences('after-b') + fences('before-existing')
        self.assertEqual(p.before_capture_commands(self.out), expected)
        self.assertEqual(p.after_capture_commands(self.out), fences('after-existing'))
        with self.assertRaises(ValueError):
            p.fence_commands(self.out, 'skip')

    def test_helper_has_only_verified_machine_reads(self):
        import re
        source = (HERE/'PausedMotorProbe.cs').read_text()
        self.assertEqual(re.findall(r'machine\.[\w.]+', source), [
            'machine.IsPaused', 'machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds',
            'machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds', 'machine.IsPaused'])
        for forbidden in ('LimitTimer', 'ClockSource', 'SyncTime', 'AddHook', 'ReadDoubleWord',
                          'WriteDoubleWord', 'MIPS', 'RunFor', 'SystemFrequency', 'APB1Frequency',
                          'Newtonsoft', 'System.Text.Json'):
            self.assertNotIn(forbidden, source)
        self.assertIn('public void Reset() { }', source)
        self.assertIn('File.Move(temporary,target)', source)
        self.assertIn('phase!=phases[nextPhase]', source)
        self.assertIn('boardName!=null && boardName!=board', source)
        self.assertLess(source.index('File.Move(temporary,target)'), source.index('nextPhase++;'))

    def test_complete_stable_evidence_not_equivalence(self):
        observation_fixture(self.out)
        result = p.validate_probe(self.out)
        self.assertTrue(result['observations_passed'])
        self.assertTrue(result['diagnostic_evidence_complete'])
        self.assertTrue(result['within_pause_stable'])
        self.assertTrue(result['equal_board_endpoints'])
        self.assertFalse(result['equivalence_established'])
        self.assertEqual(len(result['fences_sha256']), 15)
        self.assertEqual(len(result['motor_dumps_sha256']), 4)
        self.assertTrue(result['motor_sram_preserved_across_helper_installation'])
        self.assertTrue(all(value.startswith('unavailable:') for value in result['unavailable_fields'].values()))

    def test_missing_malformed_duplicate_or_wrong_fences_rejected(self):
        observation_fixture(self.out)
        target = self.out/'probe-before-a-motor.json'
        original = target.read_text()
        for broken in ('{', '[]', '{}', original.replace('"schema": 1', '"schema": 1, "schema": 1')):
            with self.subTest(broken=broken):
                target.write_text(broken)
                with self.assertRaises((ValueError, TypeError)):
                    p.validate_probe(self.out)
        target.unlink()
        with self.assertRaises(FileNotFoundError):
            p.validate_probe(self.out)
        for change in ({'schema': True}, {'board': 'nozzle'}, {'phase': 'after-b'}, {'phase_index': True},
                       {'paused_before': 1}, {'paused_after': 'true'},
                       {'local_time_before_ns': '20000000'}, {'local_time_before_ns': True},
                       {'local_time_after_ns': -1}, {'local_time_before_ns': 2**64}):
            target.write_text(original)
            self.mutate_fence(change, phase='before-a')
            with self.subTest(change=change), self.assertRaises(ValueError):
                p.validate_probe(self.out)

    def test_running_or_changing_time_fails_with_complete_evidence(self):
        for changes in ({'paused_before': False}, {'paused_after': False},
                        {'local_time_after_ns': 20000001},
                        {'local_time_before_ns': 20000001, 'local_time_after_ns': 20000001}):
            observation_fixture(self.out)
            self.mutate_fence(changes)
            result = p.validate_probe(self.out)
            self.assertFalse(result['observations_passed'])
            self.assertTrue(result['diagnostic_evidence_complete'])
            self.assertFalse(result['within_pause_stable'])
            self.assertTrue(result['instability'])

    def test_stable_secondary_offset_reported_not_assumed_20ms(self):
        observation_fixture(self.out)
        for phase in p.PHASES:
            self.mutate_fence({'local_time_before_ns': 19999999, 'local_time_after_ns': 19999999}, phase=phase)
        result = p.validate_probe(self.out)
        self.assertTrue(result['observations_passed'])
        self.assertTrue(result['within_pause_stable'])
        self.assertFalse(result['equal_board_endpoints'])
        self.assertFalse(result['all_local_times_equal_20ms_ack'])
        self.assertEqual(result['local_times_ns']['motor'], 19999999)
        self.assertFalse(result['board_matches_20ms_ack']['motor'])

    def test_main_time_must_preserve_original_ack(self):
        observation_fixture(self.out)
        for phase in p.PHASES:
            self.mutate_fence({'local_time_before_ns': 20000001, 'local_time_after_ns': 20000001}, board='main', phase=phase)
        result = p.validate_probe(self.out)
        self.assertFalse(result['observations_passed'])
        self.assertTrue(result['within_pause_stable'])
        self.assertFalse(result['original_main_ack_preserved'])

    def test_mismatch_or_truncated_dumps_rejected(self):
        for name in ('motor-probe-a.bin', 'motor-probe-b.bin', 'motor-sram.bin'):
            observation_fixture(self.out)
            (self.out/name).write_bytes(b'\x01'*p.DUMP_SIZE)
            result = p.validate_probe(self.out)
            self.assertFalse(result['observations_passed'])
            self.assertTrue(result['diagnostic_evidence_complete'])
            self.assertFalse(result['within_pause_stable'])
            (self.out/name).write_bytes(b'\x01')
            with self.assertRaises(ValueError):
                p.validate_probe(self.out)

    def test_pre_install_anchor_must_match_but_has_no_extra_fence_claim(self):
        observation_fixture(self.out)
        (self.out/'motor-probe-anchor.bin').write_bytes(b'\x01'*p.DUMP_SIZE)
        result = p.validate_probe(self.out)
        self.assertFalse(result['observations_passed'])
        self.assertTrue(result['diagnostic_evidence_complete'])
        self.assertTrue(result['within_pause_stable'])
        self.assertFalse(result['motor_sram_preserved_across_helper_installation'])
        self.assertEqual(result['pre_install_per_board_time_and_full_registers'], 'unavailable')
        (self.out/'motor-probe-anchor.bin').write_bytes(b'')
        with self.assertRaises(ValueError):
            p.validate_probe(self.out)
        (self.out/'motor-probe-anchor.bin').unlink()
        with self.assertRaises(FileNotFoundError):
            p.validate_probe(self.out)

    def test_final_verifier_needs_both_clean_guards(self):
        record, guard = guarded_fixture(self.out)
        self.assertTrue(p.verify_guarded(self.out, self.out/'outer.json')['diagnostic_passed'])
        for key, bad in (('exit_code', 1), ('process_group_absent', False), ('clean_exit', False),
                         ('watchdog_stopped', False), ('forced_termination', True), ('forced_signals', [{}])):
            changed = dict(record, **{key: bad})
            json_write(self.out/'result.json', changed)
            with self.subTest(inner=key), self.assertRaises(ValueError):
                p.verify_guarded(self.out, self.out/'outer.json')
        json_write(self.out/'result.json', record)
        for key, bad in (('comparator_exit_code', 1), ('whole_groups_absent', False),
                         ('all_descendants_absent', False), ('signals', [{}]), ('failure', 'timeout'),
                         ('surviving_processes', [{}]), ('surviving_group_members', [{}]), ('wall_budget_s', 46)):
            json_write(self.out/'outer.json', dict(guard, **{key: bad}))
            with self.subTest(outer=key), self.assertRaises(ValueError):
                p.verify_guarded(self.out, self.out/'outer.json')

    def test_guard_bound_to_exact_arm_flag_and_budget(self):
        record, guard = guarded_fixture(self.out)
        for index, bad in ((1, '/wrong/compare.py'), (3, 'synthetic'), (5, 'segmented'),
                           (7, '43'), (8, '--other-flag'), (10, str(self.out/'other'))):
            changed = copy.deepcopy(guard)
            changed['command'][index] = bad
            json_write(self.out/'outer.json', changed)
            with self.subTest(index=index), self.assertRaises(ValueError):
                p.verify_guarded(self.out, self.out/'outer.json')

    def test_python_no_bytecode_flag_is_explicitly_allowed(self):
        record, guard = guarded_fixture(self.out)
        guard['command'].insert(1, '-B')
        json_write(self.out/'outer.json', guard)
        self.assertTrue(p.verify_guarded(self.out, self.out/'outer.json')['diagnostic_passed'])
        guard['command'].insert(2, '-u')
        json_write(self.out/'outer.json', guard)
        with self.assertRaises(ValueError):
            p.verify_guarded(self.out, self.out/'outer.json')

    def test_final_verifier_detects_changed_capture_fence_or_ack(self):
        record, guard = guarded_fixture(self.out)
        (self.out/'motor-tx.bin').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            p.verify_guarded(self.out, self.out/'outer.json')
        guarded_fixture(self.out)
        for phase in p.PHASES:
            self.mutate_fence({'local_time_before_ns': 19999999, 'local_time_after_ns': 19999999}, phase=phase)
        with self.assertRaises(ValueError):
            p.verify_guarded(self.out, self.out/'outer.json')
        guarded_fixture(self.out)
        (self.out/'renode-step.json').write_text('{}')
        with self.assertRaises(ValueError):
            p.verify_guarded(self.out, self.out/'outer.json')

    def test_aggregate_rejects_diagnostic_as_equivalence_baseline(self):
        paths = []
        for i in range(3):
            path = self.out/str(i)
            path.mkdir()
            json_write(path/'result.json', {'paused_motor_probe_enabled': True})
            paths.append(path)
        with self.assertRaisesRegex(ValueError, 'not equivalence baselines'):
            a.compare(paths)

    def mocked_arm(self, module, enabled=False, ack_ns=20000000, kind='native-prefix', mode='legacy'):
        out = self.out/'arm'
        events, sent = [], []
        class Process:
            returncode = 0
            stdin = None
            def wait(self, **kwargs):
                events.append('wait')
            def poll(self): return 0
        class Guard:
            def __init__(self, process, deadline, record):
                self.forced = threading.Event()
                self.record = record
            def group_exists(self): return False
            def close(self):
                events.append('guard-close')
                self.record.update(watchdog_stopped=True, process_group_absent=True,
                                   forced_signals=[], forced_termination=False)
        class Stepper:
            def __init__(self, *args, **kwargs):
                events.append('ack-validated')
                self.time_ns = ack_ns
                json_write(out/'renode-step.json', {'fixture': True})
            def step(self, amount):
                self.time_ns += amount
                return self.time_ns
        def fake_popen(*args, **kwargs):
            events.append('launch-mocked')
            script = (out/'experiment.resc').read_text()
            self.assertNotIn('PausedMotorProbe', script)
            return Process()
        def fake_send(process, data, deadline):
            self.assertEqual(events[-1], 'ack-validated')
            self.assertEqual(json.loads((out/'result.json').read_text())['acknowledged_time_ns'], ack_ns)
            sent.append(data.decode())
            observation_fixture(out)
            json_write(out/'nozzle-thermal-status.json', {'dropped_rows': 0, 'stream_dropped_rows': 0, 'stream_error_count': 0})
        with patch.object(module, 'HERE', HERE), patch.object(module, 'setup', return_value=(['existing setup'], list(p.BOARDS))), \
                patch.object(module.subprocess, 'Popen', fake_popen), patch.object(module, 'ProcessGuard', Guard), \
                patch.object(module, 'RenodeStepper', Stepper), patch.object(module, 'bounded_send', fake_send):
            kwargs = {'paused_motor_probe': True} if enabled else {}
            record = module.run_arm(kind, mode, out, module.time.monotonic()+10, **kwargs)
        return record, sent, events

    def test_actual_post_ack_order_and_original_captures_preserved(self):
        record, sent, events = self.mocked_arm(c, enabled=True)
        self.assertTrue(record['passed'], record.get('error'))
        self.assertEqual(set(record['captures_sha256']), p.EXPECTED_CAPTURES)
        commands = sent[0].splitlines()
        prefix = p.before_capture_commands(self.out/'arm')
        suffix = p.after_capture_commands(self.out/'arm')
        self.assertEqual(commands[:len(prefix)], prefix)
        self.assertEqual(commands[-len(suffix)-1:-1], suffix)
        self.assertEqual(commands[-1], 'quit')
        self.assertLess(events.index('ack-validated'), events.index('wait'))
        self.assertTrue(record['paused_motor_probe']['observations_passed'])
        self.assertFalse(record['equivalence_established'])

    def test_bad_original_ack_never_loads_probe(self):
        record, sent, events = self.mocked_arm(c, enabled=True, ack_ns=19999999)
        self.assertFalse(record['passed'])
        self.assertEqual(sent, [])
        self.assertIsNone(record['paused_motor_probe'])

    def test_default_monitor_and_record_match_original_comparator(self):
        original_path = HERE/'evidence/paused-motor-probe-offline/original-compare.py'
        self.assertEqual(hashlib.sha256(original_path.read_bytes()).hexdigest(),
                         '0018f0b3598b67eaab124ccebcd982dcba640b647ae073d3b4079ab39d011b00')
        original = load('pre_probe_compare', original_path)
        before, before_commands, before_events = self.mocked_arm(original)
        import shutil
        shutil.rmtree(self.out/'arm')
        after, after_commands, after_events = self.mocked_arm(c)
        self.assertTrue(after['passed'])
        self.assertEqual(before, after)
        self.assertEqual(before_commands, after_commands)
        self.assertEqual(before_events, after_events)
        self.assertNotIn('PausedMotorProbe', after_commands[0])
        self.assertNotIn('paused_motor_probe_enabled', after)

if __name__ == '__main__':
    unittest.main()
