"""Offline tests only: mocked supervision and disposable Python children, no firmware."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
PROFILE = HERE.parents[2]
spec = importlib.util.spec_from_file_location('homing_completion_observation_runner', HERE / 'runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
OBSERVER_SOURCE = PROFILE / runner.OBSERVER_RELATIVE
HOMING = {'phase': 'verified_homing_completion', 'request_count': 8,
          'final_export_requested': True, 'launcher_exit_code': 0,
          'homing_completed': True, 'natural_release_observed': True,
          'physical_completion_proven': False, 'calibration_completed': False}
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
        self.profile_patch = patch.object(runner, 'EXPECTED_PROFILE', self.profile)
        self.profile_patch.start()
        self.addCleanup(self.profile_patch.stop)
        self.configuration, self.run, self.paths = runner.plan(self.profile, self.evidence, 'dummy')
        self.prefix_patch = patch.object(sys, 'pycache_prefix', self.configuration['python_cache_prefix'])
        self.prefix_patch.start()
        self.addCleanup(self.prefix_patch.stop)

    def tearDown(self):
        self.temporary.cleanup()

    def recorder(self):
        recorder = runner.Recorder(self.run, self.paths)
        self.addCleanup(recorder.stream.close)
        return recorder

    def test_exact_configuration_and_command(self):
        c = self.configuration
        self.assertEqual(c['command'], [runner.HOST_PYTHON, '-I', '-B', '-X', 'pycache_prefix=' + str(self.evidence / 'dummy-python-cache'), str(self.profile / runner.OBSERVER_RELATIVE), '--run-name', 'dummy', '--seconds', '4768'])
        self.assertEqual(c['budgets_seconds'], {'total': 4780, 'stop_at': 4768, 'graceful': 8, 'term': 2, 'kill': 2, 'planned_outer': 4800})
        self.assertEqual(c['virtual_threshold_ns'], 45_000_000_000)
        self.assertFalse(c['virtual_threshold_is_strict_stepping_cap'])
        self.assertEqual(c['environment'], {
            'GLOBAL_QUANTUM_US': '1', 'NOZZLE_TMC_MODEL': 'autobaud', 'HEADLESS_READY_ONLY': '1',
            'THERMAL_PROFILE': 'none', 'Z_PROBE_PROFILE': 'synthetic-functional', 'PASSIVE_MOTOR_TRACE': '0', 'NATIVE_NOZZLE_HEATER': '0',
            'CLOCK_CLIENT': 'scalar', 'ICOUNT_SHIFT': '0', 'RENODE_BOOTSTRAP': 'legacy',
            'PYTHONDONTWRITEBYTECODE': '1',
            'PYTHONPYCACHEPREFIX': str(self.evidence / 'dummy-python-cache'),
            'QEMU_BINARY': str(self.profile / 'rv1106-at32-link/experimental/clock-snapshot/runtime/run-baseline')})
        self.assertEqual(c['bootstrap_seconds'], 1)
        self.assertFalse(c['progress_adds_virtual_steps'])
        self.assertFalse(c['progress_writes_monitor_commands'])
        self.assertLessEqual(c['progress_interval_seconds'], 2)

    def test_planned_command_matches_observer_argparse_without_launch(self):
        # Compile only the actual inert CLI function, never the runtime/import body.
        import argparse
        import ast
        import re
        from unittest.mock import Mock
        source = OBSERVER_SOURCE
        tree = ast.parse(source.read_bytes(), filename=str(source))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main']
        self.assertEqual(len(functions), 1)
        budgets = [ast.literal_eval(node.value) for node in tree.body
                   if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'ACTIVE_SECONDS' for target in node.targets)]
        self.assertEqual(budgets, [4768])
        run = Mock(return_value={'success': True})
        scope = {'argparse': argparse, 're': re, 'sys': sys, 'Path': Path,
                 'os': os, 'ACTIVE_SECONDS': budgets[0], 'ROOT': self.profile, 'run': run}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), scope)
        command = self.configuration['command']
        arguments = command[command.index(str(self.profile / runner.OBSERVER_RELATIVE)) + 1:]
        with patch.dict(os.environ, {'PYTHONPYCACHEPREFIX': self.configuration['python_cache_prefix']}):
            self.assertEqual(scope['main'](arguments), 0)
        run.assert_called_once_with(self.profile, 'dummy', self.configuration['python_cache_prefix'])
        for bad in (['dummy', '--seconds', '4768'], ['--run-name', 'dummy', '--seconds', '4769']):
            run.reset_mock()
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                scope['main'](bad)
            run.assert_not_called()

    def test_prior_runner_and_production_sources_are_preserved(self):
        expected = {
            'rv1106-at32-link/experimental/legacy-ready/runner.py': '0cef7ec31a8ff777c8bd4a2404dce0a8e2c2e3ea4f5eb12586cbd4f26cc63448',
            'rv1106-at32-link/experimental/legacy-ready/outer_guard.py': '61b9e6b9d37cde35bf025295357c22d2da2bc60b7acc1061cde3d7fab709e954',
            'rv1106-at32-link/experimental/legacy-progress/runner.py': '569006cc81fc34254bb3947aa39763af3bc593f2c30f234eee140fa3eb043ec7',
            'rv1106-at32-link/scripts/run_native_ready_observation.py': '59d018994fe46282ade656f6e144ece30caf718e427c1bd99ad4f0d7f409b510',
            'rv1106-at32-link/scripts/bounded_native_supervisor.py': '48abc81b323217ecf6811dec29c865b6b9bf87f470f7c4ec24bae3bd597f4ca7',
            'rv1106-at32-link/experimental/bootstrap-boundaries/outer_guard.py': 'd2f1eb705e1b11311223c3584d578ced1963d2e11de2148306315952a81c1348',
        }
        for relative, digest in expected.items():
            with self.subTest(source=relative):
                self.assertEqual(hashlib.sha256((PROFILE / relative).read_bytes()).hexdigest(), digest)

    def test_late_generation_is_killed_without_extending_cleanup_or_claiming_ready(self):
        # Only test reserves are shortened. The real preset remains 4768 + 8 + 2 + 2.
        # This dummy stands in for an observer stuck generating its one probe.
        supervisor = runner.load_supervisor(PROFILE)
        body = ("import pathlib,json,time,signal; "
                "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                f"d=pathlib.Path({str(self.run)!r}); d.mkdir(); "
                "(d/'generation-started').write_text('dummy only'); "
                "(d/'ready-prerequisite.json').write_text(json.dumps({'phase':'waiting_ready','generation_attempts':1,'request_count':0})); "
                "(d/'virtual-time.json').write_text(json.dumps({'virtual_time_ns':45000000000})); "
                "time.sleep(5)")
        self.configuration['command'] = [sys.executable, '-B', '-c', body]
        started = time.monotonic()
        with patch.object(runner, 'preflight'), patch.object(runner, 'load_supervisor', return_value=supervisor), \
             patch.multiple(runner, TOTAL_SECONDS=.8, GRACE_SECONDS=.2, TERM_SECONDS=.1, KILL_SECONDS=.1):
            report = runner.execute(self.configuration, self.run, self.paths)
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue((self.run / 'generation-started').is_file())
        self.assertFalse(report['success'])
        self.assertFalse(report['supervision']['native_report_valid'])
        self.assertEqual(report['supervision']['forced_signals'], ['SIGTERM', 'SIGKILL'])
        self.assertTrue(report['post_audit']['group_absent_confirmed'])
        self.assertTrue(report['post_audit']['sampling_finished'])
        self.assertEqual(runner.TOTAL_SECONDS, 4780)
        self.assertEqual(runner.GRACE_SECONDS, 8)

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
        with patch.object(runner, 'EXPECTED_PROFILE', PROFILE):
            configuration, run, paths = runner.plan(PROFILE, self.evidence, 'offline-test-never-launched')
        with patch.object(sys, 'pycache_prefix', configuration['python_cache_prefix']), patch.object(runner, 'EXPECTED_PROFILE', PROFILE), patch.object(runner, 'available_memory', return_value=runner.AVAILABLE_FLOOR_BYTES - 1), patch.object(runner, 'load_supervisor') as load:
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
        path.write_text(json.dumps({'virtual_time_ns': 45_010_000_000}))
        result = runner.virtual_progress(path)
        self.assertEqual(result['virtual_time_ns'], 45_010_000_000)
        self.assertTrue(result['threshold_reached'])

    def test_shared_stop_domain_and_sample_boundary_are_fixed(self):
        self.assertEqual(runner.VIRTUAL_THRESHOLD_NS, 45_000_000_000)
        self.assertEqual(self.configuration['shared_stop_seconds'], 45)
        self.assertNotIn('shared_stop_host_seconds', self.configuration)
        self.assertEqual(self.configuration['virtual_threshold_ns'], 45_000_000_000)
        path = self.root / 'clock'
        for now, reached in ((15_000_000_000, False), (44_999_999_999, False),
                             (45_000_000_000, True), (45_010_000_000, True)):
            with self.subTest(now=now):
                path.write_text(json.dumps({'virtual_time_ns': now}))
                result = runner.virtual_progress(path)
                self.assertEqual(result['virtual_time_ns'], now)
                self.assertIs(result['threshold_reached'], reached)

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

    def run_dummy(self, native_report, *, homing_completion_valid=False):
        supervisor = runner.load_supervisor(PROFILE)
        body = f"import pathlib,json,time; d=pathlib.Path({str(self.run)!r}); d.mkdir(); time.sleep(.05); "
        if native_report is not None:
            body += f"(d/'ready-prerequisite.json').write_text(json.dumps({native_report!r})); "
        self.configuration['command'] = [sys.executable, '-B', '-c', body]
        handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
        old_environment = dict(os.environ)
        homing_completion_error = None if homing_completion_valid else ValueError('Synthetic homing_completion report missing or invalid')
        with patch.object(runner, 'preflight'), patch.object(runner, 'load_supervisor', return_value=supervisor), \
             patch.object(runner, 'read_homing_completion_report', side_effect=homing_completion_error, return_value={'fixture_only': True}):
            report = runner.execute(self.configuration, self.run, self.paths)
        self.assertEqual(dict(os.environ), old_environment)
        self.assertEqual({sig: signal.getsignal(sig) for sig in handlers}, handlers)
        self.assertTrue(report['post_audit']['sampling_finished'])
        self.assertTrue(report['post_audit']['group_absent_confirmed'])
        self.assertFalse(any(t.name == 'homing_completion-host-progress' for t in threading.enumerate()))
        return report

    def test_dummy_ready_and_mocked_homing_completion_validation_can_pass_inner_scope_only(self):
        report = self.run_dummy(VALID, homing_completion_valid=True)
        self.assertTrue(report['success'], report)
        self.assertTrue(report['homing_completed'])
        self.assertTrue(report['natural_release_observed'])
        self.assertFalse(report['physical_completion_proven'])
        self.assertFalse(report['calibration_completed'])
        self.assertIn('outer guard', report['success_scope'])
        latest = json.loads(self.paths['latest'].read_text())
        self.assertTrue(latest['outer_guard_verification_pending'])
        self.assertEqual(latest['success_scope'], report['success_scope'])

    def test_dummy_genuine_ready_without_homing_completion_fails(self):
        report = self.run_dummy(VALID)
        self.assertFalse(report['success'])
        self.assertTrue(report['supervision']['native_report_valid'])
        self.assertFalse(report['homing_completion_report_valid'])

    def test_dummy_no_ready_cannot_pass(self):
        report = self.run_dummy(None)
        self.assertFalse(report['success'])
        self.assertFalse(report['supervision']['native_report_valid'])
        self.assertEqual(json.loads(self.paths['latest'].read_text())['status'], 'failed')

    def test_dummy_failed_ready_report_cannot_pass(self):
        report = self.run_dummy(dict(VALID, phase='error', error='Native readiness failed'))
        self.assertFalse(report['success'])
        self.assertFalse(report['supervision']['native_report_valid'])

    def test_exact_supervise_call_includes_fixed_45_second_stop_and_exception_finalization(self):
        supervisor = runner.load_supervisor(PROFILE)
        old_environment = dict(os.environ)
        with patch.object(runner, 'preflight'), patch.object(runner, 'load_supervisor', return_value=supervisor), \
             patch.object(supervisor, 'supervise', side_effect=RuntimeError('injected failure')) as supervise:
            report = runner.execute(self.configuration, self.run, self.paths)
        self.assertFalse(report['success'])
        self.assertEqual(dict(os.environ), old_environment)
        self.assertTrue(report['post_audit']['sampling_finished'])
        supervise.assert_called_once_with(self.configuration['command'], stop_request=self.run / 'stop-request',
            native_report=self.run / 'ready-prerequisite.json', evidence=self.paths['supervision'],
            total_seconds=4780, grace_seconds=8, term_seconds=2, kill_seconds=2,
            virtual_time_file=self.run / 'virtual-time.json', max_virtual_time_ns=45_000_000_000)





class FixedBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.evidence = self.root / 'evidence'
        self.evidence.mkdir()

    def test_exact_profile_only_and_symlinked_directory_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exact source profile'):
            runner.plan(self.root, self.evidence, 'dummy')
        link = self.root / 'alias'
        link.symlink_to(self.evidence, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlinked'):
            runner.plan(PROFILE, link, 'dummy')

    def test_configuration_mutation_rejected_before_supervisor_import(self):
        configuration, run, paths = runner.plan(PROFILE, self.evidence, 'offline-mutation')
        for key, replacement in [('command', ['arbitrary']), ('environment', {}),
                                 ('budgets_seconds', {'total': 999}), ('observer_work_host_seconds', 999)]:
            changed = dict(configuration, **{key: replacement})
            with self.subTest(key=key), patch.object(runner, 'load_supervisor') as load:
                with self.assertRaisesRegex(ValueError, 'fixed homing_completion plan'):
                    runner.execute(changed, run, paths)
                load.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'fixed homing_completion plan'):
            runner.preflight(configuration, self.root / 'alternate-run', paths)

    def test_bad_semantic_environment_rejected(self):
        for key, value in [('GLOBAL_QUANTUM_US', '10'), ('THERMAL_PROFILE', 'synthetic-calibration'),
                           ('Z_PROBE_PROFILE', 'none'), ('PASSIVE_MOTOR_TRACE', '1'), ('NOZZLE_TMC_MODEL', 'fixed'),
                           ('CLOCK_CLIENT', 'snapshot'), ('RENODE_BOOTSTRAP', 'paused'),
                           ('ICOUNT_SHIFT', '1'), ('QEMU_BINARY', '/tmp/other'),
                           ('NATIVE_NOZZLE_HEATER', '1'), ('RUN_SECONDS', '1'),
                           ('PASSIVE_NOZZLE_TRACE', '1'), ('MOTOR_ENABLE_WIRING', 'other')]:
            with self.subTest(key=key), patch.dict(os.environ, {key: value}):
                with self.assertRaisesRegex(ValueError, 'Unexpected'):
                    runner.validate_environment(PROFILE)

    def test_hash_pending_changed_source_and_symlink_are_rejected(self):
        source = self.root / 'source.py'
        source.write_text('pass\n')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.assertEqual(runner.verify_source(source, digest), digest)
        for bad in (None, 'pending', '0' * 64):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'hash'):
                runner.verify_source(source, bad)
        link = self.root / 'source-alias.py'
        link.symlink_to(source)
        with self.assertRaisesRegex(ValueError, 'symlinked'):
            runner.verify_source(link, digest)

    def test_supervisor_ready_validator_is_not_replaced(self):
        supervisor = runner.load_supervisor(PROFILE)
        self.assertEqual(supervisor.read_ready_report.__module__, 'homing_completion_bounded_supervisor')
        self.assertEqual(supervisor.read_ready_report.__name__, 'read_ready_report')

    def test_source_mismatch_blocks_supervisor_import(self):
        with patch.dict(runner.PINNED_CONTROLS, {'rv1106-at32-link/scripts/bounded_native_supervisor.py': '0' * 64}), \
             patch.object(runner.types, 'ModuleType') as imported:
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                runner.load_supervisor(PROFILE)
            imported.assert_not_called()

    def test_missing_homing_completion_report_rejected(self):
        with self.assertRaises(FileNotFoundError):
            runner.read_homing_completion_report(self.root / 'missing.json')

    def test_fixed_homing_report_wrapper_gate(self):
        # Stub deep validators to test this wrapper's independent fail-closed gate.
        valid = dict(HOMING)
        path = self.root / 'homing-completion.json'
        from types import SimpleNamespace
        validator = SimpleNamespace(validate_final_report=lambda report: None,
                                    validate_artifacts=lambda directory, report: None)
        with patch.object(runner, 'verify_source'), patch.object(runner, 'verified_source_module', return_value=validator):
            path.write_text(json.dumps(valid))
            self.assertEqual(runner.read_homing_completion_report(path), valid)
            for key, bad in [('phase', 'verified_ready'), ('phase', 'verified_cold_release'),
                             ('request_count', 1), ('request_count', 7), ('request_count', 9),
                             ('request_count', True), ('request_count', 10), ('request_count', 8.0),
                             ('request_count', '8'), ('final_export_requested', False),
                             ('final_export_requested', 1), ('launcher_exit_code', True),
                             ('launcher_exit_code', False), ('launcher_exit_code', 0.0),
                             ('launcher_exit_code', '0'), ('launcher_exit_code', 1),
                             ('homing_completed', False), ('homing_completed', None), ('homing_completed', 1),
                             ('natural_release_observed', False), ('natural_release_observed', None),
                             ('natural_release_observed', 1), ('physical_completion_proven', True),
                             ('physical_completion_proven', None), ('physical_completion_proven', 0),
                             ('calibration_completed', True), ('calibration_completed', None),
                             ('calibration_completed', 0)]:
                with self.subTest(key=key, bad=bad):
                    path.write_text(json.dumps(dict(valid, **{key: bad})))
                    with self.assertRaises(ValueError):
                        runner.read_homing_completion_report(path)
            for key in valid:
                missing = dict(valid)
                del missing[key]
                path.write_text(json.dumps(missing))
                with self.subTest(missing=key), self.assertRaises(ValueError):
                    runner.read_homing_completion_report(path)

    def test_old_ten_request_release_report_never_passes_wrapper(self):
        from types import SimpleNamespace
        old = {'phase': 'verified_cold_release', 'request_count': 10,
               'final_export_requested': True, 'launcher_exit_code': 0,
               'virtual_release_proven': True, 'physical_completion_proven': False,
               'calibration_completed': False, 'release_gcode': 'G91\nG1 Z1 F60\nM400\nG90'}
        path = self.root / 'old-cold-release.json'
        path.write_text(json.dumps(old))
        validator = SimpleNamespace(validate_final_report=lambda report: None,
                                    validate_artifacts=lambda directory, report: None)
        with patch.object(runner, 'verify_source'), patch.object(runner, 'verified_source_module', return_value=validator):
            with self.assertRaisesRegex(ValueError, 'eight-request native homing'):
                runner.read_homing_completion_report(path)
        self.assertNotIn('release_gcode', HOMING)
        self.assertFalse(hasattr(runner, 'RELEASE_GCODE'))

    def test_artifact_replay_is_mandatory_and_ordered(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, call
        valid = dict(HOMING)
        path = self.root / 'homing-completion.json'
        path.write_text(json.dumps(valid))
        validator = Mock()
        with patch.object(runner, 'verify_source'), patch.object(runner, 'verified_source_module', return_value=validator):
            self.assertEqual(runner.read_homing_completion_report(path), valid)
        self.assertEqual(validator.mock_calls, [call.validate_final_report(valid),
                                               call.validate_artifacts(path.parent, valid)])
        for failure in (FileNotFoundError('missing artifact'), ValueError('malformed artifact')):
            validator = SimpleNamespace(validate_final_report=Mock(),
                                        validate_artifacts=Mock(side_effect=failure))
            with self.subTest(failure=type(failure).__name__), patch.object(runner, 'verify_source'), \
                 patch.object(runner, 'verified_source_module', return_value=validator):
                with self.assertRaises(type(failure)):
                    runner.read_homing_completion_report(path)
            validator.validate_artifacts.assert_called_once_with(path.parent, valid)
        validator = SimpleNamespace(validate_final_report=lambda report: None)
        with patch.object(runner, 'verify_source'), patch.object(runner, 'verified_source_module', return_value=validator):
            with self.assertRaises(AttributeError):
                runner.read_homing_completion_report(path)

    def test_actual_source_validator_missing_or_raising_artifacts_fails(self):
        # Load actual freshly hash-verified inert Python source, not a mock module.
        profile = self.root / 'source-profile'
        observer = profile / runner.OBSERVER_RELATIVE
        protocol = profile / runner.PROTOCOL_RELATIVE
        observer.parent.mkdir(parents=True)
        protocol.write_text('# inert protocol identity only\n')
        protocol_hash = hashlib.sha256(protocol.read_bytes()).hexdigest()
        path = self.root / 'homing-completion.json'
        path.write_text(json.dumps(HOMING))
        cases = [('', AttributeError),
                 ('def validate_artifacts(directory, report):\n    raise ValueError("inert artifact rejected")\n', ValueError)]
        for artifact_body, failure in cases:
            observer.write_text('def validate_final_report(report):\n    return True\n' + artifact_body)
            observer_hash = hashlib.sha256(observer.read_bytes()).hexdigest()
            with self.subTest(failure=failure.__name__), patch.multiple(runner,
                    EXPECTED_PROFILE=profile, OBSERVER_SHA256=observer_hash, PROTOCOL_SHA256=protocol_hash):
                with self.assertRaises(failure):
                    runner.read_homing_completion_report(path)

    def test_final_report_reloads_verified_source_and_checks_protocol_identity(self):
        profile = self.root / 'source-profile'
        observer = profile / runner.OBSERVER_RELATIVE
        protocol = profile / runner.PROTOCOL_RELATIVE
        observer.parent.mkdir(parents=True)
        protocol.write_text('# inert protocol identity only\n')
        protocol_hash = hashlib.sha256(protocol.read_bytes()).hexdigest()
        observer.write_text('def validate_final_report(report):\n    return True\n'
                            'def validate_artifacts(directory, report):\n    return True\n')
        observer_hash = hashlib.sha256(observer.read_bytes()).hexdigest()
        path = self.root / 'homing-completion.json'
        path.write_text(json.dumps(HOMING))
        with patch.multiple(runner, EXPECTED_PROFILE=profile,
                            OBSERVER_SHA256=observer_hash, PROTOCOL_SHA256=protocol_hash):
            self.assertEqual(runner.read_homing_completion_report(path), HOMING)
            protocol.write_text('# changed protocol identity\n')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                runner.read_homing_completion_report(path)
            protocol.write_text('# inert protocol identity only\n')
            observer.write_text('raise AssertionError("changed source must not execute")\n')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                runner.read_homing_completion_report(path)

    def test_new_launcher_is_mandatory_and_unpinned(self):
        self.assertIn(runner.LAUNCHER_RELATIVE, runner.PINNED_CONTROLS)
        with patch.dict(runner.PINNED_CONTROLS, {runner.LAUNCHER_RELATIVE: None}):
            configuration, _, _ = runner.plan(PROFILE, self.root, 'fixed-contract')
            self.assertTrue(configuration['source_hash_pin_pending'])
        self.assertEqual(configuration['request_count'], 8)
        self.assertNotIn('release_gcode', configuration)
        self.assertEqual(runner.PROTOCOL_RELATIVE, 'rv1106-at32-link/experimental/native-homing-completion/protocol.py')
        self.assertIn('rv1106-at32-link/experimental/native-homing-completion/physical.py', runner.PINNED_CONTROLS)
        self.assertEqual(runner.MANIFEST_SCOPE, 'native-homing-completion-execution-source-closure')
        self.assertEqual(runner.READY_REFERENCE_RELATIVE, 'rv1106-at32-link/experimental/sensor30-observation/evidence/ready-baseline.console.txt')
        self.assertEqual(configuration['observer_work_host_seconds'], 4760)
        self.assertEqual(configuration['shared_stop_seconds'], 45)
        self.assertTrue(configuration['homing_commands'])
        self.assertTrue(configuration['motion_commands'])
        self.assertFalse(configuration['heating_commands'])

    def test_runner_cli_has_no_command_or_budget_override(self):
        for extra in (['--seconds', '999'], ['--command', '/bin/true'], ['--', '/bin/true']):
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()), \
                 patch.object(runner, 'execute') as execute, self.assertRaises(SystemExit):
                runner.main(['--profile', str(PROFILE), '--evidence-dir', str(self.evidence), '--name', 'dummy', *extra])
            execute.assert_not_called()


class CacheIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.configuration, self.run, self.paths = runner.plan(PROFILE, self.root, 'offline-cache')
        self.prefix = Path(self.configuration['python_cache_prefix'])

    def test_prefix_is_derived_absent_and_never_created(self):
        self.assertEqual(self.prefix, self.root / 'offline-cache-python-cache')
        self.assertNotIn(self.run, self.prefix.parents)
        with patch.object(sys, 'pycache_prefix', str(self.prefix)):
            runner.validate_pycache_prefix(self.configuration, require_runtime=True)
        self.assertFalse(self.prefix.exists())
        self.assertEqual(self.configuration['environment']['PYTHONPYCACHEPREFIX'], str(self.prefix))
        self.assertEqual(self.configuration['environment']['PYTHONDONTWRITEBYTECODE'], '1')

    def test_preexisting_file_directory_and_dangling_prefix_rejected(self):
        for kind in ('file', 'directory', 'dangling-link'):
            with self.subTest(kind=kind):
                if kind == 'file':
                    self.prefix.write_text('must preserve')
                elif kind == 'directory':
                    self.prefix.mkdir()
                else:
                    self.prefix.symlink_to(self.root / 'missing')
                try:
                    with self.assertRaisesRegex(ValueError, 'cache prefix'):
                        runner.validate_pycache_prefix(self.configuration, require_runtime=False)
                    self.assertTrue(self.prefix.exists() or self.prefix.is_symlink())
                finally:
                    self.prefix.rmdir() if kind == 'directory' else self.prefix.unlink()

    def test_unexpected_config_runtime_and_environment_prefixes_rejected(self):
        changed = dict(self.configuration, python_cache_prefix=str(self.root / 'arbitrary'))
        with self.assertRaisesRegex(ValueError, 'Unexpected Python cache prefix'):
            runner.validate_pycache_prefix(changed, require_runtime=False)
        with patch.object(sys, 'pycache_prefix', str(self.root / 'arbitrary')):
            with self.assertRaisesRegex(ValueError, 'runtime cache isolation'):
                runner.validate_pycache_prefix(self.configuration, require_runtime=True)
        with patch.dict(os.environ, {'PYTHONPYCACHEPREFIX': str(self.root / 'arbitrary')}):
            with self.assertRaisesRegex(ValueError, 'Unexpected PYTHONPYCACHEPREFIX'):
                runner.validate_pycache_prefix(self.configuration, require_runtime=False)
            with self.assertRaisesRegex(ValueError, 'Unexpected'):
                runner.validate_environment(PROFILE, str(self.prefix))

    def test_matching_environment_prefix_accepted_without_creation(self):
        with patch.dict(os.environ, {'PYTHONPYCACHEPREFIX': str(self.prefix)}):
            runner.validate_environment(PROFILE, str(self.prefix))
            runner.validate_pycache_prefix(self.configuration, require_runtime=False)
        self.assertFalse(self.prefix.exists())

    def test_cached_dummy_cannot_substitute_for_verified_source_bytes(self):
        import importlib.machinery
        import py_compile
        source = self.root / 'pure_dummy.py'
        source.write_text("VALUE = 'cached'\n")
        initial = source.stat()
        # Same-size, same-mtime source gives a deliberately stale valid pyc.
        cache = Path(py_compile.compile(str(source), doraise=True))
        source.write_text("VALUE = 'source'\n")
        os.utime(source, ns=(initial.st_atime_ns, initial.st_mtime_ns))
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        before = cache.read_bytes()
        with patch.object(importlib.machinery.SourceFileLoader, 'get_code',
                          side_effect=AssertionError('Bytecode-capable loader must not be used')):
            actual_runner = runner.verified_source_module(source, digest, 'offline_runner_dummy')
            actual_outer = outer.verified_import(source, digest, 'offline_outer_dummy')
        self.assertEqual(actual_runner.VALUE, 'source')
        self.assertEqual(actual_outer.VALUE, 'source')
        self.assertIsNone(actual_runner.__cached__)
        self.assertIsNone(actual_outer.__cached__)
        self.assertEqual(cache.read_bytes(), before)

    def test_bad_source_hash_never_compiles_or_executes_cached_dummy(self):
        source = self.root / 'pure_dummy.py'
        source.write_text("VALUE = 'source'\n")
        for loader in (runner.verified_source_module, outer.verified_import):
            with self.subTest(loader=loader.__name__), patch('builtins.compile') as compile_source:
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    loader(source, '0' * 64, 'offline_rejected_dummy')
                compile_source.assert_not_called()


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest = self.root / runner.MANIFEST_RELATIVE
        self.manifest.parent.mkdir(parents=True)
        required = set(runner.PINNED_CONTROLS) | {runner.OBSERVER_RELATIVE, runner.PROTOCOL_RELATIVE, runner.READY_REFERENCE_RELATIVE}
        self.files = {}
        for relative in required:
            path = self.root / relative
            path.parent.mkdir(exist_ok=True, parents=True)
            path.write_bytes(('offline placeholder ' + relative).encode())
            self.files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.document = {'schema_version': 1, 'scope': runner.MANIFEST_SCOPE, 'files': self.files}

    def verify(self):
        self.manifest.write_text(json.dumps(self.document))
        digest = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        with patch.object(runner, 'MANIFEST_SHA256', digest):
            return runner.verify_manifest(self.root)

    def test_complete_offline_identity_closure_validates(self):
        result = self.verify()
        self.assertEqual(result['entry_count'], len(self.files))
        self.assertEqual(result['symlink_count'], 0)
        self.assertFalse(result['physical_calibration_proven'])

    def test_missing_required_entry_rejected(self):
        del self.files[runner.OBSERVER_RELATIVE]
        with self.assertRaisesRegex(ValueError, 'omits required'):
            self.verify()

    def test_changed_file_rejected(self):
        (self.root / runner.OBSERVER_RELATIVE).write_text('changed')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.verify()

    def test_escaping_alias_and_circular_paths_rejected(self):
        for relative in ('../outside', '/tmp/outside', 'a/../b', './x',
                         runner.MANIFEST_RELATIVE,
                         'rv1106-at32-link/experimental/native-homing-completion/runner.py'):
            with self.subTest(relative=relative):
                self.files[relative] = '0' * 64
                try:
                    with self.assertRaisesRegex(ValueError, 'path|circular'):
                        self.verify()
                finally:
                    del self.files[relative]

    def test_preserved_symlink_requires_exact_text_and_listed_inside_target(self):
        target = runner.OBSERVER_RELATIVE
        link = self.root / 'link'
        link.symlink_to(target)
        self.document['symlinks'] = {'link': target}
        self.assertEqual(self.verify()['symlink_count'], 1)
        self.document['symlinks']['link'] = runner.PROTOCOL_RELATIVE
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.verify()

    def test_absolute_outside_dangling_and_unlisted_symlinks_fail(self):
        for target in ('/tmp/absolute', '../outside', 'missing', 'unlisted'):
            with self.subTest(target=target):
                (self.root / 'unlisted').write_text('not in manifest')
                link = self.root / 'link'
                link.symlink_to(target)
                self.document['symlinks'] = {'link': target}
                try:
                    with self.assertRaisesRegex(ValueError, 'symlink'):
                        self.verify()
                finally:
                    link.unlink()

    def test_regular_entry_cannot_be_replaced_by_symlink(self):
        path = self.root / runner.OBSERVER_RELATIVE
        path.unlink()
        path.symlink_to(self.root / runner.PROTOCOL_RELATIVE)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.verify()

    def test_exact_preserved_dangling_link_accepts_explicit_absent_target(self):
        link = self.root / 'preserved-link'
        link.symlink_to('preserved-missing')
        self.document['symlinks'] = {'preserved-link': 'preserved-missing'}
        self.document['absent_targets'] = ['preserved-missing']
        result = self.verify()
        self.assertEqual(result['absent_target_count'], 1)
        self.assertTrue(link.is_symlink())
        self.assertFalse(link.exists())
        self.assertFalse((self.root / 'preserved-missing').exists())
        self.document['symlinks']['preserved-link'] = 'changed-missing'
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.verify()

    def test_absent_target_cannot_become_file_directory_or_symlink(self):
        link = self.root / 'preserved-link'
        link.symlink_to('preserved-missing')
        self.document['symlinks'] = {'preserved-link': 'preserved-missing'}
        self.document['absent_targets'] = ['preserved-missing']
        target = self.root / 'preserved-missing'
        for kind in ('file', 'directory', 'symlink'):
            with self.subTest(kind=kind):
                if kind == 'file':
                    target.write_text('unexpected')
                elif kind == 'directory':
                    target.mkdir()
                else:
                    target.symlink_to('another-missing')
                try:
                    with self.assertRaisesRegex(ValueError, 'absent target'):
                        self.verify()
                finally:
                    target.rmdir() if kind == 'directory' else target.unlink()

    def test_absent_targets_require_references_and_disjoint_canonical_paths(self):
        cases = [(['orphan'], 'Orphan'),
                 (['same', 'same'], 'Duplicate'),
                 ([runner.OBSERVER_RELATIVE], 'overlapping'),
                 (['preserved-link'], 'overlapping'),
                 (['../outside'], 'Noncanonical'),
                 (['/tmp/outside'], 'Noncanonical'),
                 (['./alias'], 'Noncanonical'),
                 (['a/../alias'], 'Noncanonical'),
                 ([''], 'Noncanonical'),
                 ('not-a-list', 'Invalid'),
                 ([None], 'Invalid')]
        link = self.root / 'preserved-link'
        link.symlink_to('preserved-missing')
        self.document['symlinks'] = {'preserved-link': 'preserved-missing'}
        for targets, reason in cases:
            with self.subTest(targets=targets):
                self.document['absent_targets'] = targets
                if reason == 'Orphan':
                    # A valid listed absence with no link at all is still rejected.
                    self.document['symlinks'] = {}
                try:
                    with self.assertRaisesRegex(ValueError, reason):
                        self.verify()
                finally:
                    self.document['symlinks'] = {'preserved-link': 'preserved-missing'}

    def test_absent_target_through_symlinked_parent_rejected(self):
        (self.root / 'actual-directory').mkdir()
        (self.root / 'alias-directory').symlink_to('actual-directory', target_is_directory=True)
        (self.root / 'preserved-link').symlink_to('alias-directory/missing')
        self.document['symlinks'] = {'preserved-link': 'alias-directory/missing'}
        self.document['absent_targets'] = ['alias-directory/missing']
        with self.assertRaisesRegex(ValueError, 'Noncanonical'):
            self.verify()

    def test_wrong_manifest_digest_prevents_all_file_hashing(self):
        self.manifest.write_text(json.dumps(self.document))
        with patch.object(runner, 'MANIFEST_SHA256', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                runner.verify_manifest(self.root)


spec = importlib.util.spec_from_file_location('homing_completion_outer_entrypoint', HERE / 'outer_guard.py')
outer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(outer)


class OuterEntrypointTests(unittest.TestCase):
    def test_exact_fixed_command_and_plan_does_not_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = outer.plan(PROFILE, Path(directory), 'offline-plan')
            self.assertEqual(plan['wall_budget_seconds'], 4800)
            self.assertEqual(plan['record'], str(Path(directory) / 'offline-plan-outer.json'))
            self.assertEqual(plan['command'], [outer.HOST_PYTHON, '-I', '-B', '-X', 'pycache_prefix=' + str(Path(directory) / 'offline-plan-python-cache'), str(HERE / 'runner.py'),
                '--profile', str(PROFILE), '--evidence-dir', directory, '--name', 'offline-plan'])
            with patch.object(outer, 'execute') as execute, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(outer.main(['--profile', str(PROFILE), '--evidence-dir', directory,
                    '--name', 'offline-plan', '--plan']), 0)
            execute.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_no_arbitrary_command_record_or_budget(self):
        for extra in (['--wall-seconds', '900'], ['--wall-seconds', '901'],
                      ['--wall-seconds', '1200'], ['--wall-seconds', '1201'],
                      ['--wall-seconds', '4800'], ['--wall-seconds', '1501'],
                      ['--record', '/tmp/other'], ['--', '/bin/true'], ['--command', '/bin/true']):
            with self.subTest(extra=extra), patch.object(outer, 'execute') as execute, \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                outer.main(['--profile', str(PROFILE), '--evidence-dir', '/tmp', '--name', 'dummy', *extra])
            execute.assert_not_called()

    def test_pending_or_mismatched_source_rejected_before_import(self):
        for digest in (None, '0' * 64):
            with self.subTest(digest=digest), patch.object(outer.types, 'ModuleType') as imported:
                with self.assertRaisesRegex(ValueError, 'hash'):
                    outer.verified_import(HERE / 'runner.py', digest, 'never_import')
                imported.assert_not_called()

    def test_current_unfrozen_entrypoint_cannot_launch(self):
        # Pins may later be frozen by the parent; this tests the fail-closed None state explicitly.
        with patch.object(outer, 'OBSERVER_SHA256', None), patch.object(outer, 'verified_import') as imported:
            with self.assertRaisesRegex(ValueError, 'pin pending'):
                outer.execute(PROFILE, Path('/tmp'), 'offline-never-launch')
            imported.assert_not_called()

    def run_dummy(self, body, seconds=3):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / 'guard.json'
            # Directly test the unchanged, hash-verified guard in its own process.
            # Never widen the new outer entrypoint to accept arbitrary commands.
            harness = (
                'import importlib.util,pathlib,hashlib; '
                f'p=pathlib.Path({str(outer.BASE_GUARD)!r}); '
                f'assert hashlib.sha256(p.read_bytes()).hexdigest()=={outer.BASE_GUARD_SHA256!r}; '
                's=importlib.util.spec_from_file_location("offline_guard",p); '
                'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
                f'raise SystemExit(m.supervise({[sys.executable, "-I", "-B", "-c", body]!r}, pathlib.Path({str(record)!r}), {seconds!r}))')
            result = subprocess.run([sys.executable, '-I', '-B', '-c', harness],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8, check=False,
                env={'PATH': runner.HOST_PYTHON_DIR + ':/usr/bin:/bin', 'LANG': 'C.UTF-8'})
            self.assertTrue(record.is_file(), result.stderr.decode())
            data = json.loads(record.read_text())
            self.assertEqual(data['wall_budget_s'], seconds)
            self.assertEqual(data['rss_limit_bytes'], 4 * 1024**3)
            self.assertEqual(data['available_floor_bytes'], 2 * 1024**3)
            self.assertTrue(data['all_descendants_absent'], data)
            self.assertTrue(data['whole_groups_absent'], data)
            return result.returncode, data

    def test_dummy_immediate_exit_clean(self):
        code, data = self.run_dummy('pass')
        self.assertEqual(code, 0, data)
        self.assertTrue(data['passed'])
        self.assertEqual(data['signals'], [])

    def test_dummy_nonzero_never_passes(self):
        code, data = self.run_dummy('raise SystemExit(9)')
        self.assertNotEqual(code, 0)
        self.assertFalse(data['passed'])
        self.assertEqual(data['comparator_exit_code'], 9)

    def test_dummy_detached_child_tracked_killed_reaped(self):
        code, data = self.run_dummy(
            "import subprocess,sys; subprocess.Popen([sys.executable,'-I','-B','-c','import time; time.sleep(4)'], start_new_session=True)")
        self.assertNotEqual(code, 0)
        self.assertFalse(data['passed'])
        self.assertTrue(data['signals'])
        self.assertTrue(data['reaped_adopted_children'])

    def test_dummy_deadline_kills_and_reaps(self):
        start = time.monotonic()
        code, data = self.run_dummy('import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(4)')
        self.assertNotEqual(code, 0)
        self.assertFalse(data['passed'])
        self.assertEqual(data['failure'], 'overall wall deadline')
        self.assertTrue(data['signals'])
        self.assertLess(time.monotonic() - start, 5)


if __name__ == '__main__':
    unittest.main()
