import csv
import importlib.util
import io
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('trace_analysis', Path(__file__).resolve().parents[1] / 'tools/analyze_passive_motor_state.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def fixture():
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=analysis.REQUIRED)
    writer.writeheader()
    for sample, time in enumerate([1.0, 2.0, 3.0]):
        for axis in range(3):
            row = dict.fromkeys(analysis.REQUIRED, 0)
            row.update(virtual_time_s=time, sample=sample, trigger_count=(sample+1)*1000, axis=axis,
                       logical_enable=1, bridge_enabled=1, pwm_reg_00=1, pwm_reg_2c=4000,
                       pwm_reg_18=0x4848 if sample == 0 else 0x6868,
                       pwm_reg_1c=0x4848 if sample == 0 else 0x6868, pwm_reg_20=0x1111,
                       control_angle_u16=sample*16384, physical_relative_mm=sample*2.0,
                       commutation_mode=4)
            writer.writerow(row)
    return stream.getvalue().encode()


class AnalysisTests(unittest.TestCase):
    def test_stages_separate_reference_physical_and_modes(self):
        result = analysis.analyze(fixture(), [('before', 0, 2), ('during', 2, 4)])
        before, during = [item['axes']['0'] for item in result['stages']]
        self.assertEqual(before['samples'], 1)
        self.assertEqual(before['pwm_sample_counts'][0]['configuration']['modes'], [4]*4)
        self.assertEqual(during['pwm_sample_counts'][0]['configuration']['modes'], [6]*4)
        self.assertEqual(during['sampled_physical_delta_mm'], 2)
        self.assertEqual(during['control_angle_changed_intervals'], 1)

    def test_partial_tail_and_sample_are_not_used(self):
        lines = fixture().splitlines(keepends=True)
        rows, coverage = analysis.read_snapshot(b''.join(lines[:-2])+b'3,partial')
        self.assertEqual(len(rows), 6)
        self.assertEqual(coverage['incomplete_sample_rows'], 1)
        self.assertEqual(coverage['partial_tail_bytes'], 9)

    def test_bad_interior_sample_rejected(self):
        lines = fixture().splitlines(keepends=True)
        with self.assertRaises(ValueError):
            analysis.read_snapshot(b''.join(lines[:2]+lines[3:]))

    def test_empty_stage(self):
        self.assertEqual(analysis.analyze(fixture(), [('later', 50, 60)])['stages'][0]['axes']['0'], {'samples': 0})


if __name__ == '__main__':
    unittest.main()
