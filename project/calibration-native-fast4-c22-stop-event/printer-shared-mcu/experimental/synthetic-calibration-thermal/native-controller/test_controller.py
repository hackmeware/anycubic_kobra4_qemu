"""Offline captured-protocol, passive arithmetic and mocked orchestration tests only."""
import contextlib
import csv
import importlib.util
import io
import json
import math
import pathlib
import re
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('controller', HERE / 'controller.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
fixture_spec = importlib.util.spec_from_file_location('fixture', m.ROOT / 'rv1106-at32-link/tests/test_native_xyz_observation.py')
f = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(f)
HEADER = 'time_us,event,changed_pin,changed_level,pb8_level,pb9_level,pb8_config,pb9_config,pb8_latch,pb9_latch,physical_temperature_c,published_adc_code,sensor_curve,sensor_fault,curve_out_of_range,model_overtemperature,model_heater_latched_off,last_heater_duty,last_fan_duty,thermal_updates\n'
BED_HEADER = 'time_us,virtual_time_ns,event,changed_pin,changed_level,pa0_level,pa0_config,pa0_latch,physical_temperature_c,published_adc_code,sensor_curve,sensor_fault,model_overtemperature,model_heater_latched_off,last_heater_duty,last_fan_duty,thermal_updates\n'


def row(us, temp=25, level=0, duty=0, fault='none', heater='nozzle'):
    if heater == 'nozzle':
        return f'{us},sample,,,{level},0,3,3,{level},0,{temp},4023,NTC ZM3863 HNS112HC4570G0,{fault},0,0,0,{duty},0,{us // 10000}\n'
    return f'{us},{us*1000},sample,,,{level},3,{level},{temp},3911,B3950 100k 4700ohm illustrative divider,{fault},0,0,{duty},0,{us // 10000}\n'


def native_payload(current=25, target=0, bed_current=25, bed_target=0):
    def msg(number, payload):
        return m.varint(number * 8 + 2) + m.varint(len(payload)) + payload
    def heater(current, target):
        return b'\x08' + m.varint(current) + b'\x10' + m.varint(target)
    return msg(1, msg(2, heater(current, target)) + msg(3, heater(bed_current, bed_target)))


def capture(request, protobuf=b'', status=0):
    if request['method'] == 'GetStatus':
        headers=f.frame(1,4,b'\x88\x00\x0ccontent-type\x10application/grpc')
        payload=b'\0'+len(protobuf).to_bytes(4,'big')+protobuf
        data=headers+f.frame(0,0,payload)+f.frame(0,0,payload)
        if status==0:status=m.snapshot.SNAPSHOT_CANCELLED
    else:
        data = f.wire(protobuf)
    return (request['begin'] + '\nREADY_CLIENT_STATUS=' + str(status) + '\n' + m.ready.RAW_BEGIN + '\n' + f.od(data) +
            m.ready.RAW_END + '\nGRPC_PROBE_TRANSPORT_EXIT=' + str(status) + '\nGRPC_PROBE_DONE\n' + request['end'] + '\n')


class Protocol(unittest.TestCase):
    def test_exact_requests_and_inert_generation(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(m.subprocess, 'Popen', side_effect=AssertionError('No native runs')):
            for method, target, expected in [('PrinterState', None, b''), ('GetStatus', None, b''),
                  ('ExtruderPreheating', 230, bytes.fromhex('10e601')), ('HotbedPreheating', 60, bytes.fromhex('103c')),
                  ('ExtruderPreheating', 0, b''), ('HotbedPreheating', 0, b'')]:
                request = m.prepare_request(pathlib.Path(tmp), method+str(target), 'test', method, target)
                self.assertEqual(request['protobuf_hex'], expected.hex())
                packet, pb = m.request_packet(method, target)
                elf = pathlib.Path(tmp, 'thermal-' + method+str(target) + '.elf').read_bytes()
                self.assertEqual(m.transport.extract_packet(elf), packet)
                self.assertEqual(request['commands'].count('timeout -t 5 /tmp/grpc-probe >'), 1)

    def test_forbidden(self):
        for method, target in [('RunGcodeScript', None), ('PidCalibrate', None), ('Homing', None),
                               ('ExtruderPreheating', 229), ('HotbedPreheating', 75), ('HotbedPreheating', True),
                               ('PrinterState', 0), ('GetStatus', 25)]:
            with self.subTest(method=method,target=target), self.assertRaises(ValueError):
                m.request_packet(method, target)

    def test_captured_ready_response(self):
        request = {'begin': 'B', 'end': 'E', 'method': 'PrinterState'}
        data = bytes.fromhex((m.ROOT / 'rv1106-at32-link/tests/fixtures/native-ready-response.hex').read_text())
        text = 'B\nREADY_CLIENT_STATUS=0\nREADY_RAW_BEGIN\n'+f.od(data)+'READY_RAW_END\nGRPC_PROBE_TRANSPORT_EXIT=0\nGRPC_PROBE_DONE\nE\n'
        self.assertEqual(m.verify_capture(text, request)['ready_response']['state'], 'ready')

    def test_real_accepted_heater_capture(self):
        # Historical request used the legacy timeout transport. Reassemble exact
        # captured HTTP/2 bytes without pretending legacy timeout exit was success.
        text = (m.ROOT / 'evidence/native-nozzle-heating-response/raw/console.bin').read_text(errors='replace')
        found = []
        for match in re.finditer(r'(?m)^0000000[ \t]+(?:[0-7]{3}[ \t]*)+\r?\n', text):
            suffix = text[match.start():]
            final = re.search(r'(?m)^[0-7]{7,}\r?\n', suffix)
            if final:
                try:
                    data = m.ready.read_od(suffix[:final.end()])
                    pb = m.xyz.unary_protobuf(data)
                    if pb == b'': found.append(data)
                except ValueError:
                    pass
        self.assertGreaterEqual(len(found), 2)
        self.assertFalse(m.errors.decode_response(m.xyz.unary_protobuf(found[0]))['error_reported'])

    def test_response_success_error_and_native_temperatures(self):
        req = {'begin': 'B', 'end': 'E', 'method': 'ExtruderPreheating'}
        self.assertTrue(m.verify_capture(capture(req), req)['rpc_acceptance_verified'])
        self.assertFalse(m.verify_capture(capture(req, bytes.fromhex('0a0908ffff031203626164')), req)['rpc_acceptance_verified'])
        req['method'] = 'GetStatus'
        self.assertEqual(m.verify_capture(capture(req, native_payload(230,230)), req)['native_temperatures']['nozzle'],
                         {'current_c':230,'target_c':230})

    def test_protocol_uncertainty(self):
        req = {'begin': 'B', 'end': 'E', 'method': 'ExtruderPreheating'}
        good = capture(req)
        for bad in (capture(req,status=143), good+good, good.replace('GRPC_PROBE_DONE\n',''),
                    good.replace('GRPC_PROBE_TRANSPORT_EXIT=0','GRPC_PROBE_TRANSPORT_EXIT=6'),
                    good.replace('READY_RAW_END','WRONG_END')):
            with self.subTest(bad=bad), self.assertRaises(ValueError): m.verify_capture(bad,req)
        self.assertIsNone(m.verify_capture(good[:-2],req))
        for data in (f.wire()[:-1], f.wire(status=b'13'), f.frame(3,0,b'\0'*4), f.wire()+b'\0', f.wire(b'\xff')):
            with self.subTest(data=data), self.assertRaises(ValueError):
                pb=m.xyz.unary_protobuf(data)
                m.errors.decode_response(pb)


class TraceTests(unittest.TestCase):
    def test_historical_heat_curve_gpio_replay(self):
        path = m.ROOT / 'evidence/native-nozzle-heating-response/raw/nozzle-thermal-live.csv'
        result = m.replay.analyze(path, 'nozzle', power_override=40)
        self.assertLess(result['max_physical_error_c_from_gpio'],3e-6)
        trace = m.ThermalTrace('nozzle')
        trace.consume(path.read_bytes(), 25*m.NS)
        self.assertGreater(trace.max_temperature,32)
        self.assertEqual(trace.latest['level'],0)
        self.assertFalse(trace.latest['faults'])

    def test_stability_and_cooling_are_separate(self):
        t = m.ThermalTrace('nozzle')
        data = HEADER
        for i in range(301): data += row(i*100000,230,1,0.7)
        t.consume(data.encode(),30*m.NS,target=230)
        self.assertEqual(t.physical_band_duration_s,30)
        self.assertEqual(t.off_duration_s,0)
        for i in range(301,362): data += row(i*100000,230-(i-300)*.01)
        t.consume(data.encode(),37*m.NS,zero_confirmed=True)
        self.assertGreaterEqual(t.off_duration_s,5)
        self.assertGreater(t.cooling_c,.1)

    def test_fault_truncation_nonfinite_gap_and_time(self):
        t=m.ThermalTrace('nozzle'); data=(HEADER+row(0)+row(100000)).encode();t.consume(data,0)
        self.assertTrue(t.stale(4*m.NS))
        for bad in (data[:-5], (HEADER+row(0)).encode(),data+row(1000000).encode(),data+row(90000).encode(),data+row(200000,'nan').encode()):
            with self.subTest(bad=bad),self.assertRaises(ValueError): t.consume(bad,0)
        t.consume(data+row(200000,fault='open').encode(),0)
        self.assertTrue(t.latest['faults'])

    def test_no_rise_capped_not_success(self):
        r=m.Regulation('nozzle');r.target_queue_ns=0;r.response_accepted=True
        traces={h:m.ThermalTrace(h) for h in m.TARGETS}
        for h,t in traces.items():
            t.latest={'faults':[],'physical_c':25};t.last_growth_controller_ns=232*m.NS
        r.observe_native({'nozzle':{'current_c':25,'target_c':230},'bed':{'current_c':25,'target_c':0}},232*m.NS,230)
        self.assertIn('232-second',r.stop_reason(traces,232*m.NS))
        self.assertEqual(r.native_band_duration_s,0)

    def test_dual_band_and_early_caps(self):
        r=m.Regulation('nozzle');r.target_queue_ns=0;r.response_accepted=True
        traces={h:m.ThermalTrace(h) for h in m.TARGETS}
        for h,t in traces.items():
            t.latest={'faults':[],'physical_c':230 if h=='nozzle' else 25};t.last_growth_controller_ns=31*m.NS
        sample={'nozzle':{'current_c':230,'target_c':230},'bed':{'current_c':25,'target_c':0}}
        for second in range(1,32): r.observe_native(sample,second*m.NS,230)
        self.assertIsNone(r.stop_reason(traces,31*m.NS))
        traces['nozzle'].physical_band_duration_s=30
        self.assertIn('Independent',r.stop_reason(traces,31*m.NS))
        traces['nozzle'].latest['physical_c']=250
        self.assertIn('cap',r.stop_reason(traces,31*m.NS))
        traces['nozzle'].latest['faults']=['open']
        self.assertIn('fault',r.stop_reason(traces,31*m.NS))

    def test_camera_exception_exact_only(self):
        self.assertFalse(m.xyz.native_failure('error',m.xyz.KNOWN_ABSENT_VIDEO_SERVICE))
        self.assertTrue(m.xyz.native_failure('error',m.xyz.KNOWN_ABSENT_VIDEO_SERVICE+' changed'))
        self.assertTrue(m.xyz.native_failure('warning','MCU shutdown'))


def startup_lines():
    return ''.join('[1970-01-01 00:00:02.%03d] [error] [%d] %s\n' % (i, meta[0], message)
                   for i, (message, meta) in enumerate(m.KNOWN_STARTUP_AUXILIARY.items()))


class StartupReviewTests(unittest.TestCase):
    def test_exact_five_are_retained_not_fatal_before_ready(self):
        review=m.NativeErrorReview();review.observe(startup_lines()+f.READY)
        self.assertEqual(len(review.startup_errors),5)
        self.assertEqual(len(review.known_startup_errors),5)
        self.assertEqual(review.failures,[])
        review.observe(startup_lines()+f.READY)
        self.assertEqual(len(review.startup_errors),5)

    def test_after_ready_or_delayed_ready_does_not_exempt(self):
        message='wifi init failed'
        line='[1970-01-01 00:00:11.001] [error] [36] '+message+'\n'
        for delayed in (False,True):
            review=m.NativeErrorReview()
            review.observe(line if delayed else f.READY+line)
            review.observe(f.READY+line)
            self.assertEqual(len(review.failures),1)

    def test_exact_severity_source_path_and_full_message_required(self):
        base='[1970-01-01 00:00:02.001] [error] [36] wifi init failed\n'
        for line in (base.replace('[36]','[37]'),base.replace('[error]','[critical]'),
                     base.replace('failed\n','failedtail -100 /data/logs/avata_main.log\n'),
                     '[1970-01-01 00:00:02.001] [error] [218] Unable to read config file /app/etc/avata_main.cfg\n',
                     '[1970-01-01 00:00:02.001] [error] [123] filament hub config file open failed: Permission denied\n'):
            review=m.NativeErrorReview();review.observe(line)
            self.assertEqual(len(review.failures),1,line)
            self.assertEqual(review.known_startup_errors,[])

    def test_unknown_motion_thermal_tmc_guard_errors_block_even_before_ready(self):
        for text in ('Verification failed for register 2 (start/stop bits or CRC mismatch)',
                     'Heater extruder not heating at expected rate','Printer is shutdown',
                     'MCU shutdown: ADC out of range','Unknown configuration failure'):
            review=m.NativeErrorReview()
            review.observe('[1970-01-01 00:00:02.001] [error] [301] '+text+'\n'+f.READY)
            self.assertEqual(len(review.failures),1)
        review=m.NativeErrorReview()
        review.observe('[1970-01-01 00:00:02.001] [warning] [301] MCU shutdown\n')
        self.assertEqual(len(review.failures),1)

    def test_captured_successful_autobaud_starts(self):
        for run in ('native-ready-autobaud','native-ready-synthetic-z','native-ready-synthetic-z-clockfix'):
            text=(m.ROOT/'runs'/run/'console.bin').read_text(errors='replace')
            review=m.NativeErrorReview();review.observe(text)
            self.assertIsNotNone(review.ready_stamp)
            self.assertEqual(len(review.known_startup_errors),5,run)
            self.assertEqual(review.failures,[],run)

    def test_older_success_is_not_blanket_guard_or_corruption_exemption(self):
        for run in ('native-xy-quantum1','native-home-x-heater','native-xyz-synthetic-z-r1'):
            review=m.NativeErrorReview()
            review.observe((m.ROOT/'runs'/run/'console.bin').read_text(errors='replace'))
            self.assertEqual(len(review.known_startup_errors),5)
            self.assertGreater(len(review.failures),0)


class SimulatedLauncher:
    """Mock only: never an executable, GPIO source, firmware or physical model."""
    def __init__(self, root, mode, selected='nozzle'):
        self.directory = root / 'runs' / 'mock'
        self.directory.mkdir(parents=True)
        self.mode, self.seconds, self.target, self.zero_at = mode, 0, 0, None
        self.selected = selected
        self.request_names = set()
        self.pid = 123456
        (self.directory / 'console-input.commands').write_text('')
        (self.directory / 'console.bin').write_text(startup_lines()+f.READY + 'COUPLED_STARTUP_COMMANDS_DONE\n')
        if mode=='unknown-startup':
            with (self.directory / 'console.bin').open('a') as stream:
                stream.write('[1970-01-01 00:00:02.001] [error] [301] Verification failed for register 2 (start/stop bits or CRC mismatch)\n')
        (self.directory / 'nozzle-thermal-live.csv').write_text(HEADER + row(0))
        (self.directory / 'bed-thermal-live.csv').write_text(BED_HEADER + row(0,heater='bed'))

    def poll(self):
        if (self.directory / 'stop-request').exists(): return 0
        self.seconds += 1
        commands = (self.directory / 'console-input.commands').read_text()
        for match in re.finditer(r'(?m)^echo (THERMAL_([A-Z0-9]+)_BEGIN_[a-f0-9]+)$',commands):
            begin, stage = match[1], match[2].lower()
            if stage in self.request_names: continue
            self.request_names.add(stage)
            method = 'PrinterState' if stage=='ready' else 'GetStatus' if stage.startswith('status') else m.METHODS[self.selected]
            request = {'begin':begin,'end':begin.replace('_BEGIN_','_END_'),'method':method}
            if stage=='target': self.target=m.TARGETS[self.selected]
            if stage=='zero': self.target=0;self.zero_at=self.seconds
            if method=='PrinterState': payload=bytes.fromhex('12057265616479')
            elif method=='GetStatus':
                current=25 if self.target==0 or self.mode in ('no-rise','zero-stall') else m.TARGETS[self.selected]
                payload=native_payload(current,self.target) if self.selected=='nozzle' else native_payload(25,0,current,self.target)
                if self.mode=='baseline-zero' or self.mode=='baseline-zero-then-valid' and stage=='status001':
                    payload=native_payload(0,0,0,0)
            else: payload=b''
            status=143 if stage=='target' and self.mode=='timeout' else 0
            if not (stage=='zero' and self.mode=='zero-stall'):
                with (self.directory / 'console.bin').open('a') as out: out.write(capture(request,payload,status))
        for match in re.finditer(r"(?m)(?:^|; )echo (THERMAL_LOG_END_[a-f0-9]+_[0-9]+)(?:'')?$",commands):
            if match[1] not in self.request_names:
                self.request_names.add(match[1])
                with (self.directory / 'console.bin').open('a') as out:out.write(match[1]+'\n')
        if self.mode=='fault' and self.target and self.seconds>=6:
            with (self.directory / 'console.bin').open('a') as out:
                out.write('[1970-01-01 00:00:%02d.001] [error] [199] MCU shutdown: Heater failure\n' % self.seconds)
        for heater in m.TARGETS:
            if heater==self.selected and self.target:
                physical=25 if self.mode in ('no-rise','zero-stall') else m.TARGETS[heater]
            elif heater==self.selected and self.zero_at is not None:
                physical=m.TARGETS[heater]-(self.seconds-self.zero_at)
            else: physical=25
            with (self.directory / (heater+'-thermal-live.csv')).open('a') as out:
                for tenth in range(1,11):
                    out.write(row(((self.seconds-1)*10+tenth)*100000,physical,
                                  int(heater==self.selected and bool(self.target)),
                                  .7 if heater==self.selected and self.target else 0,
                                  fault='open' if self.mode=='sensor-fault' and heater==self.selected and self.seconds>=6 else 'none',heater=heater))
        (self.directory / 'virtual-time.json').write_text(json.dumps({'virtual_time_ns':self.seconds*m.NS,
             'time_went_backwards':False,'enabled':True,'epoch':'mock'}))
        return None

    def wait(self, timeout=None):return 0


class MockedController(unittest.TestCase):
    def execute(self,mode,heater='nozzle'):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            proc=SimulatedLauncher(root,mode,heater)
            args=m.parse_args(['mock','--thermal-profile','synthetic-calibration','--heater',heater,
                              '--nozzle-tmc-model','autobaud','--execute'])
            # Launcher normally creates directory after preflight. Move creation
            # into mocked Popen so the no-overwrite contract remains exercised.
            import shutil
            shutil.rmtree(root/'runs'/'mock')
            def start(*unused,**kwargs):
                nonlocal proc
                proc=SimulatedLauncher(root,mode,heater)
                return proc
            with mock.patch.object(m,'ROOT',root), mock.patch.object(m,'verify_dependencies',return_value={}), \
                 mock.patch.object(m,'validate_profile',return_value={}), \
                 mock.patch.object(m.xyz,'validate_tmc_manifest',return_value={}), \
                 mock.patch.object(m,'final_status_issues',return_value=[]), \
                 mock.patch.object(m.replay,'analyze',return_value={'mocked_not_physical':True}), \
                 mock.patch.object(m.subprocess,'Popen',side_effect=start), mock.patch.object(m.time,'sleep'):
                # TMC helper's second argument is decoded by caller, so this file
                # is installed inside startup mock immediately.
                original=start
                def start_files(*a,**kw):
                    obj=original(*a,**kw)
                    (obj.directory/'shared-profile.json').write_text('{}')
                    return obj
                with mock.patch.object(m.subprocess,'Popen',side_effect=start_files):
                    code=m.run(args)
            result=json.loads((root/'runs'/'mock'/'thermal-observation.json').read_text())
            return code,result

    def test_success_keeps_separate_facts(self):
        code,result=self.execute('success')
        self.assertEqual(code,0,result.get('error',result))
        self.assertTrue(result['regulation_criterion_met'])
        self.assertEqual(len(result['startup_error_lines']),5)
        self.assertEqual(len(result['known_auxiliary_startup_errors']),5)
        self.assertTrue(result['zero_response_verified'])
        self.assertTrue(result['actual_heater_off_observed'])
        self.assertTrue(result['physical_cooling_observed'])
        self.assertFalse(result['pid_calibration_completed'])
        stages=[r['stage'] for r in result['requests']]
        self.assertEqual(stages.count('target'),1);self.assertEqual(stages.count('zero'),1)
        self.assertEqual(stages.count('ready'),1)

    def test_bed_separate_invocation(self):
        code,result=self.execute('success','bed')
        self.assertEqual(code,0,result)
        self.assertEqual([r['method'] for r in result['requests'] if r['stage']=='target'],['HotbedPreheating'])
        self.assertEqual(result['target_c'],60)

    def test_sensor_fault_normal_zero(self):
        code,result=self.execute('sensor-fault')
        self.assertEqual(code,2,result)
        self.assertTrue(result['zero_response_verified'])
        self.assertIn('sensor/model fault',result['heat_stop_criterion'])

    def test_hard_cap_without_zero_response(self):
        code,result=self.execute('zero-stall')
        self.assertEqual(code,2,result)
        self.assertFalse(result['zero_response_verified'])
        self.assertEqual(result['phase'],'hard_heat_cap')

    def test_valid_zero_baseline_waits_for_new_real_reading(self):
        code,result=self.execute('baseline-zero-then-valid')
        self.assertEqual(code,0,result)
        self.assertEqual(len(result['native_baseline_wait_samples']),1)
        stages=[r['stage'] for r in result['requests']]
        self.assertLess(stages.index('status002'),stages.index('target'))
        status=[r['response'] for r in result['requests'] if r['stage']=='status002'][0]
        self.assertEqual(status['transport_exit_status'],20)
        self.assertFalse(status['transport_complete'])
        self.assertFalse(status['unary_rpc_completion'])
        self.assertFalse(status['remote_cancellation_acknowledged'])
        self.assertEqual(status['selected_native_message_index'],2)

    def test_permanently_zero_native_baseline_never_heats(self):
        code,result=self.execute('baseline-zero')
        self.assertEqual(code,2,result)
        self.assertNotIn('target',[r['stage'] for r in result['requests']])
        self.assertIn('baseline',result['error'])
        self.assertEqual(result['baseline_successful_snapshots'],3)

    def test_unknown_startup_blocks_all_rpc_and_heat(self):
        code,result=self.execute('unknown-startup')
        self.assertEqual(code,2,result)
        self.assertEqual(result['requests'],[])
        self.assertEqual(result['phase'],'startup_native_failure')

    def test_uncertain_target_stops_without_retry_or_zero_claim(self):
        code,result=self.execute('timeout')
        self.assertEqual(code,2)
        self.assertFalse(result['zero_response_verified'])
        self.assertNotIn('zero',[r['stage'] for r in result['requests']])
        self.assertIn('transport',result['error'])

    def test_native_fault_uses_normal_zero_once(self):
        code,result=self.execute('fault')
        self.assertEqual(code,2,result)
        self.assertTrue(result['zero_response_verified'])
        self.assertTrue(result['native_failure_lines'])
        self.assertEqual([r['stage'] for r in result['requests']].count('zero'),1)

    def test_no_rise_reaches_bound_and_normal_zero(self):
        code,result=self.execute('no-rise')
        self.assertEqual(code,2,result)
        self.assertFalse(result['regulation_criterion_met'])
        self.assertIn('232-second',result['heat_stop_criterion'])
        self.assertTrue(result['zero_response_verified'])
        self.assertLessEqual(result['last_controller_virtual_time_ns'],270*m.NS)


if __name__=='__main__':unittest.main()
