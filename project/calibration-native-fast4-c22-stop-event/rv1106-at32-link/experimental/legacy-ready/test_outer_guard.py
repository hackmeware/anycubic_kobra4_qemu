"""Offline-only checks of the fixed longer entrypoint; dummy Python children only."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('legacy_ready_guard_entrypoint', HERE / 'outer_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class GuardEntrypointTests(unittest.TestCase):
    def test_explicit_and_default_fixed_900_seconds(self):
        for option in ([], ['--wall-seconds', '900']):
            supervise = Mock(return_value=7)
            with patch.object(guard, 'load_base_guard', return_value=types.SimpleNamespace(supervise=supervise)):
                result = guard.main(['--record', '/tmp/unused-record', *option, '--', 'dummy', 'argument'])
            self.assertEqual(result, 7)
            supervise.assert_called_once_with(['dummy', 'argument'], Path('/tmp/unused-record'), 900)

    def test_arbitrary_and_nonfinite_limits_rejected_without_launch(self):
        for value in ('0', '180', '899', '901', '1800', '-1', 'nan', 'inf', '900.0'):
            with self.subTest(value=value), patch.object(guard, 'load_base_guard') as load:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    guard.main(['--record', '/tmp/unused-record', '--wall-seconds', value, '--', 'dummy'])
                self.assertEqual(caught.exception.code, 2)
                load.assert_not_called()

    def test_empty_command_rejected(self):
        with patch.object(guard, 'load_base_guard') as load:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                guard.main(['--record', '/tmp/unused-record', '--'])
            load.assert_not_called()

    def test_changed_base_guard_rejected_before_import(self):
        with patch.object(guard.Path, 'read_bytes', return_value=b'changed'), patch.object(guard.importlib.util, 'spec_from_file_location') as load:
            with self.assertRaisesRegex(ValueError, 'reviewed outer guard changed'):
                guard.load_base_guard()
            load.assert_not_called()

    def test_base_implementation_and_resource_constants_are_unchanged(self):
        base = guard.load_base_guard()
        self.assertEqual(Path(base.__file__), guard.BASE_GUARD)
        self.assertEqual(base.RSS_LIMIT, 4 * 1024**3)
        self.assertEqual(base.AVAILABLE_FLOOR, 2 * 1024**3)
        self.assertTrue(callable(base.enable_subreaper))
        self.assertTrue(callable(base.reap_children))

    def run_dummy(self, body):
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / 'guard.json'
            result = subprocess.run([sys.executable, '-I', '-B', str(HERE / 'outer_guard.py'),
                '--record', str(record), '--wall-seconds', '900', '--', sys.executable, '-I', '-B', '-c', body],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8, check=False)
            data = json.loads(record.read_text())
            self.assertEqual(data['wall_budget_s'], 900)
            self.assertEqual(data['rss_limit_bytes'], 4 * 1024**3)
            self.assertEqual(data['available_floor_bytes'], 2 * 1024**3)
            self.assertTrue(data['all_descendants_absent'], data)
            self.assertTrue(data['whole_groups_absent'], data)
            return result.returncode, data

    def test_immediately_exiting_dummy_success(self):
        code, record = self.run_dummy('pass')
        self.assertEqual(code, 0, record)
        self.assertTrue(record['passed'])
        self.assertEqual(record['signals'], [])

    def test_failed_dummy_never_passes(self):
        code, record = self.run_dummy('raise SystemExit(9)')
        self.assertNotEqual(code, 0)
        self.assertFalse(record['passed'])
        self.assertEqual(record['comparator_exit_code'], 9)

    def test_detached_dummy_is_tracked_killed_and_reaped(self):
        # The direct dummy exits immediately; only its detached child sleeps.
        code, record = self.run_dummy(
            "import subprocess,sys; subprocess.Popen([sys.executable,'-I','-B','-c','import time; time.sleep(2)'], start_new_session=True)")
        self.assertNotEqual(code, 0)
        self.assertFalse(record['passed'])
        self.assertTrue(record['signals'], record)
        self.assertTrue(record['reaped_adopted_children'], record)


if __name__ == '__main__':
    unittest.main()
