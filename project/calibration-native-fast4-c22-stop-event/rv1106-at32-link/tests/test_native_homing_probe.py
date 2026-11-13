"""Offline generation only. Never execute the generated ARM probes or commands."""
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'rv1106-at32-link/scripts/make_grpc_probe.py'
BASELINE = ROOT / 'evidence/homing-y-probe/baseline.json'
PREFACE = b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'


class TestHoming(unittest.TestCase):
    def run_probe(self, args):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / 'probe'
            result = subprocess.run(
                [sys.executable, str(SCRIPT), '--output', str(output), *args],
                capture_output=True, text=True)
            commands = output.with_suffix('.commands')
            return (result, output.read_bytes() if output.exists() else None,
                    commands.read_bytes() if commands.exists() else None)

    def test_exact_x_and_y_requests(self):
        for axis, hex_body in [('X', '00000000030a0158'), ('Y', '00000000030a0159')]:
            with self.subTest(axis=axis):
                result, data, commands = self.run_probe(['--method', 'Homing', '--homing-axis', axis])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(b'/applink.AppLinkService/Homing', data)
                self.assertIn(b'127.0.0.1:50051', data)
                position = data.index(PREFACE) + len(PREFACE)
                messages = []
                for _ in range(3):
                    size = int.from_bytes(data[position:position + 3], 'big')
                    kind, flags = data[position + 3:position + 5]
                    stream = int.from_bytes(data[position + 5:position + 9], 'big')
                    payload = data[position + 9:position + 9 + size]
                    self.assertEqual(len(payload), size)
                    position += 9 + size
                    if kind == 0:
                        self.assertEqual((flags, stream), (1, 1))
                        messages.append(payload)
                self.assertEqual(messages, [bytes.fromhex(hex_body)])
                self.assertIn(b'timeout -t 5 /tmp/grpc-probe', commands)

    def test_existing_42_cases_are_byte_identical(self):
        for case in json.loads(BASELINE.read_text())['cases']:
            with self.subTest(args=case['args']):
                result, data, commands = self.run_probe(case['args'])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(hashlib.sha256(data).hexdigest(), case['elf_sha256'])
                self.assertEqual(hashlib.sha256(commands).hexdigest(), case['commands_sha256'])

    def assert_rejected_without_artifacts(self, args):
        result, data, commands = self.run_probe(args)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(data)
        self.assertIsNone(commands)

    def test_missing_axis_rejected(self):
        self.assert_rejected_without_artifacts(['--method', 'Homing'])

    def test_other_axis_values_rejected(self):
        for axis in ['', 'Z', 'x', 'y', 'z', 'XY', 'XYZ', 'ALL', 'all', ' X', 'Y ', 'G28 Y']:
            with self.subTest(axis=axis):
                self.assert_rejected_without_artifacts(['--method', 'Homing', '--homing-axis', axis])

    def test_axis_rejected_on_every_other_method(self):
        for method in ['RunGcodeScript', 'StartPrint', 'PrinterState', 'ExtruderPreheating']:
            for axis in ['X', 'Y']:
                with self.subTest(method=method, axis=axis):
                    self.assert_rejected_without_artifacts(['--method', method, '--homing-axis', axis])

    def test_temperature_rejected_for_homing(self):
        for axis in ['X', 'Y']:
            with self.subTest(axis=axis):
                self.assert_rejected_without_artifacts(['--method', 'Homing', '--homing-axis', axis, '--temperature-c', '0'])


if __name__ == '__main__':
    unittest.main()
