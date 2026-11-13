#!/usr/bin/env python3
"""Offline selection/ordering/default-identity checks; never execute firmware."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'rv1106-at32-link/scripts'))
from run_link import parser, execution_args
from shared_mcu import prepare
import z_probe_selection as z


def arguments(directory, selected=True):
    a = parser().parse_args([])
    a.shared_mcus = True
    a.motor_plant = 'electromechanical-driver'
    a.z_probe_profile = z.PROFILE if selected else 'none'
    a.mcu_image = ROOT / 'inputs/mcu.bin'
    a.nozzle_image = ROOT / 'inputs/nozzle.bin'
    a.motor_image = ROOT / 'inputs/motor.bin'
    a.mcu_base = a.nozzle_base = 0x08004000
    a.log_dir = directory / 'logs'
    a.log_dir.mkdir(exist_ok=True)
    return a


def tree(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob('*') if p.is_file()}


class ZProfileTests(unittest.TestCase):
    def test_default_byte_identity_against_pre_change(self):
        before = ROOT / 'evidence/synthetic-z-profile-integration/before/shared_mcu.py'
        old = types.ModuleType('before_z_selection')
        old.__file__ = str(ROOT / 'rv1106-at32-link/scripts/shared_mcu.py')
        exec(compile(before.read_text(), old.__file__, 'exec'), old.__dict__)
        for plant, tmc in [('electrical', 'fixed'), ('electromechanical-driver', 'fixed'), ('electromechanical-driver', 'autobaud')]:
            with self.subTest(plant=plant, tmc=tmc), tempfile.TemporaryDirectory() as folder:
                d = Path(folder)
                a = arguments(d, selected=False)
                a.motor_plant, a.nozzle_tmc_model = plant, tmc
                setup = ['emulation SetGlobalQuantum "0.000001"'] if tmc == 'autobaud' else []
                old.prepare(a, d, [], setup)
                baseline = tree(d)
                shutil.rmtree(d / 'shared-models')
                shutil.rmtree(d / 'logs')
                (d / 'logs').mkdir()
                prepare(a, d, [], setup)
                self.assertEqual(baseline, tree(d))

    def test_explicit_composition_and_provenance(self):
        core = ROOT / 'motor-renode/peripherals/GenericStepperElectromechanical.cs'
        original = core.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            d = Path(folder)
            a = arguments(d)
            a.nozzle_tmc_model = 'autobaud'
            a.z_baseline_counts = 32
            a.z_bed_relative_mm = -12.5
            script, _ = prepare(a, d, [], ['emulation SetGlobalQuantum "0.000001"'])
            text = script.read_text()
            generated = d / 'shared-models'
            self.assertIn('Cs1237NativeGpio', (generated / 'nozzle/platforms/nozzle-f1-provisional.repl').read_text())
            loader = (generated / 'nozzle/scripts/load.resc').read_text()
            self.assertLess(loader.index('Cs1237NativeGpio.cs'), loader.index('LoadPlatformDescription'))
            self.assertLess(text.index('/sensor.repl'), text.index('zBedContactFixture SetEnabled true'))
            self.assertLess(text.index('zBedContactFixture SetEnabled true'), text.index('/source.repl'))
            self.assertLess(text.index('zForceSource Register'), text.index('/binding.repl'))
            self.assertLess(text.index('/binding.repl'), text.index('syntheticZProbe SelectDestinationPin'))
            self.assertLess(text.index('syntheticZProbe SelectDestinationPin'), text.index('syntheticZProbe SelectSourcePin'))
            self.assertLess(text.index('syntheticZProbe SelectSourcePin'), text.index('zProbeEdges Observe'))
            self.assertLess(text.index('zProbeEdges Start'), text.index('emulation RunFor'))
            self.assertEqual(text.count('syntheticZProbe SelectSourcePin'), 1)
            self.assertIn('syntheticBaseline: 32', (generated / 'z-probe-profile/sensor.repl').read_text())
            self.assertIn('baselineCounts: 32', (generated / 'z-probe-profile/fixture.repl').read_text())
            self.assertIn('bedRelativeMillimeters: -12.5', (generated / 'z-probe-profile/fixture.repl').read_text())
            profile = json.loads((a.log_dir / 'shared-profile.json').read_text())
            self.assertEqual(profile['nozzle_tmc_model']['selection'], 'autobaud')
            self.assertEqual(profile['z_probe_profile']['maximum_state_age_ns'], 100000)
            self.assertEqual(profile['z_probe_profile']['maximum_producer_lead_ns'], 1000)
            self.assertFalse(profile['z_probe_profile']['physical_timing_fidelity'])
            self.assertNotIn('PerformanceInMips', text)
            manifest = json.loads((generated / 'manifest.json').read_text())
            for entry in manifest:
                self.assertEqual(entry['generated_sha256'], hashlib.sha256((generated / entry['generated']).read_bytes()).hexdigest())
            extended = (generated / 'motor/peripherals/GenericStepperElectromechanical.cs').read_text()
            self.assertEqual(extended.count('public void DisableContact()'), 1)
            self.assertEqual(extended.count('public void DisableRelativeContact(int axis)'), 1)
        self.assertEqual(core.read_bytes(), original)

    def test_required_model_and_explicit_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            a = arguments(Path(folder))
            a.shared_mcus = False
            with self.assertRaises(ValueError): execution_args(a)
            a.shared_mcus = True
            a.motor_plant = 'electrical'
            with self.assertRaises(ValueError): execution_args(a)
            a.z_probe_profile = 'none'
            a.z_counts_per_n = 10000
            with self.assertRaises(ValueError): execution_args(a)
            a.z_probe_profile = 'unknown'
            with self.assertRaises(ValueError): z.validate(a)

    def test_invalid_parameters(self):
        with tempfile.TemporaryDirectory() as folder:
            for key, value in [('bed_relative_mm', float('nan')), ('opposite_stop_relative_mm', float('inf')),
                               ('bed_relative_mm', 253), ('stiffness_n_per_mm', 0), ('damping_ns_per_mm', -1),
                               ('baseline_counts', 8388608), ('counts_per_n', 0), ('signal_polarity', 0),
                               ('history_capacity', 1), ('query_trace_rows', 1000001)]:
                a = arguments(Path(folder))
                setattr(a, 'z_' + key, value)
                with self.subTest(key=key), self.assertRaises(ValueError): z.validate(a)

    def test_setup_rejects_missing_quantum_execution_clocks_and_ownership(self):
        with tempfile.TemporaryDirectory() as folder:
            d = Path(folder)
            a = arguments(d)
            for bad in [[], ['emulation SetGlobalQuantum "0.00001"'],
                        ['emulation SetGlobalQuantum "0.000001"', 'emulation RunFor "0.01"'],
                        ['emulation SetGlobalQuantum "0.000001"', 'start'],
                        ['emulation SetGlobalQuantum "0.000001"', 'cpu PerformanceInMips 8'],
                        ['emulation SetGlobalQuantum "0.000001"', 'sysbus.electromechanicalPlant ConfigureRelativeContact 2 -10 252 1 1'],
                        ['emulation SetGlobalQuantum "0.000001"', 'include @' + str(ROOT / 'nozzle-renode/experimental/cs1237-native/Cs1237NativeGpio.cs')]]:
                with self.subTest(bad=bad), self.assertRaises(ValueError): z.require_setup(ROOT, a, [], bad, [])
            nested = d / 'bad.resc'
            nested.write_text('emulation SetGlobalQuantum "0.00001"\n')
            with self.assertRaises(ValueError): z.require_setup(ROOT, a, [], ['emulation SetGlobalQuantum "0.000001"', 'include @' + str(nested)], [])

    def test_default_has_no_final_commands(self):
        a = parser().parse_args([])
        self.assertEqual(z.final_commands(a), '')


if __name__ == '__main__':
    unittest.main()
