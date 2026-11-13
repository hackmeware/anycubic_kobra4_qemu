"""Inert c6 tests with real c3 cold parsers and synthetic passive file inputs."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
PROFILE = HERE.parents[2]
spec = importlib.util.spec_from_file_location('cold_ui_observer_test', HERE / 'observer.py')
o = importlib.util.module_from_spec(spec)
spec.loader.exec_module(o)
READY = '[1970-01-01 00:00:06.241] [info] [7] Printer is ready at 6.2416.\n'
SENSOR = '[1970-01-01 00:00:07.241] [error] [7] cali_x:Invalid lis2dw12 id\n'


class Fixture:
    """No subprocess: known valid sensor30 row schema from original tests."""
    def __init__(self, root, base, kind):
        self.root, self.base, self.kind = root, base, kind
        self.wall, self.shared, self.sequence = 0., 1_000_000_000, 0
        self.rows, self.waits, self.snapshots = [], [], []
    def monotonic(self):
        return self.wall
    def launch(self, args, env):
        self.args, self.env = args, env
        self.directory = self.root / 'runs' / args[1]
        self.directory.mkdir(parents=True)
        self.console = 'COLD_UI_STARTUP_COMMANDS_DONE\n' + READY
        self.write()
        return self
    def poll(self):
        return None
    def write(self):
        d = self.directory
        data = dict(schema=1, source='renode-shared-mcu', enabled=True,
                    time_went_backwards=False, virtual_time_ns=self.shared,
                    sequence=self.sequence, epoch='synthetic-c5')
        if self.kind == 'backwards' and self.sequence:
            data['virtual_time_ns'] = 0
        (d / 'virtual-time.json').write_text(json.dumps(data))
        values = [str(self.shared // 1000), 'sample', '', '', '0', '0', '4', '4', '0', '0',
                  '30', '4004', 'NTC ZM3863 HNS112HC4570G0', 'none', '0', '0', '0', '0', '0', str(self.sequence)]
        row = dict(zip(self.base.CSV_HEADER.split(','), values))
        if self.sequence and self.kind in ('heat', 'sensor_fault', 'temperature', 'fan', 'adc'):
            key, value = {'heat': ('pb8_latch', '1'), 'sensor_fault': ('sensor_fault', 'short'),
                          'temperature': ('physical_temperature_c', '31'),
                          'fan': ('last_fan_duty', '1'), 'adc': ('published_adc_code', '4003')}[self.kind]
            row[key] = value
        if not self.rows or self.kind != 'stale':
            self.rows.append(row)
        if self.kind != 'missing_thermal':
            (d / 'nozzle-thermal-live.csv').write_text(self.base.CSV_HEADER + '\n' +
                ''.join(','.join(r.values()) + '\n' for r in self.rows))
        if self.sequence:
            if self.kind in ('sensor', 'cleanup_timeout', 'final_heat'):
                self.console += SENSOR
            elif self.kind == 'native_fault':
                self.console += '[1970-01-01 00:00:07.241] [error] [99] MCU failed\n'
            elif self.kind == 'unstructured_fault':
                self.console += 'MCU sensor timeout\n'
            elif self.kind == 'rewrite':
                self.console = 'rewritten\n'
            elif self.kind == 'duplicate_marker':
                self.console += 'COLD_UI_STARTUP_COMMANDS_DONE\n'
        (d / 'console.bin').write_text(self.console)
    def sleep(self, seconds):
        saved = self.directory / o.REPORT_NAME
        if saved.exists():
            self.snapshots.append(json.loads(saved.read_text()))
        self.wall += .1
        self.shared += 300_000_000 if self.kind == 'stale' else 10_000_000
        self.sequence += 1
        if self.kind == 'host_cap':
            self.wall = o.WORK_SECONDS
        elif self.kind == 'shared_cap':
            self.shared = o.SHARED_STOP_NS
        elif self.kind == 'external':
            (self.directory / 'stop-request').write_text('offline external stop\n')
        self.write()
    def wait(self, timeout):
        self.waits.append(timeout)
        if self.kind == 'cleanup_timeout':
            raise subprocess.TimeoutExpired('inert-fixture', timeout)
        if self.kind == 'final_heat':
            self.rows[-1]['pb8_latch'] = '1'
            (self.directory / 'nozzle-thermal-live.csv').write_text(self.base.CSV_HEADER + '\n' +
                ''.join(','.join(r.values()) + '\n' for r in self.rows))
        return 0


class ObserverTests(unittest.TestCase):
    def run_case(self, kind):
        base = o.load_base(PROFILE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = Fixture(root, base, kind)
            with patch.object(o, 'load_base', return_value=base), patch.object(o.subprocess, 'Popen', side_effect=AssertionError('Native launch forbidden')):
                report = o.run(root, 'inert-test', str(root / 'inert-test-python-cache'), fixture)
            self.assertFalse(report['success'])
            self.assertFalse(report['calibration_completed'])
            self.assertFalse(report['homing_completed'])
            self.assertFalse(report['physical_completion_proven'])
            self.assertFalse(report['ready_rpc_verified'])
            self.assertFalse(report['sensor_model_attached'])
            self.assertFalse(report['cold_observation_ready'])
            self.assertEqual(report['request_count'], 0)
            self.assertEqual(report['requests'], [])
            self.assertTrue((fixture.directory / 'stop-request').exists())
            self.assertEqual(json.loads((fixture.directory / o.REPORT_NAME).read_text()), report)
            for forbidden in ('ready-prerequisite.json', 'homing-completion.json', 'console-input.commands'):
                self.assertFalse((fixture.directory / forbidden).exists())
            return report, fixture

    def test_first_lis_error_stops_without_retry_or_success(self):
        report, fixture = self.run_case('sensor')
        self.assertEqual(report['phase'], 'sensor_error_observed')
        self.assertEqual(report['first_lis2dw12_error'], SENSOR.strip())
        self.assertTrue(report['identification_event_observed'])
        self.assertTrue(report['final_sensor_error_present'])
        self.assertEqual(fixture.sequence, 1)
        self.assertTrue(fixture.snapshots[0]['cold_observation_ready'])
        self.assertEqual(fixture.args[0], str(fixture.root / o.LAUNCHER_RELATIVE))
        self.assertEqual(fixture.waits, [8])

    def test_existing_cold_temperature_heater_sensor_adc_rules_remain_strict(self):
        for kind in ('heat', 'sensor_fault', 'temperature', 'fan', 'adc'):
            with self.subTest(kind=kind):
                report, fixture = self.run_case(kind)
                self.assertEqual(report['phase'], 'stopped_on_error')
                self.assertFalse(report['identification_event_observed'])
                self.assertEqual(fixture.sequence, 1)

    def test_unknown_native_faults_stop_immediately(self):
        for kind in ('native_fault', 'unstructured_fault'):
            with self.subTest(kind=kind):
                report, fixture = self.run_case(kind)
                self.assertEqual(report['phase'], 'stopped_on_error')
                self.assertIn('fault', report['error'].lower())
                self.assertEqual(fixture.sequence, 1)

    def test_thermal_missing_stale_console_and_clock_changes_stop(self):
        for kind in ('missing_thermal', 'stale', 'rewrite', 'backwards', 'duplicate_marker'):
            with self.subTest(kind=kind):
                report, fixture = self.run_case(kind)
                self.assertEqual(report['phase'], 'stopped_on_error')
                self.assertLessEqual(fixture.sequence, 1)

    def test_host_shared_and_external_stop_reserve_cleanup(self):
        for kind in ('host_cap', 'shared_cap', 'external'):
            with self.subTest(kind=kind):
                report, fixture = self.run_case(kind)
                self.assertEqual(report['phase'], 'external_stop' if kind == 'external' else 'stopped_on_error')
                if kind != 'external':
                    self.assertIn('budget', report['error'])
                self.assertEqual(fixture.waits, [8])

    def test_cleanup_timeout_is_explicit_and_not_retried(self):
        report, fixture = self.run_case('cleanup_timeout')
        self.assertTrue(report['cleanup_timeout'])
        self.assertEqual(fixture.waits, [8])
        self.assertNotIn('launcher_exit_code', report)

    def test_final_thermal_revalidation_catches_changed_bytes(self):
        report, _ = self.run_case('final_heat')
        self.assertIn('truncated/rewritten', report['final_observation_error'])

    def test_source_pin_rejects_changed_dependency_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / o.BASE_RELATIVE
            path.parent.mkdir(parents=True)
            path.write_text('raise AssertionError("must not execute")\n')
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                o.load_base(root)

    def test_runtime_has_no_console_monitor_rpc_gcode_or_vnc_writes(self):
        tree = ast.parse((HERE / 'observer.py').read_bytes())
        attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        for absent in ('append_once', 'commands', 'build', 'packet', 'sendall', 'connect', 'request_packet'):
            self.assertNotIn(absent, attrs)
        names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        self.assertNotIn('validate_final_report', names)
        self.assertNotIn('validate_artifacts', names)

    def test_fixed_environment_matches_cold_contract(self):
        env = o.fixed_environment(PROFILE, '/tmp/inert-test-python-cache')
        self.assertEqual(env['RUN_SECONDS'], '4768')
        self.assertEqual(env['THERMAL_PROFILE'], 'none')
        self.assertEqual(env['NATIVE_NOZZLE_HEATER'], '0')
        self.assertEqual(env['PASSIVE_MOTOR_TRACE'], '0')
        self.assertEqual(env['PASSIVE_NOZZLE_TRACE'], '1')
        self.assertEqual(env['CLOCK_CLIENT'], 'scalar')
        self.assertEqual(env['RENODE_BOOTSTRAP'], 'legacy')


class WlanClassificationTests(unittest.TestCase):
    def setUp(self):
        self.base = o.load_base(PROFILE)
        self.reconnect = "[1970-01-01 00:00:14.817] [error] [129] exec command 'wpa_cli -i wlan0 reconnect' failed, "
        self.status = "[1970-01-01 00:00:14.825] [error] [129] exec command 'wpa_cli -i wlan0 status' failed, "
        self.reason = o.WLAN_MISSING_CONTROL

    def review(self, text, final=True):
        review = o.UiNativeReview(self.base)
        result = review.observe(text, final=final)
        return result, review

    def test_entire_unmodified_c5_console_has_ready_and_exactly_two_classifications(self):
        path = HERE / 'evidence/c5-console.bin'
        raw = path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), '15e9cd0fb93f29252508f5578805534117bd801bfacba5109ccf9ee7159afcf9')
        text = raw.decode('utf-8', errors='replace')
        with self.assertRaisesRegex(ValueError, 'Unclassified native fault/error'):
            self.base.NativeReview().observe(text, final=True)
        ready, review = self.review(text)
        self.assertTrue(ready)
        classified = [row for row in review.occurrences if row['classification'].startswith('exact c5 absent wlan0')]
        self.assertEqual([row['line'] for row in classified], [self.reconnect, self.status])
        for row in classified:
            self.assertEqual(row['corroborating_line'], self.reason)
            self.assertEqual(row['line_number_1based'], row['corroborating_line_number_1based'] + 1)
            self.assertIn(row['raw_line'], text)
            self.assertIn(row['corroborating_raw_line'], text)
        self.assertEqual(path.read_bytes(), raw)
        historical = json.loads((HERE / 'evidence/c5-ui-resonance-identification.json').read_text())
        self.assertFalse(historical['success'])
        self.assertEqual(historical['phase'], 'stopped_on_error')
        self.assertFalse(historical['calibration_completed'])

    def test_exact_pair_and_exact_timestamp_duplicate_are_classified(self):
        text = READY + self.reason + '\n' + self.reconnect + '\n' + self.reconnect + '\n'
        ready, review = self.review(text)
        self.assertTrue(ready)
        self.assertEqual(len(review.occurrences), 2)
        self.assertEqual(review.occurrences[0]['corroborating_line_number_1based'], 2)
        self.assertEqual(review.occurrences[1]['corroborating_line_number_1based'], 2)

    def test_wrong_command_interface_source_severity_and_punctuation_fail(self):
        variants = [self.reconnect.replace('reconnect', 'disconnect'),
                    self.reconnect.replace('wlan0', 'wlan1'),
                    self.reconnect.replace('[129]', '[130]'),
                    self.reconnect.replace('[error]', '[fatal]'),
                    self.reconnect.replace('[error]', '[info]'),
                    self.reconnect.rstrip(),
                    self.reconnect + 'permission denied',
                    self.reconnect.replace('wpa_cli -i', 'wpa_cli -p /tmp -i')]
        for line in variants:
            with self.subTest(line=line), self.assertRaises(ValueError):
                self.review(READY + self.reason + '\n' + line + '\n')

    def test_missing_nonadjacent_or_other_reason_fails(self):
        variants = ['', self.reason + '\nnot adjacent\n',
                    self.reason.replace('No such file or directory', 'Permission denied') + '\n',
                    self.reason.replace('wlan0', 'wlan1') + '\n',
                    self.reason.replace('  error:', ' error:') + '\n']
        for before in variants:
            with self.subTest(before=before), self.assertRaises(ValueError):
                self.review(READY + before + self.reconnect + '\n')

    def test_new_timestamp_without_new_corroboration_is_not_a_duplicate(self):
        text = READY + self.reason + '\n' + self.reconnect + '\n' + self.reconnect.replace('14.817', '15.817') + '\n'
        with self.assertRaisesRegex(ValueError, 'Uncorroborated'):
            self.review(text)

    def test_unknown_native_fault_is_not_filtered_by_known_wlan_pair(self):
        prefix = READY + self.reason + '\n' + self.reconnect + '\n'
        for tail in ('[1970-01-01 00:00:15.000] [error] [129] wifi unknown failure\n',
                     '[1970-01-01 00:00:15.000] [error] [7] MCU failed\n',
                     'wpa_cli error: permission denied\n',
                     'Failed to connect to non-global ctrl_ifname: wlan0  error: Permission denied\n'):
            with self.subTest(tail=tail), self.assertRaises(ValueError):
                self.review(prefix + tail)

    def test_partial_final_error_cannot_be_classified_as_complete(self):
        with self.assertRaisesRegex(ValueError, 'Unterminated'):
            self.review(READY + self.reason + '\n' + self.reconnect)

    def test_startup_initializes_ui_stdout_before_launch_and_tail(self):
        commands = (HERE / 'native-ui-startup.commands').read_text()
        text = (HERE / 'native-ui-startup-gate.sh').read_text()
        initialize = ': > /data/ui.stdout\n'
        launch = '/app/bin/avata_ui -c /app/etc/avata_ui.cfg >/data/ui.stdout 2>&1 &'
        tail = 'tail -n +1 -f "$D/avata_main.log" /data/main.stdout /data/ui.stdout &'
        self.assertEqual(text.count(initialize), 1)
        self.assertLess(text.index(initialize), text.index(tail))
        self.assertLess(text.index(tail), text.index('while :; do'))
        self.assertLess(text.index('C18_UI_BACKEND_VERIFIED'), text.index(launch))
        self.assertEqual(text.count(launch), 1)
        self.assertEqual(commands.count('/bin/sh /tmp/c23-native-ui-startup.sh'), 1)



if __name__ == '__main__':
    unittest.main()
