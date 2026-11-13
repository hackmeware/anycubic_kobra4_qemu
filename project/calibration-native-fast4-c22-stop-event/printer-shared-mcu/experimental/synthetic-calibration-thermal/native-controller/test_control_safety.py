"""Offline console-ownership and graceful-stop regressions. Never starts a VM.

All temperatures and clock updates here are mock test vectors, not new native
observations or physical-model evidence. Existing protocol helpers are reused.
"""
import contextlib
import hashlib
import json
import pathlib
import re
import tempfile
import unittest
from unittest import mock

import test_controller as existing

m = existing.m
HERE = pathlib.Path(__file__).resolve().parent
CORRUPT_CAPTURE = HERE / 'console-safety-review' / 'status019-raw-dump-region.txt'
CORRUPT_CAPTURE_SHA256 = 'b7951d3fab4e0d15afc9547d37ee4f441397bad4596ce02d414b86e92fe6b9fa'
INTENT = {'action': 'stop_heating', 'reason': 'Offline regression requests graceful stop'}


class DelayedLauncher(existing.SimulatedLauncher):
    """An inert launcher double with independently delayed shell batch output.

    Rejects *any* new console input before the prior actual final marker is
    emitted, including otherwise-valid log reads. It never executes a command.
    """
    STEP_US = 250000

    def __init__(self, root, scenario='success', failure=None, remove_intent=False):
        super().__init__(root, 'success')
        self.scenario = scenario
        self.failure = failure
        self.remove_intent = remove_intent
        self.now_us = 0
        self.command_cursor = 0
        self.active = None
        self.started = []
        self.finished = []
        self.violations = []
        self.intent_written = False
        self.intent_removed = False
        self.intent_batch = None
        self.pending_at_wait = None
        self.final_delay_started = False
        self.pending_after_cooling_proven = False
        (self.directory / 'shared-profile.json').write_text('{}')

    def report(self):
        path = self.directory / 'thermal-observation.json'
        return json.loads(path.read_text()) if path.exists() else {}

    def publish_intent(self, batch):
        temporary = self.directory / (m.GRACEFUL_STOP_FILE + '.tmp')
        temporary.write_text(json.dumps(INTENT))
        temporary.replace(self.directory / m.GRACEFUL_STOP_FILE)
        self.intent_written = True
        self.intent_batch = batch

    def should_interrupt(self, stage):
        if self.intent_written:
            return False
        return ((self.scenario == 'pending_target' and stage == 'target') or
                (self.scenario == 'pending_status' and stage.startswith('status') and self.target != 0) or
                (self.scenario == 'pending_log' and stage == 'log' and self.target != 0) or
                (self.scenario == 'pending_baseline' and stage == 'status001') or
                (self.scenario == 'pending_ready' and stage == 'ready'))

    def start_batch(self, command_text):
        rpc = list(re.finditer(r'(?m)^echo (THERMAL_([A-Z0-9]+)_BEGIN_[a-f0-9]+)$', command_text))
        logs = list(re.finditer(r'echo (THERMAL_LOG_END_[a-f0-9]+_[0-9]+)', command_text))
        if len(rpc) + len(logs) != 1:
            self.violations.append('Multiple or unknown batches were appended together')
            raise AssertionError(self.violations[-1])
        if rpc:
            begin, stage = rpc[0][1], rpc[0][2].lower()
            method = ('PrinterState' if stage == 'ready' else 'GetStatus' if stage.startswith('status')
                      else m.METHODS[self.selected])
            request = {'begin': begin, 'end': begin.replace('_BEGIN_', '_END_'), 'method': method}
            if stage == 'target':
                self.target = m.TARGETS[self.selected]
            elif stage == 'zero':
                self.target = 0
                self.zero_at = self.now_us
            payload = (bytes.fromhex('12057265616479') if stage == 'ready' else
                       existing.native_payload(m.TARGETS['nozzle'] if self.target else 25, self.target)
                       if method == 'GetStatus' else b'')
            response = existing.capture(request, payload)
            raw_start = response.index(m.ready.RAW_BEGIN) + len(m.ready.RAW_BEGIN) + 1
            raw_end = response.index(m.ready.RAW_END)
            split = raw_start + (raw_end - raw_start) // 2
            end_at = response.index(request['end'])
            # The compound execution line is echoed first. It contains the end
            # marker text but is deliberately not a standalone emitted marker.
            echo = '/ # ' + command_text.splitlines()[-1] + '\n'
            chunks = [echo + response[:raw_start], response[raw_start:split],
                      response[split:end_at], response[end_at:]]
            kind = 'rpc:' + stage
        else:
            stage = 'log'
            marker = logs[0][1]
            chunks = ['/ # ' + command_text, 'mock log body\n', marker + '\n']
            kind = 'log'

        batch = {'kind': kind, 'stage': stage, 'start_us': self.now_us, 'chunks': chunks, 'index': 0}
        self.started.append({'kind': kind, 'stage': stage, 'start_us': self.now_us})
        if self.should_interrupt(stage):
            self.publish_intent(batch)
            if self.failure == 'timeout':
                batch['chunks'] = chunks[:1]
                batch['stall'] = True
            elif self.failure == 'corrupt':
                if stage == 'log':
                    batch['chunks'][-1] *= 2
                else:
                    batch['chunks'] = [chunk.replace(m.ready.RAW_END, 'INVALID_RAW_END') for chunk in chunks]
        report = self.report()
        if (self.scenario == 'final_drain' and not self.final_delay_started and
                report.get('phase') == 'cooling' and stage.startswith('status') and
                report.get('thermal_observations', {}).get('nozzle', {}).get('actual_off_duration_s', 0) >= 3):
            # Keep one final status outstanding across the 5s off boundary.
            batch['chunks'][-1:-1] = [''] * 9
            self.final_delay_started = True
        self.active = batch

    def poll(self):
        if (self.directory / 'stop-request').exists():
            return 0
        self.now_us += self.STEP_US
        self.seconds = self.now_us / 1e6
        if self.now_us > 365000000:
            raise AssertionError('Mock exceeded the controller absolute virtual cap')
        report = self.report()
        if (self.remove_intent and self.intent_written and not self.intent_removed and
                report.get('graceful_stop_intent') is not None):
            (self.directory / m.GRACEFUL_STOP_FILE).unlink()
            self.intent_removed = True
        if self.active is not None and report.get('physical_cooling_observed'):
            self.pending_after_cooling_proven = True
        commands = (self.directory / 'console-input.commands').read_bytes()
        if self.active is not None and len(commands) != self.command_cursor:
            self.violations.append('Input changed while ' + self.active['kind'] + ' lacked its final end marker')
            raise AssertionError(self.violations[-1])
        if self.active is None and len(commands) > self.command_cursor:
            new_commands = commands[self.command_cursor:].decode('ascii')
            self.command_cursor = len(commands)
            self.start_batch(new_commands)
        if self.active is not None:
            batch = self.active
            if batch['index'] < len(batch['chunks']):
                with (self.directory / 'console.bin').open('a') as stream:
                    stream.write(batch['chunks'][batch['index']])
                batch['index'] += 1
            if batch['index'] == len(batch['chunks']) and not batch.get('stall'):
                self.finished.append({'kind': batch['kind'], 'stage': batch['stage'], 'finish_us': self.now_us})
                self.active = None
        # Five deterministic samples per poll preserve the original 500ms
        # maximum observer interval without invoking the actual thermal model.
        for heater in m.TARGETS:
            if heater == self.selected and self.target:
                physical = m.TARGETS[heater]
            elif heater == self.selected and self.zero_at is not None:
                physical = m.TARGETS[heater] - (self.now_us - self.zero_at) / 1e6
            else:
                physical = 25
            with (self.directory / (heater + '-thermal-live.csv')).open('a') as stream:
                for offset in range(50000, self.STEP_US + 1, 50000):
                    stream.write(existing.row(self.now_us - self.STEP_US + offset, physical,
                                              int(heater == self.selected and bool(self.target)),
                                              .7 if heater == self.selected and self.target else 0,
                                              heater=heater))
        (self.directory / 'virtual-time.json').write_text(json.dumps({
            'virtual_time_ns': self.now_us * 1000, 'time_went_backwards': False,
            'enabled': True, 'epoch': 'delayed-offline-mock'}))
        return None

    def wait(self, timeout=None):
        self.pending_at_wait = self.active['kind'] if self.active is not None else None
        return 0


class ConsoleAndStopSafety(unittest.TestCase):
    def execute(self, scenario='success', failure=None, remove_intent=False,
                profile='accelerated-functional-4x', prepare_hook=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            holder = {}

            def start(*unused, **kwargs):
                holder['process'] = DelayedLauncher(root, scenario, failure, remove_intent)
                return holder['process']

            original_prepare = m.prepare_request

            def prepare(*args, **kwargs):
                result = original_prepare(*args, **kwargs)
                if prepare_hook is not None:
                    prepare_hook(holder['process'], args[1])
                return result

            args = m.parse_args(['mock', '--thermal-profile', profile, '--heater', 'nozzle',
                                 '--nozzle-tmc-model', 'autobaud', '--execute'])
            with contextlib.ExitStack() as stack:
                for target, name, value in [(m, 'ROOT', root), (m, 'verify_dependencies', mock.Mock(return_value={})),
                        (m, 'validate_profile', mock.Mock(return_value={})),
                        (m.xyz, 'validate_tmc_manifest', mock.Mock(return_value={})),
                        (m, 'final_status_issues', mock.Mock(return_value=[])),
                        (m.replay, 'analyze', mock.Mock(return_value={'mocked_not_physical': True})),
                        (m.subprocess, 'Popen', mock.Mock(side_effect=start)),
                        (m.time, 'sleep', mock.Mock()), (m, 'prepare_request', prepare)]:
                    stack.enter_context(mock.patch.object(target, name, value))
                code = m.run(args)
            process = holder['process']
            result = process.report()
            command_text = (process.directory / 'console-input.commands').read_text()
            self.assertEqual(process.violations, [], result.get('error'))
            return code, result, process, command_text

    def assert_serialized(self, result, complete=True):
        batches = result['console_batches']
        self.assertTrue(batches)
        for previous, following in zip(batches, batches[1:]):
            self.assertIn('validated_completion_controller_ns', previous)
            self.assertLessEqual(previous['validated_completion_controller_ns'], following['queued_controller_ns'])
        if complete:
            self.assertTrue(all('validated_completion_controller_ns' in item for item in batches))

    def test_all_rpc_and_log_output_is_serialized_across_delayed_polls(self):
        code, result, process, commands = self.execute()
        self.assertEqual(code, 0, result)
        self.assert_serialized(result)
        self.assertIn('log', [entry['kind'] for entry in result['console_batches']])
        self.assertIsNone(process.pending_at_wait)
        self.assertTrue(result['complete_functional_evidence'])
        self.assertFalse(result['regulation_criterion_met'])
        self.assertFalse(result['complete_regulation_evidence'])
        self.assertFalse(result['pid_calibration_completed'])
        self.assertEqual(result['limits']['physical_and_native_band_seconds'], 5)
        for line in commands.splitlines():
            if line.startswith('chmod '):
                self.assertIn('; timeout -t 5 ', line)
                self.assertIn('; od -v -b ', line)
                self.assertRegex(line, r'; echo THERMAL_[A-Z0-9]+_END_')
                self.assertLess(len(line), 1024)
            if line.startswith('tail '):
                self.assertIn('; tail ', line)
                self.assertIn('; echo THERMAL_LOG_END_', line)

    def test_original_profile_still_requires_30_second_regulation(self):
        code, result, process, unused = self.execute(profile='synthetic-calibration')
        self.assertEqual(code, 0, result)
        self.assertTrue(result['complete_regulation_evidence'])
        self.assertFalse(result['complete_functional_evidence'])
        self.assertEqual(result['limits']['physical_and_native_band_seconds'], 30)
        self.assertEqual(result['limits']['heat_virtual_seconds'], 240)
        self.assertEqual(result['limits']['zero_lead_virtual_seconds'], 232)
        self.assert_serialized(result)

    def test_intent_during_pending_target_status_and_log_drains_then_one_zero(self):
        for scenario in ('pending_target', 'pending_status', 'pending_log'):
            with self.subTest(scenario=scenario):
                code, result, process, unused = self.execute(scenario)
                self.assertEqual(code, 2, result)
                self.assertTrue(process.intent_written)
                self.assertTrue(result['graceful_stop_completed'], result)
                self.assertTrue(result['zero_response_verified'])
                self.assertTrue(result['native_zero_target_observed'])
                self.assertTrue(result['actual_heater_off_observed'])
                self.assertTrue(result['physical_cooling_observed'])
                self.assertFalse(result['complete_functional_evidence'])
                self.assert_serialized(result)
                stages = [entry['stage'] for entry in result['requests']]
                self.assertEqual(stages.count('target'), 1)
                self.assertEqual(stages.count('zero'), 1)
                interrupted = next(item for item in process.finished if item['kind'] == process.intent_batch['kind']
                                   and item['finish_us'] >= process.intent_batch['start_us'])
                zero = next(item for item in process.started if item['stage'] == 'zero')
                self.assertLessEqual(interrupted['finish_us'], zero['start_us'])
                self.assertIsNone(process.pending_at_wait)

    def test_intent_before_target_prevents_heating(self):
        for scenario in ('pending_ready', 'pending_baseline'):
            with self.subTest(scenario=scenario):
                code, result, process, unused = self.execute(scenario)
                self.assertEqual(code, 2, result)
                self.assertTrue(result['graceful_stop_completed'])
                self.assertEqual(result['phase'], 'graceful_stopped_before_heat')
                self.assertFalse(result['target_response_accepted'])
                self.assertNotIn('target', [entry['stage'] for entry in result['requests']])
                self.assertNotIn('zero', [entry['stage'] for entry in result['requests']])
                self.assert_serialized(result)
                self.assertIsNone(process.pending_at_wait)

    def test_intent_arriving_during_target_generation_cancels_append(self):
        def during_prepare(process, stage):
            if stage == 'target':
                process.publish_intent({'kind': 'preappend:target'})
        code, result, process, commands = self.execute(prepare_hook=during_prepare)
        self.assertEqual(code, 2, result)
        self.assertTrue(result['graceful_stop_completed'])
        self.assertFalse(result['target_response_accepted'])
        self.assertNotIn('THERMAL_TARGET_BEGIN_', commands)
        target = [entry for entry in result['requests'] if entry['stage'] == 'target']
        self.assertEqual(len(target), 1)
        self.assertEqual(target[0]['queue_outcome'], 'cancelled_before_append')
        self.assert_serialized(result)

    def test_latched_intent_survives_file_removal_without_reheat(self):
        code, result, process, unused = self.execute('pending_status', remove_intent=True)
        self.assertEqual(code, 2, result)
        self.assertTrue(process.intent_removed)
        self.assertEqual(result['graceful_stop_intent']['reason'], INTENT['reason'])
        self.assertTrue(result['graceful_stop_completed'])
        self.assertEqual([entry['stage'] for entry in result['requests']].count('target'), 1)
        self.assertEqual([entry['stage'] for entry in result['requests']].count('zero'), 1)
        self.assert_serialized(result)

    def test_corrupt_or_timed_out_pending_capture_never_injects_zero_or_retries(self):
        for scenario in ('pending_target', 'pending_status', 'pending_log'):
            for failure in ('corrupt', 'timeout'):
                with self.subTest(scenario=scenario, failure=failure):
                    code, result, process, unused = self.execute(scenario, failure)
                    self.assertEqual(code, 2, result)
                    self.assertTrue(process.intent_written)
                    self.assertEqual(result['phase'], 'error', result)
                    self.assertFalse(result['zero_response_verified'])
                    self.assertFalse(result['graceful_stop_completed'])
                    self.assertNotIn('zero', [entry['stage'] for entry in result['requests']])
                    self.assertEqual(result['console_batches'][-1]['kind'], process.intent_batch['kind'])
                    self.assertNotIn('validated_completion_controller_ns', result['console_batches'][-1])
                    self.assert_serialized(result, complete=False)

    def test_final_success_waits_for_outstanding_capture_end(self):
        code, result, process, unused = self.execute('final_drain')
        self.assertTrue(process.final_delay_started, result)
        self.assertTrue(process.pending_after_cooling_proven, result)
        self.assertEqual(code, 0, result)
        self.assertIsNone(process.pending_at_wait)
        self.assert_serialized(result)


class IntentAndHistoricalCapture(unittest.TestCase):
    def test_intent_shape_is_exact_and_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / 'intent.json'
            self.assertIsNone(m.read_graceful_stop(path))
            path.write_text(json.dumps(INTENT))
            parsed = m.read_graceful_stop(path)
            self.assertEqual({key: parsed[key] for key in INTENT}, INTENT)
            self.assertEqual(parsed['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            invalid = [[], {}, dict(INTENT, extra=True), dict(INTENT, action='reheat'),
                       dict(INTENT, reason=''), dict(INTENT, reason=True),
                       dict(INTENT, reason='line\nbreak'), dict(INTENT, reason='x' * 1001)]
            for value in invalid:
                path.write_text(json.dumps(value))
                with self.subTest(value=str(value)[:80]), self.assertRaises(ValueError):
                    m.read_graceful_stop(path)
            path.write_bytes(b' ' * 4097)
            with self.assertRaisesRegex(ValueError, '4096'):
                m.read_graceful_stop(path)

    def test_preserved_r3_status019_corruption_remains_rejected(self):
        raw = CORRUPT_CAPTURE.read_bytes()
        source = m.ROOT / 'runs/native-nozzle-230-synthetic-r3/safe-stop-r3/status019-raw-dump-region.txt'
        self.assertEqual(hashlib.sha256(raw).hexdigest(), CORRUPT_CAPTURE_SHA256)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), CORRUPT_CAPTURE_SHA256)
        self.assertIn(b"printf '\\051\\004\\240\\340000000", raw)
        with self.assertRaisesRegex(ValueError, 'Noncontiguous or repeated raw dump'):
            m.ready.read_od(raw.decode())


if __name__ == '__main__':
    unittest.main()
