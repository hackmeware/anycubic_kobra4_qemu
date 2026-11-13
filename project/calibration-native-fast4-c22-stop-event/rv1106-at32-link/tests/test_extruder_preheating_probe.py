"""Offline generation/decoding tests. Never execute a generated ARM probe."""
import hashlib
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('preheating', SCRIPTS / 'decode_extruder_preheating_response.py')
decoder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decoder)
PREFACE = b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'
# Captured before the change from make_grpc_probe.py SHA256 ef057b8a9ecfbe68...
LEGACY = [
    ([], 'c4e9c021c04d94100ec93b5ebc5e10e7d1ea959329763eb638c0b1abbeee6a31', 'ba43777938bf30e742b531650536e8ea62772f444fa326cd75c856b718367c5b'),
    (['--script', 'M105\nM104 S0', '--timeout-seconds', '9'], '6ce6e1061431a5f2ce5c4af20ca050861a7cd6061ef77438e53514c5b8b6b0b3', '9ee7580ae4ebb3f63e17a864590573c6a4870fa148687a9568ebb92f38d52280'),
    (['--method', 'StartPrint'], '9e7060e39d207fdb14a02fb337c78b71176764ca27f850ea42a05637c4748f37', '28d0673a9b205a3af06b2268f56e712b738fc51d069a504e0872a0af968a3504'),
    (['--method', 'StartPrint', '--file-path', '/data/gcodes', '--file-name', 'test.gcode'], '6b9bf05fbf29cb7dc22110d54a4fc89b81bad4672388db061f068da583a88b43', '73493fc0c692e672e4f0b223f4e6577fd9aca81c7164675a9747897a602ac512'),
    (['--method', 'PrinterState'], '8ab7450c7a46da3d7ed9e889120f7eb6b933a670d22b51d97d5ce798e1bfdc4b', '1fddbb6c51a8f6340dee6ee28850057155a540274c5c584b3373be8a8c361c3f'),
]


class ProbeTests(unittest.TestCase):
    def build(self, args):
        with tempfile.TemporaryDirectory() as temp:
            output = pathlib.Path(temp) / 'probe'
            run = subprocess.run([sys.executable, str(SCRIPTS / 'make_grpc_probe.py'), '--output', str(output), *args], capture_output=True, text=True)
            return run, (output.read_bytes() if output.exists() else None), (output.with_suffix('.commands').read_bytes() if output.with_suffix('.commands').exists() else None)

    def test_legacy_byte_identity(self):
        for args, elf_hash, commands_hash in LEGACY:
            with self.subTest(args=args):
                run, elf, commands = self.build(args)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(hashlib.sha256(elf).hexdigest(), elf_hash)
                self.assertEqual(hashlib.sha256(commands).hexdigest(), commands_hash)

    def test_all_bounded_targets(self):
        for target in range(36):
            with self.subTest(target=target):
                run, elf, commands = self.build(['--method', 'ExtruderPreheating', '--temperature-c', str(target)])
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertIn(b'/applink.AppLinkService/ExtruderPreheating', elf)
                self.assertIn(b'127.0.0.1:50051', elf)
                pos = elf.index(PREFACE) + len(PREFACE)
                data = []
                while True:
                    size = int.from_bytes(elf[pos:pos + 3], 'big')
                    kind, flags = elf[pos + 3:pos + 5]
                    payload = elf[pos + 9:pos + 9 + size]
                    if kind == 0:
                        data.append(payload)
                        self.assertEqual(flags, 1)
                        break
                    pos += 9 + size
                expected = bytes([0x10, target]) if target else b''
                self.assertEqual(data, [b'\0' + len(expected).to_bytes(4, 'big') + expected])
                self.assertIn(b'timeout -t 5 /tmp/grpc-probe', commands)

    def test_invalid_targets_do_not_create_artifacts(self):
        for target in ['-1', '36', '200', '4294967295', '35.0', 'abc']:
            with self.subTest(target=target):
                run, elf, commands = self.build(['--method', 'ExtruderPreheating', '--temperature-c', target])
                self.assertNotEqual(run.returncode, 0)
                self.assertIsNone(elf)
                self.assertIsNone(commands)

    def test_target_required(self):
        self.assertNotEqual(self.build(['--method', 'ExtruderPreheating'])[0].returncode, 0)

    def test_target_not_accepted_on_other_methods(self):
        for method in ['RunGcodeScript', 'StartPrint', 'PrinterState']:
            self.assertNotEqual(self.build(['--method', method, '--temperature-c', '35'])[0].returncode, 0)


class ResponseTests(unittest.TestCase):
    def test_empty_response_does_not_claim_actuation(self):
        result = decoder.decode_response(b'')
        self.assertEqual(result, {'error_present': False, 'error_code': 0, 'error_message': '', 'error_reported': False})
        self.assertNotIn('success', result)

    def test_empty_error(self):
        self.assertTrue(decoder.decode_response(b'\x0a\0')['error_present'])
        self.assertFalse(decoder.decode_response(b'\x0a\0')['error_reported'])

    def test_original_exception_code(self):
        result = decoder.decode_response(bytes.fromhex('0a0908ffff031203626164'))
        self.assertEqual(result['error_code'], 65535)
        self.assertEqual(result['error_message'], 'bad')
        self.assertTrue(result['error_reported'])

    def test_message_only_is_not_silently_ignored(self):
        self.assertTrue(decoder.decode_response(bytes.fromhex('0a051203626164'))['error_reported'])

    def test_repeated_nested_error_merges(self):
        result = decoder.decode_response(bytes.fromhex('0a0408ffff030a051203626164'))
        self.assertEqual((result['error_code'], result['error_message']), (65535, 'bad'))

    def test_unknown_fields(self):
        result = decoder.decode_response(bytes.fromhex('10050a06080118042200'))
        self.assertEqual(result['error_code'], 1)

    def test_bad_protobuf_is_rejected(self):
        for value in ['0a', '0a04', '00', '08ff', '0a020801ff', '0a020a00', '0a020001', '0a031201ff', '0a06088080808010', '80808080808080808002', '0b']:
            with self.subTest(value=value), self.assertRaises((ValueError, UnicodeError)):
                decoder.decode_response(bytes.fromhex(value))

    def test_grpc_message(self):
        self.assertFalse(decoder.decode_grpc_message(bytes(5))['error_reported'])
        body = bytes.fromhex('0a0408ffff03')
        self.assertEqual(decoder.decode_grpc_message(b'\0' + len(body).to_bytes(4, 'big') + body)['error_code'], 65535)

    def test_bad_grpc_envelope(self):
        for data in [b'', bytes(4), b'\1' + bytes(4), bytes(5) + b'\0', bytes.fromhex('0000000001')]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                decoder.decode_grpc_message(data)


if __name__ == '__main__':
    unittest.main()
