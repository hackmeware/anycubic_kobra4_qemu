#!/usr/bin/env python3
"""No-firmware generation regression for explicit accelerated functional profiles."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'rv1106-at32-link/scripts'), str(Path(__file__).resolve().parent)]
from run_link import parser, execution_args
from shared_mcu import prepare
from test_z_probe_profile import arguments, tree
from test_thermal_profile import MAIN, NOZZLE
import thermal_profile_selection as baseline
import accelerated_thermal_profile_selection as accelerated


class AcceleratedThermalTests(unittest.TestCase):
    def test_exact_legacy_generation_bytes_including_slow_thermal(self):
        before = ROOT / accelerated.EXPERIMENT / 'integration-plan/before/rv1106-at32-link/scripts/shared_mcu.py'
        old = types.ModuleType('before_accelerated_selection')
        old.__file__ = str(ROOT / 'rv1106-at32-link/scripts/shared_mcu.py')
        exec(compile(before.read_text(), old.__file__, 'exec'), old.__dict__)
        cases = [('electrical', 'fixed', False, 'none'), ('electromechanical-driver', 'fixed', False, 'none'),
                 ('electromechanical-driver', 'autobaud', True, 'none'),
                 ('electromechanical-driver', 'fixed', False, baseline.PROFILE),
                 ('electromechanical-driver', 'autobaud', True, baseline.PROFILE)]
        for plant, tmc, z, thermal in cases:
            with self.subTest(plant=plant, tmc=tmc, z=z, thermal=thermal), tempfile.TemporaryDirectory() as folder:
                d = Path(folder); args = arguments(d, selected=z)
                args.motor_plant, args.nozzle_tmc_model, args.thermal_profile = plant, tmc, thermal
                old.prepare(args, d, MAIN, NOZZLE)
                expected = tree(d)
                shutil.rmtree(d / 'shared-models'); shutil.rmtree(d / 'logs'); (d / 'logs').mkdir()
                prepare(args, d, MAIN, NOZZLE)
                self.assertEqual(expected, tree(d))

    def test_explicit_fast_composition_metadata_and_exclusive_writers(self):
        original = copy.deepcopy(baseline.PARAMETERS)
        for profile, factor in accelerated.PROFILES.items():
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as folder:
                d = Path(folder); args = arguments(d)
                args.nozzle_tmc_model = 'autobaud'; args.thermal_profile = profile
                script, _ = prepare(args, d, MAIN, NOZZLE)
                text = script.read_text()
                self.assertEqual(text.count('/thermal-profile/nozzle.repl'), 1)
                self.assertEqual(text.count('/thermal-profile/bed.repl'), 1)
                self.assertNotIn('virtual-bed-ntc.resc', text)
                self.assertNotIn('virtual-nozzle-recovered-ntc.resc', text)
                self.assertLess(text.index('passiveBedThermalObserver Start'), text.index('RunFor'))
                self.assertLess(text.index('passiveNozzleThermalObserver Start'), text.index('RunFor'))
                info = json.loads((args.log_dir / 'thermal-profile.json').read_text())
                shared = json.loads((args.log_dir / 'shared-profile.json').read_text())
                self.assertEqual(info, shared['thermal_profile'])
                self.assertEqual(info['selection'], profile)
                self.assertEqual(info['functional_acceleration_factor'], factor)
                self.assertTrue(info['unrealistic_dynamics'])
                self.assertFalse(info['real_pid_validation'])
                self.assertFalse(info['automatic_factor_fallback'])
                self.assertEqual(info['emulation_clock_scale'], 1)
                self.assertEqual(info['parameters']['nozzle']['heat_capacity_j_per_k'], 20 / factor)
                self.assertEqual(info['parameters']['bed']['heat_capacity_j_per_k'], 600 / factor)
                self.assertFalse(info['parameters']['pb9_thermal_connection'])
                self.assertEqual(info['parameters']['update_us'], 10000)
                self.assertEqual(shared['z_probe_profile']['maximum_state_age_ns'], 100000)
                self.assertEqual(shared['z_probe_profile']['maximum_producer_lead_ns'], 1000)
                self.assertEqual(shared['nozzle_tmc_model']['selection'], 'autobaud')
                self.assertEqual(info['baseline_integration_helper_sha256'], baseline.sha(ROOT / 'rv1106-at32-link/scripts/thermal_profile_selection.py'))
                self.assertEqual(info['integration_helper_sha256'], baseline.sha(ROOT / 'rv1106-at32-link/scripts/accelerated_thermal_profile_selection.py'))
                for entry in json.loads((d / 'shared-models/manifest.json').read_text()):
                    self.assertEqual(entry['generated_sha256'], baseline.sha(d / 'shared-models' / entry['generated']))
                for heater in ('nozzle', 'bed'):
                    generated = d / 'shared-models/thermal-profile' / (heater + '.repl')
                    self.assertIn('heatCapacityJoulesPerKelvin: ' + format((20 if heater == 'nozzle' else 600) / factor, '.12g'), generated.read_text())
                    self.assertNotIn('AT32.', generated.read_text())
                self.assertEqual(accelerated.final_commands(args), baseline.final_commands(accelerated.baseline_args(args)))
                self.assertEqual(args.thermal_profile, profile)
        self.assertEqual(baseline.PARAMETERS, original)

    def test_all_legacy_constraints_apply_to_fast(self):
        with tempfile.TemporaryDirectory() as folder:
            args = arguments(Path(folder)); args.thermal_profile = 'accelerated-functional-4x'
            args.shared_mcus = False
            with self.assertRaises(ValueError): execution_args(args)
            args.shared_mcus = True; args.motor_plant = 'electrical'
            with self.assertRaises(ValueError): execution_args(args)
            args.motor_plant = 'electromechanical-driver'; args.mcu_hext = 12000000
            with self.assertRaises(ValueError): execution_args(args)
            args.mcu_hext = None
            for line in ['emulation SetGlobalQuantum "0.00001"', 'sysbus.virtualNozzleNTC SetDutyCycle 1',
                         'sysbus.virtualBedNTC ColdReset', 'sysbus.adc1 SetChannelValue 8 3444',
                         'include @scripts/native-nozzle-heater-binding.resc']:
                with self.subTest(line=line), self.assertRaises(ValueError):
                    accelerated.prepare_setup(ROOT, args, MAIN, NOZZLE + [line], [])
            with self.assertRaises(ValueError): accelerated.prepare_setup(ROOT, args, MAIN, NOZZLE[:-1], [])
            with self.assertRaises(ValueError): accelerated.verify_accelerated_sources(ROOT, 'accelerated-functional-10x')

    def test_hash_and_capacity_only_semantic_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            d = Path(folder); original = ROOT / accelerated.EXPERIMENT / 'integration-reviewed-sources.json'
            hashes = json.loads(original.read_text())
            for relative in list(hashes) + [baseline.EXPERIMENT + '/nozzle.repl', baseline.EXPERIMENT + '/bed.repl']:
                target = d / relative; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / relative, target)
            manifest = d / accelerated.EXPERIMENT / 'integration-reviewed-sources.json'; manifest.write_text(original.read_text())
            profile = d / accelerated.EXPERIMENT / 'profiles/4x/nozzle.repl'
            profile.write_text(profile.read_text().replace('heaterPowerWatts: 60', 'heaterPowerWatts: 120'))
            with self.assertRaisesRegex(ValueError, 'dependency changed'):
                accelerated.verify_accelerated_sources(d, 'accelerated-functional-4x')
            hashes[str(profile.relative_to(d))] = baseline.sha(profile); manifest.write_text(json.dumps(hashes))
            with self.assertRaisesRegex(ValueError, 'heat capacity only'):
                accelerated.verify_accelerated_sources(d, 'accelerated-functional-4x')

    def test_wrapper_accepts_explicit_factors_but_not_10x(self):
        with tempfile.TemporaryDirectory() as folder:
            d = Path(folder); scripts = d / 'rv1106-at32-link/scripts'; scripts.mkdir(parents=True)
            tests = d / 'rv1106-at32-link/tests'; tests.mkdir()
            for name in ['assumed-centered-xy-contact.commands', 'nozzle-ntc-tmc.commands']:
                shutil.copyfile(ROOT / 'rv1106-at32-link/tests' / name, tests / name)
            shutil.copyfile(ROOT / 'rv1106-at32-link/scripts/run_native_event_fixture.sh', scripts / 'run_native_event_fixture.sh')
            (d / 'build-deps').mkdir(); (d / 'build-deps/env.sh').write_text(':\n')
            stub = scripts / 'run_combined.sh'; stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "' + str(d / 'args.txt') + '"\n'); stub.chmod(0o755)
            for factor in [4, 2, 10]:
                profile = 'accelerated-functional-' + str(factor) + 'x'
                env = dict(os.environ, THERMAL_PROFILE=profile, GLOBAL_QUANTUM_US='1', Z_PROBE_PROFILE='none', NOZZLE_TMC_MODEL='fixed', NATIVE_NOZZLE_HEATER='0')
                result = subprocess.run(['bash', str(scripts / 'run_native_event_fixture.sh'), profile], env=env, capture_output=True, text=True)
                if factor == 10:
                    self.assertNotEqual(result.returncode, 0); self.assertFalse((d / 'runs' / profile).exists())
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('--thermal-profile\n' + profile + '\n', (d / 'args.txt').read_text())


if __name__ == '__main__':
    unittest.main()
