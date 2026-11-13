"""Offline native integration checks. Shell launchers end at an argv-only stub."""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import run_link
import event_clock_client as ec
from lockstep_coordinator import LockstepCoordinator

VALID = ['--clock-client', 'snapshot', '--shared-mcus', '--clock-coupled',
         '--clock-source', 'qom-deadline', '--clock-lockstep', '--qemu-icount-shift', '0']

class SelectionTests(unittest.TestCase):
    def test_scalar_default(self):
        a = run_link.parser().parse_args([])
        self.assertEqual(a.clock_client, 'scalar')
        self.assertEqual(run_link.execution_args(a), [])
        with patch.object(ec.EventClockClient, 'from_pipes', return_value='scalar') as op:
            self.assertEqual(run_link.open_deadline_client('scalar', 'fifo'), 'scalar')
            op.assert_called_once_with('fifo', timeout=3)

    def test_snapshot_prerequisites(self):
        for field, value in [('shared_mcus', False), ('clock_coupled', False),
                             ('clock_source', 'qom'), ('clock_lockstep', False),
                             ('qemu_icount_shift', None)]:
            a = run_link.parser().parse_args(VALID)
            setattr(a, field, value)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Snapshot client requires'):
                run_link.execution_args(a)
        self.assertEqual(run_link.execution_args(run_link.parser().parse_args(VALID)),
                         ['-icount', 'shift=0,align=off,sleep=off'])

    def test_invalid_snapshot_main_fails_before_launch(self):
        with patch.object(sys, 'argv', ['run_link', '--clock-client', 'snapshot']), \
             patch.object(run_link.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(SystemExit, 'Snapshot client requires'):
                run_link.main()
            launch.assert_not_called()

    def test_snapshot_selection_and_failure_no_fallback(self):
        with patch.object(ec, 'open_clock_pipes', side_effect=ec.ClockError('unsupported snapshot')) as op, \
             patch.object(ec.EventClockClient, 'from_pipes') as scalar:
            with self.assertRaisesRegex(ec.ClockError, 'unsupported snapshot'):
                run_link.open_deadline_client('snapshot', 'fifo', timeout=.1)
            self.assertEqual(op.call_args.args[0].__name__, 'SnapshotClockClient')
            scalar.assert_not_called()
        with self.assertRaises(ValueError):
            run_link.open_deadline_client('invalid', 'fifo')

class PipeTests(unittest.TestCase):
    def test_success_ownership_and_constructor_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            base = pathlib.Path(d) / 'qmp'
            for suffix in ('.out', '.in'): os.mkfifo(str(base) + suffix)
            streams = ec.open_clock_pipes(lambda *s, **kw: s, base)
            self.assertTrue(all(not s.closed for s in streams))
            for s in streams: s.close()
            captured = []
            def fail(*s, **kw):
                captured.extend(s)
                raise ec.ClockError('unsupported')
            with self.assertRaises(ec.ClockError): ec.open_clock_pipes(fail, base)
            self.assertTrue(all(s.closed for s in captured))

    def test_second_endpoint_failure_closes_first(self):
        with tempfile.TemporaryDirectory() as d:
            base = pathlib.Path(d) / 'qmp'
            os.mkfifo(str(base) + '.out')
            pathlib.Path(str(base) + '.in').write_text('not a FIFO')
            captured = []
            original = os.fdopen
            def opening(*a, **kw):
                s = original(*a, **kw); captured.append(s); return s
            with patch.object(ec.os, 'fdopen', side_effect=opening):
                with self.assertRaisesRegex(ec.ClockError, 'not a FIFO'):
                    ec.open_clock_pipes(Mock(), base)
            self.assertEqual(len(captured), 1)
            self.assertTrue(captured[0].closed)

class BoundaryTests(unittest.TestCase):
    def test_scalar_baseline_and_boundary_order(self):
        calls = []
        q = types.SimpleNamespace(call=lambda c: (calls.append(c) or {'running': False}),
                                  now=lambda: (calls.append('now') or 0))
        with patch('lockstep_coordinator.threading.Thread'):
            g = LockstepCoordinator(q, types.SimpleNamespace(time_ns=0), 'unused')
        self.assertEqual(calls, ['stop', 'query-status', 'now'])
        calls.clear(); self.assertEqual(g._paused_now('bad'), 0)
        self.assertEqual(calls, ['query-status', 'now'])
        self.assertEqual((g.slice_ns, g.max_lead_ns), (1000000, 5000000))

    def test_snapshot_baseline_boundary_and_failure(self):
        q = Mock(); q.paused_now.return_value = 0
        with patch('lockstep_coordinator.threading.Thread'):
            g = LockstepCoordinator(q, types.SimpleNamespace(time_ns=0), 'unused')
        q.call.assert_called_once_with('stop'); q.now.assert_not_called()
        self.assertEqual(g._paused_now('bad'), 0)
        q.paused_now.side_effect = ec.ClockError('invalid snapshot')
        with self.assertRaisesRegex(ec.ClockError, 'invalid snapshot'): g._paused_now('bad')
        q.now.assert_not_called(); q.call.assert_called_once_with('stop')

    def test_snapshot_boundary_drift_aborts_before_step(self):
        q = Mock(); q.paused_now.side_effect = [0, 1]
        stepper = Mock(time_ns=0, failed=False)
        with patch('lockstep_coordinator.threading.Thread'):
            g = LockstepCoordinator(q, stepper, 'unused')
        g.run()
        self.assertIn('Paused QEMU clock changed', g.error)
        stepper.step.assert_not_called()
        stepper.pause.assert_called_once_with(force=False)
        self.assertEqual(q.call.call_args_list, [unittest.mock.call('stop'), unittest.mock.call('stop')])
        q.now.assert_not_called()

    def test_scalar_running_boundary_never_reads_clock(self):
        q = types.SimpleNamespace(call=Mock(return_value={'running': True}), now=Mock())
        g = LockstepCoordinator.__new__(LockstepCoordinator); g.qmp = q
        with self.assertRaisesRegex(RuntimeError, 'boundary failure'):
            g._paused_now('boundary failure')
        q.now.assert_not_called()

    def test_native_coordinator_bounds(self):
        g = LockstepCoordinator.__new__(LockstepCoordinator)
        g.q0 = g.r0 = g.max_lead = g.max_lag = 0
        g.max_lead_ns = 5000000
        self.assertEqual(g._check(1000001, 1000000, 0), 1)
        for q, r, lag in [(6000001, 1000000, 0), (0, 1000001, 1000000), (999999, 1000000, 0)]:
            with self.assertRaises(RuntimeError): g._check(q, r, lag)

class LauncherTests(unittest.TestCase):
    def launch_argv(self, native, headless, client, bootstrap=None):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d); scripts = root / 'rv1106-at32-link/scripts'
            scripts.mkdir(parents=True)
            for name in ('run_combined.sh', 'run_native_event_fixture.sh'):
                shutil.copy2(ROOT / 'scripts' / name, scripts / name)
            tests = scripts.parent / 'tests'; tests.mkdir()
            for name in ('assumed-centered-xy-contact.commands', 'nozzle-ntc-tmc.commands'):
                (tests / name).write_text('')
            (root / 'build-deps').mkdir(); (root / 'build-deps/env.sh').write_text('')
            binpath = root / 'bin'; binpath.mkdir()
            stub = binpath / 'python3'
            stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE"\n'); stub.chmod(0o755)
            env = dict(os.environ, PATH=str(binpath) + ':' + os.environ['PATH'],
                       CAPTURE=str(root / 'argv'), DISK='disk', MCU_IMAGE='main', NOZZLE_IMAGE='nozzle')
            # Keep inherited experiment choices from influencing the fixture.
            for key in list(env):
                if key.startswith(('Z_', 'PASSIVE_')) or key in ('GLOBAL_QUANTUM_US', 'NOZZLE_TMC_MODEL', 'ICOUNT_SHIFT', 'HEADLESS_READY_ONLY', 'CLOCK_CLIENT', 'THERMAL_PROFILE', 'RENODE_BOOTSTRAP'):
                    env.pop(key)
            if headless: env['HEADLESS_READY_ONLY'] = '1'
            if client: env['CLOCK_CLIENT'] = client
            if bootstrap: env['RENODE_BOOTSTRAP'] = bootstrap
            command = ['bash', str(scripts / 'run_native_event_fixture.sh'), 'offline'] if native else ['sh', str(scripts / 'run_combined.sh')]
            subprocess.run(command, env=env, check=True, capture_output=True)
            return (root / 'argv').read_text().splitlines()

    def test_bootstrap_forwarding(self):
        for native in (False, True):
            for headless in (False, True):
                for bootstrap in (None, 'segmented'):
                    with self.subTest(native=native, headless=headless, bootstrap=bootstrap):
                        args = self.launch_argv(native, headless, None, bootstrap)
                        values = [args[i+1] for i, x in enumerate(args) if x == '--renode-bootstrap']
                        self.assertTrue(values)
                        self.assertTrue(all(x == (bootstrap or 'legacy') for x in values))

    def test_both_launcher_modes(self):
        for native in (False, True):
            for headless in (False, True):
                for client in (None, 'snapshot'):
                    with self.subTest(native=native, headless=headless, client=client):
                        args = self.launch_argv(native, headless, client)
                        self.assertEqual('--screenshot' in args, not headless)
                        values = [args[i+1] for i, x in enumerate(args) if x == '--clock-client']
                        self.assertTrue(values)
                        self.assertTrue(all(x == (client or 'scalar') for x in values))
                        if native:
                            self.assertEqual(args[args.index('--qemu-icount-shift')+1], '0')

if __name__ == '__main__': unittest.main()
