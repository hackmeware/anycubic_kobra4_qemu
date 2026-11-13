"""Offline sensor-point distinction tests, never launch native programs."""
import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

fixture = load('sensor30_test_helpers', HERE / 'test_observer.py')
old = load('unchanged_ambient_protocol', HERE.with_name('ambient-observation') / 'protocol.py')

class Sensor30DistinctionTests(unittest.TestCase):
    def test_native_band_and_unchanged_ambient(self):
        for current in (29, 30, 31):
            temperatures = fixture.p.decode_status(fixture.temperature_payload(current))
            fixture.p.validate_sensor30(temperatures, selected=True)
            with self.assertRaises(ValueError):
                old.validate_ambient(temperatures, selected=True)
        baseline = fixture.p.decode_status(fixture.temperature_payload(25))
        old.validate_ambient(baseline, selected=True)
        for current in (0, 25, 28, 32):
            with self.assertRaises(ValueError):
                fixture.p.validate_sensor30(fixture.p.decode_status(fixture.temperature_payload(current)), selected=True)

    def test_baseline_passive_rejected(self):
        row = fixture.passive_row(10000)
        fixture.observer.validate_passive_row(row)
        for key, value in (('physical_temperature_c', '25'), ('physical_temperature_c', '29.999'),
                           ('published_adc_code', '4023'), ('published_adc_code', '4003'),
                           ('last_heater_duty', '.001'), ('last_fan_duty', '.001'),
                           ('pb8_level', '1'), ('pb9_level', '1'), ('pb9_latch', '1')):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                fixture.observer.validate_passive_row(dict(row, **{key: value}))

    def test_targets_and_bed_remain_strict(self):
        for kwargs in ({'target': 1}, {'bed_target': 1}, {'bed': 30}, {'bed': 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                fixture.p.validate_sensor30(fixture.p.decode_status(fixture.temperature_payload(**kwargs)), selected=True)

    def test_first_default_zero_preserved(self):
        result = fixture.p.verify_capture(fixture.synthetic_capture('GetStatus'), 'GetStatus', fixture.TOKEN)
        self.assertEqual(result['selected_sequence'], 2)
        self.assertEqual(result['messages'][0]['temperatures']['nozzle']['current'], 0)
        self.assertEqual(result['messages'][0]['temperatures']['bed']['current'], 0)
        self.assertEqual(result['selected_temperatures']['nozzle']['current'], 30)

if __name__ == '__main__':
    unittest.main()
