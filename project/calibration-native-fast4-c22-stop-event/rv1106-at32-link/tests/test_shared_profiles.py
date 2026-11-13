#!/usr/bin/env python3
"""Configuration regression only; not a firmware motion test."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'rv1106-at32-link/scripts'))
from run_link import parser
from shared_mcu import prepare

class Profiles(unittest.TestCase):
    def generate(self, mode, contact=False, lockstep=False, cable=False, wiring="direct-bridge-gate", edges=False):
        a=parser().parse_args([]);a.motor_enable_wiring=wiring;a.trace_homing_gpio=edges
        a.clock_lockstep=lockstep;a.clock_coupled=lockstep;a.assumed_xy_diag_cable=cable
        a.mcu_image=ROOT/'inputs/mcu.bin';a.nozzle_image=ROOT/'inputs/nozzle.bin';a.motor_image=ROOT/'inputs/motor.bin'
        a.mcu_base=a.nozzle_base=0x08004000;a.motor_plant=mode
        a.motor_setup_commands=ROOT/'rv1106-at32-link/tests/assumed-centered-xy-contact.commands' if contact else None
        with tempfile.TemporaryDirectory() as directory:
            tmp=Path(directory);a.log_dir=tmp/'logs';a.log_dir.mkdir()
            script,_=prepare(a,tmp,[],[])
            return script.read_text(),(tmp/'shared-models/shared-load.resc').read_text(),json.loads((a.log_dir/'shared-profile.json').read_text())
    def test_mcu_control_only(self):
        script,bootstrap,profile=self.generate('electromechanical-driver',wiring='mcu-control-only')
        self.assertIn('generic-driver-mcu-control-only.repl',bootstrap)
        self.assertEqual(profile['motor_enable_wiring']['assumption'],'mcu-control-only')
        self.assertFalse(profile['motor_enable_wiring']['physical_pcb_verified'])
    def test_passive_edge_observers(self):
        script,bootstrap,profile=self.generate('electromechanical-driver',edges=True)
        self.assertIn('main-homing-edges.csv',script)
        self.assertIn('motor-homing-edges.csv',script)
        self.assertIn('Observe sysbus.gpioC 13',script)
        self.assertLess(script.index('homingEdges Start'),script.index('emulation RunFor'))
        self.assertTrue(profile['passive_homing_gpio_edges'])
    def test_original_default(self):
        script,bootstrap,profile=self.generate('electrical')
        self.assertIn('generic-stationary-rl.resc',bootstrap)
        self.assertNotIn('generic-electromechanical.resc',bootstrap)
        self.assertNotIn('genericDriver',bootstrap)
        self.assertNotIn('ConfigureRelativeContact',script)
        self.assertEqual(profile['motor_plant'],'electrical')
    def test_lockstep_initial_boundary(self):
        script,bootstrap,profile=self.generate('electromechanical-driver',True,True)
        self.assertIn('timeTelemetry Enable',script)
        self.assertIn('timeTelemetry PublishStep',script)
        self.assertLess(script.index('emulation RunFor "1"'),script.index('timeTelemetry PublishStep'))
        self.assertNotEqual(script.strip().splitlines()[-1],'start')
        self.assertTrue(profile['clock_lockstep'])
    def test_explicit_diag_cable(self):
        script,bootstrap,profile=self.generate('electromechanical-driver',True,True,True)
        self.assertIn('assumedDiagX SelectSourcePin sysbus.gpioB 5',bootstrap)
        self.assertIn('assumedDiagX SelectDestinationPin sysbus.gpioA 6',bootstrap)
        self.assertIn('assumedDiagY SelectSourcePin sysbus.gpioB 4',bootstrap)
        self.assertIn('assumedDiagY SelectDestinationPin sysbus.gpioA 15',bootstrap)
        self.assertFalse(profile['assumed_xy_diag_cable']['physical_pcb_wiring_verified'])
    def test_explicit_contact(self):
        script,bootstrap,profile=self.generate('electromechanical-driver',True)
        self.assertNotIn('generic-stationary-rl.resc',bootstrap)
        self.assertIn('generic-electromechanical.resc',bootstrap)
        self.assertIn('sysbus.gpioC OnGPIO 13 true',bootstrap)
        self.assertLess(bootstrap.index('motorEnable SelectDestinationPin'),bootstrap.index('sysbus.gpioC OnGPIO 13 true'))
        self.assertIn('motorEnable SelectSourcePin sysbus.gpioC 13',bootstrap)
        self.assertIn('motorEnable SelectDestinationPin sysbus.genericDriver 0',bootstrap)
        self.assertIn('ConfigureRelativeContact 0 -149.25 149.25',script)
        self.assertIn('ConfigureRelativeContact 1 -140 140',script)
        self.assertLess(script.index('ConfigureRelativeContact'),script.index('emulation RunFor'))
        self.assertFalse(profile['homing_state_modified'])

if __name__=='__main__':unittest.main()
