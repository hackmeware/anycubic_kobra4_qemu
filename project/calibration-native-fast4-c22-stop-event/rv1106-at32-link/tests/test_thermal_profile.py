#!/usr/bin/env python3
"""Generation/negative/default identity only. Never execute firmware."""
import hashlib
import json
import os
import subprocess
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'rv1106-at32-link/scripts'), str(Path(__file__).resolve().parent)]
from run_link import parser, execution_args
from shared_mcu import prepare
from test_z_probe_profile import arguments, tree
import thermal_profile_selection as thermal

QUANTUM = 'emulation SetGlobalQuantum "0.000001"'
MAIN = ['include @scripts/virtual-bed-ntc.resc']
NOZZLE = ['include @scripts/virtual-nozzle-recovered-ntc.resc', 'include @scripts/virtual-tmc2209.resc', QUANTUM]


class ThermalProfileTests(unittest.TestCase):
    def selected(self, path):
        args = arguments(path)
        args.thermal_profile = thermal.PROFILE
        args.nozzle_tmc_model = 'autobaud'
        return args

    def test_default_and_proven_z_autobaud_exact_bytes(self):
        before = ROOT / 'evidence/synthetic-thermal-profile-integration/before/shared_mcu.py'
        old = types.ModuleType('before_thermal_selection')
        old.__file__ = str(ROOT / 'rv1106-at32-link/scripts/shared_mcu.py')
        exec(compile(before.read_text(), old.__file__, 'exec'), old.__dict__)
        for plant, tmc, z in [('electrical', 'fixed', False), ('electromechanical-driver', 'fixed', False),
                              ('electromechanical-driver', 'autobaud', False), ('electromechanical-driver', 'autobaud', True)]:
            with self.subTest(plant=plant, tmc=tmc, z=z), tempfile.TemporaryDirectory() as folder:
                d = Path(folder)
                args = arguments(d, selected=z)
                args.motor_plant, args.nozzle_tmc_model = plant, tmc
                nozzle = NOZZLE if tmc == 'autobaud' else NOZZLE[:-1]
                old.prepare(args, d, MAIN, nozzle)
                baseline = tree(d)
                shutil.rmtree(d / 'shared-models'); shutil.rmtree(d / 'logs'); (d / 'logs').mkdir()
                prepare(args, d, MAIN, nozzle)
                self.assertEqual(baseline, tree(d))

    def test_selected_exclusive_ordering_and_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            d = Path(folder); args = self.selected(d)
            script, _ = prepare(args, d, MAIN, NOZZLE)
            text = script.read_text()
            self.assertNotIn('virtual-bed-ntc.resc', text)
            self.assertNotIn('virtual-nozzle-recovered-ntc.resc', text)
            self.assertNotIn('virtual-commanded-bed.repl', text)
            self.assertEqual(text.count('/thermal-profile/bed.repl'), 1)
            self.assertEqual(text.count('/thermal-profile/nozzle.repl'), 1)
            self.assertLess(text.index('/thermal-profile/bed.repl'), text.index('passiveBedThermalObserver Start'))
            self.assertLess(text.index('/thermal-profile/nozzle.repl'), text.index('passiveNozzleThermalObserver Start'))
            self.assertLess(text.index('passiveNozzleThermalObserver Start'), text.index('RunFor'))
            self.assertIn('Cs1237NativeGpio', (d / 'shared-models/nozzle/platforms/nozzle-f1-provisional.repl').read_text())
            profile = json.loads((args.log_dir / 'shared-profile.json').read_text())
            info = json.loads((args.log_dir / 'thermal-profile.json').read_text())
            self.assertEqual(info, profile['thermal_profile'])
            self.assertEqual(profile['nozzle_tmc_model']['selection'], 'autobaud')
            self.assertEqual(profile['z_probe_profile']['maximum_state_age_ns'], 100000)
            self.assertEqual(profile['z_probe_profile']['maximum_producer_lead_ns'], 1000)
            self.assertEqual(info['parameters']['nozzle']['heater_power_w'], 60)
            self.assertFalse(info['parameters']['pb9_thermal_connection'])
            for entry in json.loads((d / 'shared-models/manifest.json').read_text()):
                self.assertEqual(entry['generated_sha256'], thermal.sha(d / 'shared-models' / entry['generated']))
            for source, expected in info['source_sha256'].items():
                self.assertEqual(thermal.sha(ROOT / source), expected)
            self.assertNotIn('AT32.', (d / 'shared-models/thermal-profile/bed.repl').read_text())
            self.assertIn('PrinterMain;', (d / 'shared-models/thermal-profile/ResolvedBedHeaterBinding.cs').read_text())
            self.assertNotIn('SetDutyCycle', text)
            self.assertIn('SensorCurveOutOfRange', thermal.final_commands(args))

    def test_requirements(self):
        args = parser().parse_args([])
        self.assertEqual(args.thermal_profile, 'none')
        self.assertEqual(thermal.final_commands(args), '')
        args.thermal_profile = thermal.PROFILE
        with self.assertRaises(ValueError): execution_args(args)
        args.shared_mcus = True
        with self.assertRaises(ValueError): execution_args(args)
        args.motor_plant = 'electromechanical-driver'; args.peer_monitor_input = Path('live')
        with self.assertRaises(ValueError): execution_args(args)
        args.peer_monitor_input = None; args.mcu_hext = 12000000
        with self.assertRaises(ValueError): execution_args(args)

    def test_setup_rejects_extra_writers_bindings_execution_and_overrides(self):
        with tempfile.TemporaryDirectory() as folder:
            d = Path(folder); args = self.selected(d)
            bad_lines = ['emulation SetGlobalQuantum "0.00001"', 'emulation RunFor "1"', 'start', 'machine Reset',
                         'cpu PerformanceInMips 10', 'sysbus.virtualNozzleNTC SetDutyCycle 1',
                         'sysbus.virtualNozzleNTC ColdReset', 'sysbus.virtualNozzleNTC SetSensorFault open',
                         'sysbus.adc1 SetChannelValue 0 468', 'sysbus.gpioB WriteDoubleWord 12 256',
                         'include @scripts/native-nozzle-heater-binding.resc',
                         'machine LoadPlatformDescription @platforms/virtual-nozzle-ntc.repl',
                         'machine LoadPlatformDescriptionFromString "another: AT32.VirtualPrinterThermal @ sysbus { channel: 0 }"',
                         'include @scripts/passive-nozzle-thermal-observer.resc',
                         'include @' + str(ROOT / 'nozzle-renode/peripherals/VirtualPrinterThermal.cs')]
            for line in bad_lines:
                with self.subTest(line=line), self.assertRaises(ValueError):
                    thermal.prepare_setup(ROOT, args, MAIN, NOZZLE + [line], [])
            with self.assertRaises(ValueError): thermal.prepare_setup(ROOT, args, MAIN, NOZZLE[:-1], [])
            with self.assertRaises(ValueError): thermal.prepare_setup(ROOT, args, MAIN, NOZZLE + ['include @scripts/virtual-nozzle-ntc.resc'], [])
            hidden = d / 'hidden.resc'; hidden.write_text('sysbus.adc1 SetChannelValue 0 468\n')
            with self.assertRaises(ValueError): thermal.prepare_setup(ROOT, args, MAIN, NOZZLE + ['include @' + str(hidden)], [])

    def test_wrapper_opt_in_contract_and_early_rejections(self):
        with tempfile.TemporaryDirectory() as folder:
            d = Path(folder)
            scripts = d / 'rv1106-at32-link/scripts'; scripts.mkdir(parents=True)
            tests = d / 'rv1106-at32-link/tests'; tests.mkdir()
            for name in ['assumed-centered-xy-contact.commands', 'nozzle-ntc-tmc.commands']:
                shutil.copyfile(ROOT / 'rv1106-at32-link/tests' / name, tests / name)
            shutil.copyfile(ROOT / 'rv1106-at32-link/scripts/run_native_event_fixture.sh', scripts / 'run_native_event_fixture.sh')
            (d / 'build-deps').mkdir(); (d / 'build-deps/env.sh').write_text(':\n')
            stub = scripts / 'run_combined.sh'
            stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "' + str(d / 'args.txt') + '"\n')
            stub.chmod(0o755)
            environment = dict(os.environ, THERMAL_PROFILE='synthetic-calibration', GLOBAL_QUANTUM_US='1',
                               Z_PROBE_PROFILE='synthetic-functional', NOZZLE_TMC_MODEL='autobaud',
                               PASSIVE_NOZZLE_TRACE='1', PASSIVE_TMC_TRACE='1', NATIVE_NOZZLE_HEATER='0')
            run = subprocess.run(['bash', str(scripts / 'run_native_event_fixture.sh'), 'selected'], env=environment, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('--thermal-profile\nsynthetic-calibration\n', (d / 'args.txt').read_text())
            self.assertIn('--nozzle-final-commands', (d / 'args.txt').read_text())
            self.assertNotIn('passive-nozzle-thermal-observer', (d / 'runs/selected/nozzle-setup.commands').read_text())
            thermal.validate_final_commands((d / 'runs/selected/main-final.commands').read_text().splitlines())
            thermal.validate_final_commands((d / 'runs/selected/nozzle-final.commands').read_text().splitlines())
            for name, overrides in [('bad-quantum', {'GLOBAL_QUANTUM_US': '10', 'Z_PROBE_PROFILE': 'none', 'NOZZLE_TMC_MODEL': 'fixed'}),
                                    ('duplicate-binding', {'NATIVE_NOZZLE_HEATER': '1'}),
                                    ('bad-profile', {'THERMAL_PROFILE': 'unknown'})]:
                result = subprocess.run(['bash', str(scripts / 'run_native_event_fixture.sh'), name], env=dict(environment, **overrides), capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((d / 'runs' / name).exists())

    def test_final_diagnostics_reject_model_overrides(self):
        allowed = ['pause', 'mach set "main"', 'machine ElapsedVirtualTime',
                   'dump_file 0x20000000 0x18000 @/tmp/test.bin', 'sysbus.gpioA ReadDoubleWord 12',
                   'sysbus.electromechanicalPlant StopContactTrace', 'sysbus.electromechanicalPlant IntegrationCalls',
                   'sysbus.tmcTimingObserver WriteCsv "/tmp/tmc.csv"', 'sysbus.tmcTimingObserver Dropped']
        thermal.validate_final_commands(allowed)
        for line in ['sysbus.virtualBedNTC ColdReset', 'sysbus.virtualBedNTC SetDutyCycle 0',
                     'sysbus.virtualBedNTC SetSensorFault none', 'sysbus.adc1 SetChannelValue 8 3444',
                     'sysbus.gpioA WriteDoubleWord 12 0', 'include @unreviewed.resc', 'emulation RunFor "1"']:
            with self.subTest(line=line), self.assertRaises(ValueError): thermal.validate_final_commands([line])

    def test_default_returns_setup_untouched(self):
        args = parser().parse_args([])
        commands = ['include @anything.resc', 'anything']
        self.assertEqual(thermal.prepare_setup(ROOT, args, commands, commands, commands), (commands, commands, commands))


if __name__ == '__main__':
    unittest.main()
