"""Offline structural/validation tests only. No emulator is launched."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bootstrap_compare', HERE/'compare.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

class OfflineTests(unittest.TestCase):
    def test_legacy_trailer(self):
        text='setup\nemulation RunFor "1"\nmach set "main"\nsysbus.timeTelemetry PublishStep "/tmp/test" 0\n'
        self.assertEqual(c.prefix_only(text), ['setup'])
        for bad in [text+'start\n', text.replace('"1"', '"0.02"'), text+text]:
            with self.assertRaises(ValueError): c.prefix_only(bad)

    def test_synthetic_setup_has_no_vendor_firmware(self):
        with tempfile.TemporaryDirectory(dir=HERE) as t:
            lines, boards = c.setup('synthetic', Path(t))
            self.assertEqual(boards, ['main'])
            self.assertFalse(any('LoadBinary' in x or 'RunFor' in x or 'start' == x for x in lines))
            self.assertIn('emulation SetGlobalQuantum "0.000001"', lines)

    def test_setup_failure_preserves_early_record(self):
        with tempfile.TemporaryDirectory(dir=HERE) as t:
            out=Path(t)/'leg'
            with patch.object(c, 'setup', side_effect=ValueError('fixture failure')):
                record=c.run_arm('native-prefix', 'legacy', out, c.time.monotonic()+10)
            self.assertFalse(record['passed'])
            self.assertFalse(record['vendor_firmware_ran'])
            self.assertIn('fixture failure', json.loads((out/'result.json').read_text())['error'])

    def test_packaged_reference_integrity_and_relocation(self):
        metadata, reference = c.load_reference()
        old = metadata['original_root']
        output = Path('/relocated/evidence/leg')
        root = Path('/relocated/profile')
        text = c.relocate_reference(reference['shared-link.resc.txt'], metadata, output, root)
        self.assertNotIn(old+'/', text)
        self.assertNotIn(metadata['original_executor_root']+'/', text)
        self.assertIn(str(root/'inputs/mcu.bin'), text)
        self.assertIn(str(output/'shared-models/shared-load.resc'), text)
        # Prefix lookalikes are not part of authorized path relocation.
        self.assertEqual(c.relocate_reference(old+'-other/file', metadata, output, root), old+'-other/file')
        import hashlib
        for name, digest in metadata['files_sha256'].items():
            self.assertEqual(hashlib.sha256((c.HERE/'reference'/name).read_bytes()).hexdigest(), digest)

    def test_original_ready_profile_generates_without_runtime(self):
        with tempfile.TemporaryDirectory(dir=HERE) as t:
            original_read = Path.read_text
            def without_unbundled_runs(path, *args, **kwargs):
                if '/runs/' in str(path):
                    raise AssertionError('Attempted to read unbundled old run: '+str(path))
                return original_read(path, *args, **kwargs)
            with patch.object(Path, 'read_text', without_unbundled_runs):
                lines, boards=c.setup('native-prefix', Path(t), c.time.monotonic()+20)
            self.assertEqual(boards, ['main','nozzle','motor'])
            self.assertFalse(any('RunFor' in x or 'PublishStep' in x for x in lines))
            self.assertFalse(any('BoundaryProbe' in x or 'synthetic-z' in x or 'accelerated-functional' in x for x in lines))
            self.assertEqual(sum('LoadBinary' in x for x in lines), 3)

if __name__ == '__main__': unittest.main()
