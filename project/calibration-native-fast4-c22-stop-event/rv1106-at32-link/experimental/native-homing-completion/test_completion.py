"""Offline acceptance/mutation tests against actual raw c2 plus source boundaries."""
import copy
import csv
import io
import json
import math
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from replay_c2 import observer_module, source_profile, replay
from test_support import c2_run_directory, fixture

o = observer_module()
PROFILE = source_profile()
RAW = c2_run_directory()
b, base = o.cp.load(PROFILE)

def row(i, t, z=-9., force=0., velocity=0., x=0., y=0.):
    raw = {'sequence': str(i), 'observation_time_s': str(t)}
    for a in 'xyz':
        raw.update({a+'_state_time_s':str(t), a+'_angle_rad':'0', a+'_relative_mm':str({'x':x,'y':y,'z':z}[a]),
                    a+'_velocity_rad_s':str(velocity*2*math.pi/8 if a=='z' else 0),
                    a+'_contact_torque_nm':str(force*.008/(2*math.pi) if a=='z' else 0), a+'_bridge_enabled':'1'})
    raw.update(z_bed_clearance_mm=str(z+10),z_compression_mm=str(max(0,-z-10)),z_contact_force_n=str(force),z_contact_nonzero=str(int(force!=0)))
    return raw

def data(rows):
    buf=io.StringIO(); w=csv.DictWriter(buf,fieldnames=o.physical.HEADER,lineterminator='\n');w.writeheader();w.writerows(rows)
    return buf.getvalue().encode()

def anchor(status=.3):
    return {'home_z_queue_source_s':.1,'probe_last_edge_source_s':.2,
            'native_complete_observed_shared_ns':250_000_000,'status_z_completed_shared_ns':round(status*1e9),
            'status_z_completed_source_s':status}

def trace_until(last=30, **kw):
    rows=[row(i,i/100,**kw) for i in range(last+1)]
    trace=o.physical.Physical();trace.consume(data(rows),last*10_000_000)
    return trace,rows

def probes():
    result={}
    for fn,label,pin in [('nozzle-z-probe-edges.csv','nozzle_PA7_Z',7),('main-z-probe-edges.csv','main_PB2_Z',2)]:
        model=o.physical.Probe(label,pin);model.consume((RAW/fn).read_bytes(),final=True);result[fn]=model
    return result

class ActualHealthTests(unittest.TestCase):
    def setUp(self):
        self.raw=(RAW/'renode.log').read_bytes().decode('utf-8'); self.probes=probes()
        self.clean=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',self.raw).replace('\r','')
    def test_actual_raw_echoed_final_envelopes(self):
        health=o.physical.final_health(self.raw,self.probes)
        self.assertEqual(health,{'nozzle':{'rows':9,'edges':8,'drops':0,'stopped':True},'main':{'rows':9,'edges':8,'drops':0,'stopped':True},'contact_rows':21})
    def test_exact_response_only_equivalent(self):
        response='\n'.join(line for line in self.clean.split('\n') if not re.fullmatch(r'\((nozzle|main|motor)\) (sysbus\.(zProbeEdges|electromechanicalPlant) .+|echo "COLD_.+_END")',line))
        self.assertEqual(o.physical.final_health(response,self.probes),o.physical.final_health(self.raw,self.probes))
    def test_echo_mutations_rejected(self):
        target='(nozzle) sysbus.zProbeEdges Enabled\nTrue\n'
        self.assertIn(target,self.clean)
        mutations=[self.clean.replace(target,target.replace('(nozzle)','(main)'),1),
                   self.clean.replace(target,target.replace('Enabled','OtherGetter'),1),
                   self.clean.replace(target,'True\n',1), self.clean.replace(target,target+target,1),
                   self.clean.replace(target,target.replace('True','False'),1),
                   self.clean.replace(target,target.replace('True','Error'),1),
                   self.clean.replace('(nozzle) sysbus.zProbeEdges Stop\n','',1),
                   self.clean.replace('(nozzle) sysbus.zProbeEdges Stop\n','(nozzle) sysbus.zProbeEdges Stop\nFalse\n',1),
                   self.clean.replace('(nozzle) sysbus.zProbeEdges LastError\n\n','(nozzle) sysbus.zProbeEdges LastError\nwrite failed\n',1),
                   self.clean.replace('(nozzle) sysbus.zProbeEdges LastError\n\n','(nozzle) sysbus.zProbeEdges LastError\n',1),
                   self.clean.replace('(nozzle) echo "COLD_PROBE_nozzle_END"\n','(nozzle) echo "COLD_PROBE_nozzle_END"\ntrailing\n',1),
                   self.clean.replace('COLD_PROBE_nozzle_BEGIN\n','COLD_PROBE_nozzle_BEGIN\nCOLD_PROBE_nozzle_BEGIN\n',1),
                   self.clean.replace('\nCOLD_PROBE_main_END\n','\nMISSING_END\n',1),
                   re.sub(r'(\(motor\) sysbus.electromechanicalPlant ContactDroppedRows\n)[^\n]+',r'\g<1>1',self.clean)]
        for index,mutated in enumerate(mutations):
            with self.subTest(index=index),self.assertRaises(ValueError):o.physical.final_health(mutated,self.probes)
    def test_counters_capacity_and_integer_grammar(self):
        for getter,values in [('RowsWritten',['0','8','10','+9','09','nan','9 extra']),('DroppedRows',['1','-1','0.0']),('EdgeCount',['7','9']),('CapacityReached',['True','false']),('LastError',['None','error'])]:
            match=re.search(r'\(nozzle\) sysbus.zProbeEdges '+getter+r'\n([^\n]*)\n',self.clean)
            self.assertIsNotNone(match)
            for value in values:
                mutated=self.clean[:match.start(1)]+value+self.clean[match.end(1):]
                with self.subTest(getter=getter,value=value),self.assertRaises(ValueError):o.physical.final_health(mutated,self.probes)
    def test_pulse_delay_exact_forward_1us_and_post_freeze(self):
        saved=json.loads((RAW/'cold-release-observation.json').read_text())
        self.assertEqual(o.physical.paired_z_pulses(self.probes,saved['z_probe_floors']),4)
        model=self.probes['main-z-probe-edges.csv'];orig=model.rows[1]['virtual_time_s']
        for stamp in ['29.220819','29.22082','29.220822']:
            model.rows[1]['virtual_time_s']=stamp
            with self.subTest(stamp=stamp),self.assertRaises(ValueError):o.physical.paired_z_pulses(self.probes,saved['z_probe_floors'])
        model.rows[1]['virtual_time_s']=orig
        model.arm()
        with self.assertRaises(ValueError):model.consume(model.prefix+b'36,9,edge,main_PB2_Z,2,1\n',final=True)

class PhysicalBoundaryTests(unittest.TestCase):
    def test_no_completion_from_initial_clearance_or_native_log(self):
        trace,rows=trace_until(100)
        self.assertTrue(trace.motion_ready());self.assertFalse(trace.complete())
        trace.arm_completion(anchor(.3));self.assertTrue(trace.complete())
        self.assertEqual(trace.clear_start,.2)
    def test_half_second_exact_and_native_status_gates(self):
        trace,rows=trace_until(69);trace.arm_completion(anchor(.3));self.assertFalse(trace.complete())
        rows.append(row(70,.7));trace.consume(data(rows),700_000_000)
        # Decimal float subtraction may be just under .5; strict >= means next sample qualifies.
        rows.append(row(71,.71));trace.consume(data(rows),710_000_000);self.assertTrue(trace.complete())
        with self.assertRaises(ValueError):trace.arm_completion(anchor(.3))
    def test_automatic_motion_may_precede_status_z(self):
        trace,rows=trace_until(80);trace.arm_completion(anchor(.8))
        self.assertTrue(trace.complete());self.assertEqual(trace.clear_start,.2)
        self.assertLess(trace.clear_start,trace.anchor['status_z_completed_source_s'])
    def test_anchor_mutations(self):
        for key,value in [('home_z_queue_source_s',.2),('probe_last_edge_source_s',.4),('native_complete_observed_shared_ns',400_000_000),('status_z_completed_source_s',.31),('status_z_completed_source_s',float('nan'))]:
            trace,_=trace_until();a=anchor();a[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):trace.arm_completion(a)
        trace,_=trace_until()
        with self.assertRaises(ValueError):trace.arm_completion({})
    def test_stable_xy_range_not_just_final_position(self):
        trace,rows=trace_until();trace.arm_completion(anchor())
        for i in range(31,82):rows.append(row(i,i/100,x=.06 if i==50 else 0))
        trace.consume(data(rows),810_000_000);self.assertFalse(trace.complete())
        for i in range(82,103):rows.append(row(i,i/100))
        trace.consume(data(rows),1_020_000_000);self.assertTrue(trace.complete())
    def test_bad_later_sample_after_readiness_is_fatal(self):
        for kw in [{'velocity':.05},{'z':-9.51},{'x':.051},{'z':-10.01,'force':.2}]:
            trace,rows=trace_until(80);trace.arm_completion(anchor())
            with self.subTest(kw=kw),self.assertRaises(ValueError):trace.consume(data(rows+[row(81,.81,**kw)]),810_000_000)
    def test_no_recontact_after_first_clear_before_ready(self):
        trace,rows=trace_until();trace.arm_completion(anchor())
        with self.assertRaises(ValueError):trace.consume(data(rows+[row(31,.31,z=-10.01,force=.2)]),310_000_000)
    def test_velocity_and_clearance_boundaries(self):
        for kw,expected in [({'z':-9.5},True),({'z':-9.500001},False),({'velocity':.049999},True),({'velocity':.05},False),({'velocity':-.05},False),({'velocity':-.049999},True)]:
            trace,_=trace_until(80,**kw);trace.arm_completion(anchor())
            with self.subTest(kw=kw):self.assertEqual(trace.complete(),expected)
    def test_missing_gap_stale_future_and_truncation(self):
        trace,rows=trace_until()
        for now in [401_000_000]:
            with self.subTest(now=now),self.assertRaises(ValueError):trace.fresh(now)
        for candidate in [row(32,.31),row(31,.33),row(31,.3)]:
            t,old=trace_until()
            with self.subTest(candidate=candidate),self.assertRaises(ValueError):t.consume(data(old+[candidate]),330_000_000)
        with self.assertRaises(ValueError):trace.consume(data(rows[:-1]),300_000_000)
        with self.assertRaises(ValueError):trace.consume(data(rows)+b'1',300_000_000,final=True)
    def test_source_scalar_age_geometry_force(self):
        for key,value in [('z_state_time_s','-.001'),('z_state_time_s','.000002'),('z_relative_mm','nan'),('z_bed_clearance_mm','3'),('z_contact_nonzero','true'),('z_contact_force_n','6')]:
            raw=row(0,0);raw[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):o.physical.Physical.parse(raw)
    def test_initial_quarter_second_and_final_status(self):
        t,_=trace_until(25);self.assertFalse(t.motion_ready())
        t,_=trace_until(26);self.assertTrue(t.motion_ready())
        status={'rows_written':27,'dropped_rows':0,'error_count':0,'capacity_reached':False,'last_error':'','stopped':True}
        o.physical.validate_status(status,27,final=True)
        for k,v in [('rows_written',28),('dropped_rows',1),('error_count',1),('capacity_reached',True),('last_error','fail'),('stopped',False)]:
            bad=dict(status);bad[k]=v
            with self.subTest(key=k),self.assertRaises(ValueError):o.physical.validate_status(bad,27,final=True)

class ContractsAndReplayTests(unittest.TestCase):
    def test_exact_eight_real_packets_and_commands(self):
        old=json.loads((RAW/'cold-release-observation.json').read_text())
        self.assertEqual(list(o.cp.STAGES),[r['stage'] for r in old['requests']])
        for stage in o.cp.STAGES:
            packet,client=b.build(stage)
            self.assertEqual(packet,(RAW/(stage+'.request.bin')).read_bytes())
            self.assertEqual(b.p.load_helpers()[0].extract_packet(client),packet)
            self.assertIn('timeout -t 5',b.commands(stage,'a'*20,client))
            for forbidden in [b'RunGcodeScript',b'StartPrint',b'G91',b'M104',b'M140']:self.assertNotIn(forbidden,packet)
        for bad in ['release','final_status','StartPrint','home_e','G28',None]:
            with self.subTest(stage=bad),self.assertRaises(ValueError):b.packet(bad)
    def test_real_finite_formatter_all_labels(self):
        token='a'*20
        for i in range(1,201):
            text=b.log_command_batch(token,'L'+str(i));self.assertEqual(text.count('\n'),1);self.assertLessEqual(len(text.rstrip('\n')),768)
            self.assertIn('tail -100 /data/main.stdout',text);self.assertIn('tail -100 /data/logs/avata_main.log',text)
            if i<=20:self.assertEqual(text,b.p.log_command_batch(token,'L'+str(i)))
        for invalid in ['L0','L01','L201','L999','L1; true',None,1]:
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):b.log_command_batch(token,invalid)
        with self.assertRaises(ValueError):b.p.log_command_batch(token,'L21')
    def test_cold_status_default_selected_and_transport_guards(self):
        wire=fixture('get-status.response.http2.bin')
        result=b.verify_wire('status_z',wire)
        self.assertEqual(result['temperatures'][0]['nozzle']['current'],0)
        self.assertEqual(result['selected_temperatures'],{'nozzle':{'current':30,'target':0},'bed':{'current':25,'target':0}})
        for heater in ('nozzle','bed'):
            bad=copy.deepcopy(result['selected_temperatures']);bad[heater]['target']=1
            with self.subTest(heater=heater),self.assertRaises(ValueError):b.p.validate_sensor30(bad,selected=True)
        with self.assertRaises(ValueError):b.p.validate_sensor30(result['temperatures'][0],selected=True)
        for bad in [wire[:-1],wire+b'\0',(RAW/'ready.response.http2.bin').read_bytes()]:
            with self.subTest(length=len(bad)),self.assertRaises(ValueError):b.verify_wire('status_z',bad)
    def test_rail_completion_requires_fresh_ordered_begin(self):
        old='[1970-01-01 00:00:01.000] [info] [1] Older entry\n'
        begin='[1970-01-01 00:00:02.000] [info] [1] Home Rail Begin - stepper: z\n'
        end='[1970-01-01 00:00:03.000] [info] [1] Home Rail Complete - stepper: z\n'
        rail=o.Rail('z',old,100,base)
        self.assertFalse(rail.observe(old+begin,200));self.assertTrue(rail.observe(old+begin+end,300))
        for bad in [old+end,old+begin.replace('stepper: z','stepper: y'),old+begin+end+end.replace('03.000','04.000')]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):o.Rail('z',old,100,base).observe(bad,400)
    def test_pinned_sources_required(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):o.cp.load(Path(directory))

    def test_fixed_deadlines(self):
        o.deadlines(599.999,4_999_999_999,True,(0,0),True)
        for args in [(4760,1,True),(1,45_000_000_000,True),(1500,1,False),(1,18_000_000_000,False),(600,1,True,(0,0),True),(1,5_000_000_000,True,(0,0),True),(1500,1,True,(0,0),False)]:
            with self.subTest(args=args),self.assertRaises(TimeoutError):o.deadlines(*args)
    def test_actual_c2_replay_never_completion_at_native_or_status(self):
        result=replay();self.assertTrue(result['offline_replay_passed']);self.assertFalse(result['native_execution_performed'])
        self.assertFalse(result['at_home_rail_complete']['ready']);self.assertFalse(result['at_status_z_completion']['ready'])
        self.assertAlmostEqual(result['first_readiness_source_s'],34.72572384)
        self.assertAlmostEqual(result['settled_duration_s'],1.171456)
    def test_actual_contact_mutations(self):
        result=json.loads((Path(__file__).parent/'offline-c2-replay.json').read_text());a=result['anchor'];raw=(RAW/'contact-transitions.csv').read_bytes();clear=33.2
        o.physical.validate_contacts(raw,a,21,clear)
        for bad,count in [(raw[:-1],21),(raw,20),(raw+b'36,35.99999,36,2,transition,1,-7,0,-10.1,.001\n',22),(raw.replace(b'32.85031898',b'35.85031898'),21)]:
            with self.subTest(count=count),self.assertRaises(ValueError):o.physical.validate_contacts(bad,a,count,clear)

if __name__=='__main__':unittest.main(verbosity=2)
