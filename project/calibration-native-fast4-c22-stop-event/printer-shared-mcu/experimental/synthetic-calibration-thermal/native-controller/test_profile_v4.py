"""Offline fixed-profile, criterion, replay, and atomic intent tests."""
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest import mock
import test_controller as base
m=base.m
spec=importlib.util.spec_from_file_location('intent_publisher',Path(__file__).with_name('request_graceful_stop.py'))
publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)


def profile(selection):
    p=json.loads((Path(__file__).parent/'profile-fixtures/synthetic-calibration.json').read_text())
    if selection!='synthetic-calibration':
        p.update(selection=selection,functional_acceleration_factor=4,unrealistic_dynamics=True,
                 real_pid_validation=False,capacity_scaling_only=True,native_pid_and_sensor_smoothing_unchanged=True,
                 emulation_clock_scale=1,automatic_factor_fallback=False)
        p['parameters']['nozzle']['heat_capacity_j_per_k']=5
        p['parameters']['bed']['heat_capacity_j_per_k']=150
        p['accelerated_scenario']=json.loads((m.ROOT/'printer-shared-mcu/experimental/accelerated-functional-thermal/profiles/4x/parameters.json').read_text())
        for field,file in [('integration_helper_sha256','accelerated_thermal_profile_selection.py'),('baseline_integration_helper_sha256','thermal_profile_selection.py')]:
            p[field]=hashlib.sha256((m.ROOT/'rv1106-at32-link/scripts'/file).read_bytes()).hexdigest()
    return p


class FixedProfileTests(unittest.TestCase):
    def test_compound_capture_shell_syntax_and_no_echo_marker(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)
            for method,target in [('PrinterState',None),('GetStatus',None),('ExtruderPreheating',0),('ExtruderPreheating',230)]:
                req=m.prepare_request(d,'shellcheck','a'*24,method,target)
                commands=req['commands'];line=commands.splitlines()[-1]
                self.assertLessEqual(len(line),768)
                self.assertEqual(line.count('timeout -t 5'),1)
                self.assertIn('GRPC_PROBE_TRANSPORT_EXIT=$?;',line)
                self.assertTrue(line.endswith(req['end']+"''"))
                self.assertIn("echo READY_RAW_BEGIN'';",line)
                subprocess.run(['/bin/sh','-n'],input=commands,text=True,check=True,capture_output=True)

    def test_fixed_manifests_and_no_silent_fallback(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)
            def check(p,selection):
                (d/'thermal-profile.json').write_text(json.dumps(p));(d/'shared-profile.json').write_text(json.dumps({'thermal_profile':p}))
                return m.validate_profile(d,selection)
            for selection in m.PROFILE_RULES:
                p=profile(selection);self.assertEqual(check(p,selection),p)
            p=profile('accelerated-functional-4x')
            for field,value in [('functional_acceleration_factor',2),('real_pid_validation',True),('unrealistic_dynamics',False),('automatic_factor_fallback',True),('emulation_clock_scale',4),('native_pid_and_sensor_smoothing_unchanged',False),('integration_helper_sha256','bad')]:
                bad=copy.deepcopy(p);bad[field]=value
                with self.subTest(field=field),self.assertRaises(ValueError):check(bad,'accelerated-functional-4x')
            for heater in ('nozzle','bed'):
                bad=copy.deepcopy(p);bad['parameters'][heater]['heat_capacity_j_per_k']*=2
                with self.assertRaises(ValueError):check(bad,'accelerated-functional-4x')
            bad=copy.deepcopy(p);bad['accelerated_scenario']['clock_scale']=4
            with self.assertRaises(ValueError):check(bad,'accelerated-functional-4x')
            with self.assertRaises(ValueError):check(p,'synthetic-calibration')

    def test_five_second_criterion_only_accelerated_and_caps_unchanged(self):
        for selection,seconds,lead,cap in [('synthetic-calibration',30,232,240),('accelerated-functional-4x',5,52,60)]:
            r=m.Regulation('nozzle',selection);r.target_queue_ns=0;r.response_accepted=True
            traces={h:m.ThermalTrace(h) for h in m.TARGETS}
            for h,t in traces.items():t.latest={'faults':[],'physical_c':230 if h=='nozzle' else 25};t.last_growth_controller_ns=6*m.NS
            sample={'nozzle':{'current_c':230,'target_c':230},'bed':{'current_c':25,'target_c':0}}
            for second in range(1,7):r.observe_native(sample,second*m.NS,230)
            traces['nozzle'].physical_band_duration_s=5
            if selection.startswith('accelerated'):self.assertIn('sustained5s',r.stop_reason(traces,6*m.NS))
            else:self.assertIsNone(r.stop_reason(traces,6*m.NS))
            self.assertEqual(r.rules,dict(factor=4 if seconds==5 else 1,band_seconds=seconds,heat_cap_seconds=cap,zero_lead_seconds=lead))
            traces['nozzle'].latest['physical_c']=250
            self.assertIn('cap',r.stop_reason(traces,6*m.NS))
            traces['nozzle'].latest['physical_c']=230;traces['bed'].latest['physical_c']=75
            self.assertIn('cap',r.stop_reason(traces,6*m.NS))

    def test_accelerated_mock_success_does_not_claim_slow_regulation(self):
        original_parse=m.parse_args
        def args(argv):
            parsed=original_parse(argv);parsed.thermal_profile='accelerated-functional-4x';return parsed
        with mock.patch.object(m,'parse_args',side_effect=args):
            code,r=base.MockedController().execute('success')
        self.assertEqual(code,0,r.get('error'))
        self.assertTrue(r['complete_functional_evidence']);self.assertTrue(r['functional_band_criterion_met'])
        self.assertFalse(r['complete_regulation_evidence']);self.assertFalse(r['regulation_criterion_met'])
        self.assertFalse(r['pid_calibration_completed']);self.assertFalse(r['real_pid_validation']);self.assertFalse(r['print_completed'])
        self.assertEqual(r['band_criterion_evidence']['required_seconds'],5)
        self.assertGreaterEqual(r['band_criterion_evidence']['native_band_seconds'],5)
        self.assertGreaterEqual(r['band_criterion_evidence']['physical_band_seconds'],5)
        self.assertEqual(r['limits']['heat_virtual_seconds'],60)

    def test_accelerated_no_rise_and_uncertain_zero_are_bounded(self):
        original_parse=m.parse_args
        def args(argv):
            parsed=original_parse(argv);parsed.thermal_profile='accelerated-functional-4x';return parsed
        for mode in ('no-rise','zero-stall'):
            with mock.patch.object(m,'parse_args',side_effect=args):code,r=base.MockedController().execute(mode)
            self.assertEqual(code,2);self.assertFalse(r['complete_functional_evidence'])
            self.assertIn('52-second',r['heat_stop_criterion'])
            if mode=='zero-stall':
                self.assertEqual(r['phase'],'hard_heat_cap');self.assertFalse(r['zero_response_verified'])

    def test_replay_uses_selected_capacity_only(self):
        # Fresh invented offline vector, not native evidence. Actual GPIO stays high.
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'trace.csv';text=base.BED_HEADER
            for i in range(101):
                temp=25+200/1.5*(1-math.exp(-1.5*(i*.01)/150))
                resistance=100000*math.exp(3950*(1/(temp+273.15)-1/298.15))
                adc=math.floor(4095*resistance/(4700+resistance)+.5)
                line=base.row(i*10000,temp,1,1 if i else 0,heater='bed').split(',')
                line[9]=str(adc);text+=','.join(line)
            p.write_text(text)
            result=m.replay.analyze(p,'bed',profile_selection='accelerated-functional-4x')
            self.assertEqual(result['heat_capacity_j_per_k'],150)
            with self.assertRaises(ValueError):m.replay.analyze(p,'bed')


class IntentTests(unittest.TestCase):
    def test_atomic_publish_no_replace_and_read(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);(d/'thermal-observation.json').write_text('{"phase":"heating"}')
            p=publisher.publish(d,'Switch fixture after safe stop')
            self.assertEqual(m.read_graceful_stop(p)['action'],'stop_heating')
            first=p.read_bytes()
            with self.assertRaises(FileExistsError):publisher.publish(d,'Another reason')
            self.assertEqual(p.read_bytes(),first);self.assertEqual(list(d.glob('.graceful-intent-*')),[])
            (d/'stop-request').write_text('ended')
            with self.assertRaises(ValueError):publisher.publish(d,'Late intent')

    def test_invalid_intent_is_not_a_native_command(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'intent.json';self.assertIsNone(m.read_graceful_stop(p))
            for value in [{}, {'action':'set_target','reason':'x'}, {'action':'stop_heating','reason':''},
                          {'action':'stop_heating','reason':'x','target':0}, {'action':'stop_heating','reason':'bad\nreason'}]:
                p.write_text(json.dumps(value))
                with self.assertRaises(ValueError):m.read_graceful_stop(p)
            p.write_text(' '*4097)
            with self.assertRaises(ValueError):m.read_graceful_stop(p)


if __name__=='__main__':unittest.main()
