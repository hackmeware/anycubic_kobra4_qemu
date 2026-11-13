"""Offline tests only: mocked supervision and disposable Python children, no firmware."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
PROFILE = HERE.parents[2]
spec = importlib.util.spec_from_file_location('legacy_progress_runner', HERE / 'runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
VALID = {'phase': 'verified_ready', 'request_count': 1, 'final_export_requested': True,
         'launcher_exit_code': 0, 'result': {'client_exit_status': 0, 'transport_exit_status': 0,
         'api_response': {'state': 'ready'}, 'physical_completion_proven': False}}
ACK = {'schema': 1, 'source': 'renode-shared-mcu-step', 'step_id': 0,
       'virtual_time_ns': 1_000_000_000, 'epoch': 'test-only', 'enabled': True,
       'paused': True, 'time_went_backwards': False}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.profile, self.evidence = self.root / 'profile', self.root / 'evidence'
        (self.profile / 'runs').mkdir(parents=True)
        self.evidence.mkdir()
        self.configuration, self.run, self.paths = runner.plan(self.profile, self.evidence, 'dummy')

    def tearDown(self):
        self.temporary.cleanup()

    def recorder(self):
        recorder = runner.Recorder(self.run, self.paths)
        self.addCleanup(recorder.stream.close)
        return recorder

    def test_exact_configuration_and_command(self):
        c = self.configuration
        self.assertEqual(c['command'], ['python3', '-B', str(self.profile / 'rv1106-at32-link/scripts/run_native_ready_observation.py'), 'dummy', '--seconds', '158'])
        self.assertEqual(c['budgets_seconds'], {'total': 170, 'stop_at': 158, 'graceful': 8, 'term': 2, 'kill': 2, 'planned_outer': 180})
        self.assertEqual(c['virtual_threshold_ns'], 5_000_000_000)
        self.assertFalse(c['virtual_threshold_is_strict_stepping_cap'])
        self.assertEqual(c['environment'], {
            'GLOBAL_QUANTUM_US': '1', 'NOZZLE_TMC_MODEL': 'autobaud', 'HEADLESS_READY_ONLY': '1',
            'THERMAL_PROFILE': 'none', 'Z_PROBE_PROFILE': 'none', 'NATIVE_NOZZLE_HEATER': '0',
            'CLOCK_CLIENT': 'scalar', 'ICOUNT_SHIFT': '0', 'RENODE_BOOTSTRAP': 'legacy',
            'PYTHONDONTWRITEBYTECODE': '1',
            'QEMU_BINARY': str(self.profile / 'rv1106-at32-link/experimental/clock-snapshot/runtime/run-baseline')})
        self.assertEqual(c['bootstrap_seconds'], 1)
        self.assertFalse(c['progress_adds_virtual_steps'])
        self.assertFalse(c['progress_writes_monitor_commands'])
        self.assertLessEqual(c['progress_interval_seconds'], 2)

    def test_plan_does_not_launch_or_write(self):
        with patch.object(runner, 'execute') as execute, contextlib.redirect_stdout(io.StringIO()):
            code = runner.main(['--profile', str(self.profile), '--evidence-dir', str(self.evidence), '--name', 'plan', '--plan'])
        self.assertEqual(code, 0)
        execute.assert_not_called()
        self.assertEqual(list(self.evidence.iterdir()), [])
        self.assertEqual(list((self.profile / 'runs').iterdir()), [])

    def test_invalid_names_rejected(self):
        for name in ('', '../x', 'x/y', 'a b', 'x\n'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                runner.plan(self.profile, self.evidence, name)

    def test_preexisting_paths_and_dangling_symlinks_rejected(self):
        for path in [self.run, *self.paths.values(), self.paths['latest'].with_name('dummy-latest.json.tmp')]:
            with self.subTest(path=path):
                path.symlink_to(self.root / 'missing-target')
                with self.assertRaisesRegex(ValueError, 'Fresh'):
                    runner.preflight(self.configuration, self.run, self.paths)
                path.unlink()
        self.paths['configuration'].write_text('preserve')
        with self.assertRaisesRegex(ValueError, 'Fresh'):
            runner.preflight(self.configuration, self.run, self.paths)
        self.assertEqual(self.paths['configuration'].read_text(), 'preserve')

    def test_inherited_injection_or_semantic_overrides_rejected(self):
        for key, value in [('BASH_ENV', '/tmp/unused'), ('ENV', '/tmp/unused'),
                           ('PYTHONPATH', '/tmp/unused'), ('PYTHONHOME', '/tmp/unused'),
                           ('LD_PRELOAD', '/tmp/unused'), ('LD_LIBRARY_PATH', '/tmp/unused'),
                           ('LD_AUDIT', '/tmp/unused'), ('PASSIVE_CONTACT_TRACE', '1'),
                           ('Z_BED_RELATIVE_MM', '9')]:
            with self.subTest(key=key), patch.dict(os.environ, {key: value}), self.assertRaisesRegex(ValueError, 'Unexpected'):
                runner.preflight(self.configuration, self.run, self.paths)

    def test_resource_preflight_prevents_supervisor_launch(self):
        configuration, run, paths = runner.plan(PROFILE, self.evidence, 'offline-test-never-launched')
        with patch.object(runner, 'available_memory', return_value=runner.AVAILABLE_FLOOR_BYTES - 1), patch.object(runner, 'load_supervisor') as load:
            with self.assertRaisesRegex(ValueError, 'below 2 GiB'):
                runner.execute(configuration, run, paths)
        load.assert_not_called()
        self.assertFalse(run.exists())

    def test_missing_files_are_unknown_not_zero(self):
        self.assertEqual(runner.virtual_progress(self.run / 'clock'), {'status': 'missing', 'virtual_time_ns': None})
        self.assertEqual(runner.log_tail(self.run / 'log')['status'], 'missing')

    def test_malformed_virtual_json_is_safe_and_has_no_time(self):
        path = self.root / 'clock'
        for value in ('{"virtual_time_ns":', '[]', '{"virtual_time_ns": true}', '{"virtual_time_ns": -1}', '{"virtual_time_ns": "5"}'):
            with self.subTest(value=value):
                path.write_text(value)
                result = runner.virtual_progress(path)
                self.assertEqual(result['status'], 'unavailable')
                self.assertIsNone(result['virtual_time_ns'])

    def test_virtual_threshold_is_observed_not_clamped(self):
        path = self.root / 'clock'
        path.write_text(json.dumps({'virtual_time_ns': 5_010_000_000}))
        result = runner.virtual_progress(path)
        self.assertEqual(result['virtual_time_ns'], 5_010_000_000)
        self.assertTrue(result['threshold_reached'])

    def test_log_tail_is_bounded_and_detects_truncation_and_replacement(self):
        path = self.root / 'log'
        path.write_bytes(b'a' * 5000 + b'\xffpartial')
        first = runner.log_tail(path)
        self.assertEqual(first['size_bytes'], 5008)
        self.assertLessEqual(len(first['tail']), runner.TAIL_BYTES)
        self.assertFalse(first['tail_is_complete_file'])
        path.write_bytes(b'cut')
        second = runner.log_tail(path, first)
        self.assertTrue(second['truncated_since_previous'])
        replacement = self.root / 'new-log'
        replacement.write_bytes(b'new'); replacement.replace(path)
        third = runner.log_tail(path, second)
        self.assertTrue(third['replaced_since_previous'])
        self.assertFalse(third['truncated_since_previous'])

    def test_fifo_symlink_and_oversize_are_not_read_as_evidence(self):
        fifo = self.root / 'fifo'
        os.mkfifo(fifo)
        link = self.root / 'link'
        link.symlink_to(fifo)
        for path in (fifo, link):
            self.assertEqual(runner.log_tail(path)['status'], 'unavailable')
            self.assertEqual(runner.virtual_progress(path)['status'], 'unavailable')
        huge = self.root / 'huge.json'
        huge.write_bytes(b' ' * (runner.JSON_LIMIT_BYTES + 1))
        self.assertEqual(runner.virtual_progress(huge)['status'], 'unavailable')

    def test_partial_legacy_time_does_not_claim_full_bootstrap(self):
        self.run.mkdir()
        (self.run / 'virtual-time.json').write_text('{"virtual_time_ns": 200000000}')
        recorder = self.recorder()
        recorder.sample()
        self.assertIn('virtual_time_export_observed', recorder.milestones)
        self.assertNotIn('legacy_full_bootstrap_ack_observed', recorder.milestones)
        (self.run / 'renode-step.json').write_text(json.dumps(ACK))
        recorder.sample()
        self.assertIn('legacy_full_bootstrap_ack_observed', recorder.milestones)
        self.assertNotIn('post_bootstrap_step_ack_observed', recorder.milestones)
        (self.run / 'renode-step.json').write_text(json.dumps(dict(ACK, step_id=1, virtual_time_ns=1_001_000_000)))
        recorder.sample()
        self.assertIn('post_bootstrap_step_ack_observed', recorder.milestones)

    def test_malformed_step_ack_does_not_claim_bootstrap(self):
        self.run.mkdir()
        path = self.run / 'renode-step.json'
        for update in ({'paused': False}, {'enabled': False}, {'step_id': True}, {'schema': True}, {'epoch': ''}, {'source': 'other'}):
            path.write_text(json.dumps(dict(ACK, **update)))
            self.assertEqual(runner.virtual_progress(path, step_ack=True)['status'], 'unavailable')

    def test_append_only_progress_and_small_atomic_latest(self):
        recorder = self.recorder()
        recorder.sample()
        prefix = self.paths['progress'].read_bytes()
        recorder.sample(final=True)
        full = self.paths['progress'].read_bytes()
        self.assertTrue(full.startswith(prefix))
        rows = [json.loads(line) for line in full.splitlines()]
        self.assertEqual([row['sequence'] for row in rows], [0, 1])
        latest = json.loads(self.paths['latest'].read_text())
        self.assertFalse(latest['success'])
        self.assertFalse(latest['resumable_vm_snapshot'])
        self.assertTrue(latest['outer_guard_verification_pending'])
        self.assertIn('inner cleanup only', latest['success_scope'])
        self.assertLess(self.paths['latest'].stat().st_size, 16384)
        self.assertNotIn('tail', latest['logs']['renode.log'])
        self.assertFalse(self.paths['latest'].with_suffix('.json.tmp').exists())

    def test_resource_stop_pending_until_run_directory_exists(self):
        recorder = self.recorder()
        with patch.object(runner, 'available_memory', return_value=runner.AVAILABLE_FLOOR_BYTES - 1):
            recorder.sample()
            self.assertFalse(self.run.exists())
            self.assertEqual(recorder.last_row['stop_request'], 'pending_run_directory')
            self.run.mkdir()
            recorder.sample()
        self.assertTrue((self.run / 'stop-request').exists())
        self.assertTrue(recorder.resource_guard_triggered)
        self.assertEqual(list(self.run.iterdir()), [self.run / 'stop-request'])

    def test_rss_limit_requests_stop(self):
        self.run.mkdir()
        recorder = self.recorder()
        with patch.object(runner, 'group_members', return_value=[{'rss_bytes': runner.RSS_LIMIT_BYTES + 1, 'qemu_baseline_process': False}]):
            recorder.sample()
        self.assertTrue(recorder.resource_guard_triggered)
        self.assertTrue((self.run / 'stop-request').exists())

    def test_sampler_error_requests_stop_and_is_persisted(self):
        self.run.mkdir()
        recorder = self.recorder()
        with patch.object(runner, 'available_memory', side_effect=OSError('injected telemetry failure')):
            recorder.attempt_sample()
        self.assertTrue(recorder.errors)
        self.assertTrue((self.run / 'stop-request').exists())
        self.assertIn('sampling_error', json.loads(self.paths['progress'].read_text()))
        self.assertFalse(json.loads(self.paths['latest'].read_text())['success'])

    def run_dummy(self, native_report):
        supervisor = runner.load_supervisor(PROFILE)
        body = f"import pathlib,json,time; d=pathlib.Path({str(self.run)!r}); d.mkdir(); time.sleep(.05); "
        if native_report is not None:
            body += f"(d/'ready-observation.json').write_text(json.dumps({native_report!r})); "
        self.configuration['command'] = [sys.executable, '-B', '-c', body]
        handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
        old_environment = dict(os.environ)
        with patch.object(runner, 'preflight'), patch.object(runner, 'load_supervisor', return_value=supervisor):
            report = runner.execute(self.configuration, self.run, self.paths)
        self.assertEqual(dict(os.environ), old_environment)
        self.assertEqual({sig: signal.getsignal(sig) for sig in handlers}, handlers)
        self.assertTrue(report['post_audit']['sampling_finished'])
        self.assertTrue(report['post_audit']['group_absent_confirmed'])
        self.assertFalse(any(t.name == 'legacy-host-progress' for t in threading.enumerate()))
        return report

    def test_dummy_valid_ready_can_pass_inner_scope_only(self):
        report = self.run_dummy(VALID)
        self.assertTrue(report['success'], report)
        self.assertFalse(report['physical_completion_proven'])
        self.assertIn('outer guard', report['success_scope'])
        latest = json.loads(self.paths['latest'].read_text())
        self.assertTrue(latest['outer_guard_verification_pending'])
        self.assertEqual(latest['success_scope'], report['success_scope'])

    def test_dummy_no_ready_cannot_pass(self):
        report = self.run_dummy(None)
        self.assertFalse(report['success'])
        self.assertFalse(report['supervision']['native_report_valid'])
        self.assertEqual(json.loads(self.paths['latest'].read_text())['status'], 'failed')

    def test_dummy_failed_ready_report_cannot_pass(self):
        report = self.run_dummy(dict(VALID, phase='error', error='Native readiness failed'))
        self.assertFalse(report['success'])
        self.assertFalse(report['supervision']['native_report_valid'])

    def test_exact_supervise_call_and_exception_finalization(self):
        supervisor = runner.load_supervisor(PROFILE)
        old_environment = dict(os.environ)
        with patch.object(runner, 'preflight'), patch.object(runner, 'load_supervisor', return_value=supervisor), \
             patch.object(supervisor, 'supervise', side_effect=RuntimeError('injected failure')) as supervise:
            report = runner.execute(self.configuration, self.run, self.paths)
        self.assertFalse(report['success'])
        self.assertEqual(dict(os.environ), old_environment)
        self.assertTrue(report['post_audit']['sampling_finished'])
        supervise.assert_called_once_with(self.configuration['command'], stop_request=self.run / 'stop-request',
            native_report=self.run / 'ready-observation.json', evidence=self.paths['supervision'],
            total_seconds=170, grace_seconds=8, term_seconds=2, kill_seconds=2,
            virtual_time_file=self.run / 'virtual-time.json', max_virtual_time_ns=5_000_000_000)


if __name__ == '__main__':
    unittest.main()
