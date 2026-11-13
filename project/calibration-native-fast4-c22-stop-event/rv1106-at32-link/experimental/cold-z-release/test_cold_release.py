"""Offline only. Pure parsers/builders and mocked runtime, no client execution."""
import copy
import csv
import io
import json
import math
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
PROFILE = HERE.parents[2]
o = types.ModuleType('cold_test_observer')
o.__file__ = str(HERE / 'observer.py')
exec(compile((HERE / 'observer.py').read_bytes(), o.__file__, 'exec'), o.__dict__)
b, base = o.cp.load(PROFILE)
p = b.p

def unary(payload=b''):
    def header(k, v):
        return b'\0' + bytes([len(k)]) + k + bytes([len(v)]) + v
    return p.frame(1, 4, 1, b'\x88' + header(b'content-type', b'application/grpc')) + p.frame(0, 0, 1, b'\0' + len(payload).to_bytes(4, 'big') + payload) + p.frame(1, 5, 1, header(b'grpc-status', b'0'))

STATUS_WIRE = (HERE / 'fixtures/get-status.response.http2.bin').read_bytes()
READY_WIRE = (HERE / 'fixtures/printer-state.response.http2.bin').read_bytes()

def row(i, t, z=-10.1, force=2., velocity=0.):
    r = {'sequence': str(i), 'observation_time_s': str(t)}
    for a in 'xyz':
        r.update({a + '_state_time_s': str(t), a + '_angle_rad': '0', a + '_relative_mm': str(z if a == 'z' else 0.), a + '_velocity_rad_s': str(velocity * 2 * math.pi / 8 if a == 'z' else 0.), a + '_contact_torque_nm': str(force * .008 / (2 * math.pi) if a == 'z' else 0.), a + '_bridge_enabled': '1'})
    r.update(z_bed_clearance_mm=str(z + 10), z_compression_mm=str(max(0, -z - 10)), z_contact_force_n=str(force), z_contact_nonzero=str(int(force != 0)))
    return r

def csv_data(rows):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=o.physical.HEADER, lineterminator='\n')
    writer.writeheader(); writer.writerows(rows)
    return stream.getvalue().encode()

class BoundaryTests(unittest.TestCase):
    def test_all_real_cold_log_labels_and_original_contract(self):
        import re
        token='0123456789abcdefabcd'
        self.assertEqual(o.cp.LOG_BATCH_LIMIT,200)
        for number in range(1,o.cp.LOG_BATCH_LIMIT+1):
            label='L'+str(number)
            command=b.log_command_batch(token,label)
            self.assertEqual(command.count('\n'),1)
            self.assertTrue(command.endswith('\n'))
            self.assertLessEqual(len(command.rstrip('\n')),768)
            self.assertEqual(command.count('tail -100 /data/main.stdout'),1)
            self.assertEqual(command.count('tail -100 /data/logs/avata_main.log'),1)
            prefix='AMB_'+token+'_'+label
            self.assertNotIn(prefix,command)
            encoded=command.split("'",2)[1]
            decoded=''.join(chr(int(value,8)) for value in re.findall(r'\\([0-7]{3})',encoded))
            self.assertEqual(decoded,prefix)
            expected_setup="AMBIENT_MARKER=$(printf '"+''.join('\\%03o'%byte for byte in prefix.encode())+"')"
            expected='; '.join([expected_setup,p._marker_line('B'),'tail -100 /data/main.stdout','tail -100 /data/logs/avata_main.log',p._marker_line('E')])+'\n'
            self.assertEqual(command,expected)
            capture=prefix+'_B\nsynthetic read-only log contents\n'+prefix+'_E\n'
            self.assertEqual(p.bounded_region(capture,prefix+'_B',prefix+'_E'),'synthetic read-only log contents\n')
            if number<=20:self.assertEqual(command,p.log_command_batch(token,label))
        with self.assertRaises(ValueError):p.log_command_batch(token,'L21')
        for label in ('L0','L00','L01','L020','L201','L999','L-1','L1\n','L1; true','F','',None,21):
            with self.subTest(label=label),self.assertRaises(ValueError):b.log_command_batch(token,label)
        for invalid in ('',token+'0','G'*20,token+'; true',None):
            with self.subTest(token=invalid),self.assertRaises(ValueError):b.log_command_batch(invalid,'L21')

    def test_fixed_packets_and_builders(self):
        for stage in o.cp.STAGES:
            packet, elf = b.build(stage)
            self.assertEqual(p.load_helpers()[0].extract_packet(elf), packet)
            self.assertIn(b'/applink.AppLinkService/', packet)
            commands = b.commands(stage, 'a' * 20, elf)
            self.assertIn('timeout -t 5', commands)
        release = b.packet('release')
        self.assertIn(b'RunGcodeScript', release)
        self.assertTrue(release.endswith(b'\x0a' + bytes([len(o.cp.SCRIPT)]) + o.cp.SCRIPT.encode()))
        for invalid in ('G28', 'StartPrint', '', 'home_e', 'getstatus'):
            with self.assertRaises(ValueError): b.packet(invalid)

    def test_actual_r7_pair_keeps_zero_then_selects_second(self):
        got = b.verify_wire('baseline', STATUS_WIRE)
        self.assertEqual(got['temperatures'][0]['nozzle']['current'], 0)
        self.assertEqual(got['selected_temperatures'], {'nozzle': {'current': 30, 'target': 0}, 'bed': {'current': 25, 'target': 0}})

    def test_empty_unary_only_and_strict_transport(self):
        self.assertTrue(b.verify_wire('release', unary())['rpc_acceptance_verified'])
        for wire in (unary(b'\x0a\0'), unary(b'\x08\0'), unary()[:-1], unary()+b'\0', STATUS_WIRE, unary()+p.frame(3,0,1,b'\0'*4)):
            with self.subTest(wire=wire.hex()[-24:]), self.assertRaises(ValueError): b.verify_wire('release', wire)
        for stage in ('home_x', 'home_y', 'home_z'):
            self.assertTrue(b.verify_wire(stage, unary())['rpc_acceptance_verified'])

    def test_targets_and_second_zero_fail(self):
        payloads = p.response_messages(STATUS_WIRE, 'GetStatus')
        self.assertNotEqual(payloads[0], payloads[1])
        for heater in ('nozzle', 'bed'):
            values = {'nozzle': {'current': 30, 'target': 0}, 'bed': {'current': 25, 'target': 0}}
            values[heater]['target'] = 1
            with self.assertRaises(ValueError): p.validate_sensor30(values, selected=False)
        with self.assertRaises(ValueError): p.validate_sensor30(p.decode_status(payloads[0]), selected=True)

    def test_source_identity_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError): o.cp.load(Path(tmp))

class PhysicalTests(unittest.TestCase):
    def prepared(self):
        trace = o.physical.Physical()
        data = [row(i, i * .01) for i in range(31)]
        trace.consume(csv_data(data), 300_000_000)
        trace.arm(0.)
        return trace, data

    def test_prerelease_and_release_hold(self):
        trace, data = self.prepared()
        for i in range(31, 133): data.append(row(i, i*.01, -9.1, 0))
        trace.consume(csv_data(data), 1_320_000_000)
        self.assertTrue(trace.complete())
        self.assertFalse(trace.summary()['host_coordinates_equated_to_physical'])

    def test_hold_not_inferred_from_one_sample(self):
        trace, data = self.prepared()
        data.append(row(31, .31, -9.1, 0))
        trace.consume(csv_data(data), 310_000_000)
        self.assertFalse(trace.complete())

    def test_release_hazards(self):
        bad = [row(31, .31, -10.2, 4), row(31, .31, -8.8, 0), row(31, .31, -10.1, 6)]
        lateral = row(31,.31,-9.1,0); lateral['x_relative_mm']='.051'; bad.append(lateral)
        for candidate in bad:
            trace, data = self.prepared()
            with self.subTest(candidate=candidate), self.assertRaises(ValueError): trace.consume(csv_data(data+[candidate]),310_000_000)

    def test_recontact_fails(self):
        trace, data = self.prepared()
        trace.consume(csv_data(data+[row(31,.31,-9.1,0)]),310_000_000)
        with self.assertRaises(ValueError): trace.consume(csv_data(data+[row(31,.31,-9.1,0),row(32,.32,-10.1,2)]),320_000_000)

    def test_precision_clock_geometry_and_loss(self):
        for key,value in [('z_relative_mm','nan'),('z_state_time_s','-0.001'),('z_state_time_s','.00001'),('z_bed_clearance_mm','1'),('z_contact_force_n','-1'),('z_contact_nonzero','true'),('z_contact_torque_nm','0')]:
            candidate=row(0,0); candidate[key]=value
            with self.subTest(key=key,value=value), self.assertRaises(ValueError): o.physical.Physical.parse(candidate)
        for seq,t in [(2,.01),(1,0),(1,-.01)]:
            trace=o.physical.Physical()
            with self.subTest(seq=seq,t=t), self.assertRaises(ValueError): trace.consume(csv_data([row(0,0),row(seq,t)]),0)
        trace, data=self.prepared()
        with self.assertRaises(ValueError): trace.consume(csv_data(data[:-1]),400_000_000)
        with self.assertRaises(ValueError): trace.fresh(500_000_000)

    def test_prerelease_ranges(self):
        for z,force,v in [(-10.001,.02,0),(-10.3,4,0),(-10.1,0,0),(-10.1,2,.05)]:
            trace=o.physical.Physical(); data=[row(i,i*.01,z,force,v) for i in range(31)]
            trace.consume(csv_data(data),300_000_000)
            self.assertFalse(trace.prerelease(0))
            with self.assertRaises(ValueError): trace.arm(0)

    def test_final_status(self):
        status={'rows_written':31,'dropped_rows':0,'error_count':0,'capacity_reached':False,'last_error':'','stopped':True}
        o.physical.validate_status(status,31,final=True)
        for k,v in [('rows_written',30),('dropped_rows',1),('error_count',1),('capacity_reached',True),('last_error','write error'),('stopped',False)]:
            bad=dict(status);bad[k]=v
            with self.subTest(k=k),self.assertRaises(ValueError):o.physical.validate_status(bad,31,final=True)

class LifecycleTests(unittest.TestCase):
    def test_fixed_environment(self):
        env=o.fixed_environment(PROFILE,'/tmp/unused-cache')
        self.assertEqual(env['PASSIVE_MOTOR_TRACE'],'0')
        self.assertEqual(env['THERMAL_PROFILE'],'none')
        self.assertEqual(env['NATIVE_NOZZLE_HEATER'],'0')
        self.assertEqual(env['Z_PROBE_PROFILE'],'synthetic-functional')
        self.assertNotIn('LD_PRELOAD',env)

    def test_exact_caps(self):
        o.deadlines(1,1,False)
        for args in [(4760,1,True),(1,45_000_000_000,True),(1500,1,False),(1,18_000_000_000,False),(1501,1,True,(1,0),False),(601,1,True,(1,0),True),(1,5_000_000_000,True,(0,0),True)]:
            with self.subTest(args=args), self.assertRaises(TimeoutError): o.deadlines(*args)

    def test_rails_exact_fresh_order(self):
        old='[1970-01-01 00:00:01.000] [info] [1] Old startup\n'
        rail=o.Rail('x',old,100,base)
        begin='[1970-01-01 00:00:02.000] [info] [1] Home Rail Begin - stepper: x\n'
        end='[1970-01-01 00:00:03.000] [info] [1] Home Rail Complete - stepper: x\n'
        self.assertFalse(rail.observe(old+begin,200))
        self.assertTrue(rail.observe(old+begin+end,300))
        with self.assertRaises(ValueError): rail.observe(old+begin+end+end.replace('03.000','04.000'),400)
        with self.assertRaises(ValueError): o.Rail('x',old,100,base).observe(old+end,200)
        with self.assertRaises(ValueError): o.Rail('x',old,100,base).observe(old+begin.replace('stepper: x','stepper: y'),200)

    def test_partial_append_never_retry_real_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'input';path.write_bytes(b'')
            owner=base.ConsoleOwner(path)
            try:
                with patch.object(base.os,'write',return_value=1), self.assertRaises(OSError): owner.append_once('rpc','hello\n')
                with self.assertRaises(ValueError): owner.append_once('rpc','hello\n')
            finally:owner.close()

    def test_incomplete_report_rejected(self):
        for report in ({},{'success':True,'phase':'verified_cold_release'},{'schema_version':1,'success':True,'phase':'verified_cold_release','launcher_exit_code':0}):
            with self.assertRaises(ValueError):o.validate_final_report(report)

if __name__ == '__main__': unittest.main(verbosity=2)
