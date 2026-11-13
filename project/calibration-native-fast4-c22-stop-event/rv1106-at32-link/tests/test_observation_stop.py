import importlib.util
import pathlib
import tempfile
import unittest

path=pathlib.Path(__file__).resolve().parents[1]/'scripts/run_link.py'
spec=importlib.util.spec_from_file_location('run_link_stop_test',path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ObservationStopTests(unittest.TestCase):
    def test_default_is_disabled(self):
        self.assertIsNone(module.parser().parse_args([]).stop_request)
        self.assertFalse(module.observation_stop_requested(None))

    def test_opt_in_path(self):
        self.assertEqual(module.parser().parse_args(['--stop-request','stop']).stop_request,pathlib.Path('stop'))

    def test_only_existing_signal_stops_without_consuming(self):
        with tempfile.TemporaryDirectory() as d:
            signal=pathlib.Path(d)/'stop'
            self.assertFalse(module.observation_stop_requested(signal))
            signal.write_bytes(b'Fixture fault observed\n')
            self.assertTrue(module.observation_stop_requested(signal))
            self.assertEqual(signal.read_bytes(),b'Fixture fault observed\n')

if __name__=='__main__':unittest.main()
