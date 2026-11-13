from test_runtime import run_mock
from test_cold_release import o, PROFILE, copy, unittest, patch
import csv, io

def probe(label,pin,edges):
    model=o.physical.Probe(label,pin)
    lines=['# PASSIVE GPIO EDGE TRACE v1; source-local virtual timestamps; no SyncTime or signal writes','virtual_time_s,sequence,kind,label,pin,level']
    lines += [f'{t},{i},{"initial" if i==0 else "edge"},{label},{pin},{level}' for i,(t,level) in enumerate(edges)]
    model.consume(('\n'.join(lines)+'\n').encode())
    return model

def probes():
    return {'nozzle-z-probe-edges.csv':probe('nozzle_PA7_Z',7,[(0,0),(1,1),(2,0)]),'main-z-probe-edges.csv':probe('main_PB2_Z',2,[(0,0),(1,1),(2,0)])}

class ProbeContactTests(unittest.TestCase):
    def test_unchanged_bytes_skip_parse_but_keep_tail_and_freshness(self):
        from test_cold_release import row,csv_data
        data=csv_data([row(0,0)])
        model=o.physical.Physical();model.consume(data,0)
        with patch.object(o.physical.csv,'DictReader',side_effect=AssertionError('must not reparse')):
            model.consume(data,1)
            with self.assertRaises(ValueError):model.consume(data,100_000_001)
            model.consume(data,1_000_000_000,require_fresh=False)
        partial=data+b'partial';model.consume(partial,1_000_000_000,require_fresh=False)
        with self.assertRaises(ValueError):model.consume(partial,1_000_000_000,final=True,require_fresh=False)

    def test_startup_gap_only_then_sustained_cadence(self):
        from test_cold_release import row,csv_data
        model=o.physical.Physical()
        data=[row(0,0),row(1,2)]
        model.consume(csv_data(data),2_000_000_000)
        self.assertFalse(model.motion_ready())
        data += [row(i,2+(i-1)*.01) for i in range(2,28)]
        model.consume(csv_data(data),2_260_000_000)
        self.assertTrue(model.motion_ready())
        with self.assertRaises(ValueError):model.consume(csv_data(data+[row(28,3)]),3_000_000_000)

    def test_missing_start_and_partial_final_physical(self):
        from test_cold_release import row,csv_data
        with self.assertRaises(ValueError):o.physical.Physical().consume(csv_data([row(1,0)]),0)
        data=csv_data([row(0,0)])+b'1,0.01,partial'
        model=o.physical.Physical();model.consume(data,0)
        self.assertEqual(len(model.rows),1)
        with self.assertRaises(ValueError):model.consume(data,0,final=True)

    def test_fresh_pair_old_unpaired_reordered_and_timing(self):
        models=probes();floors={key:1 for key in models}
        self.assertEqual(o.physical.paired_z_pulses(models,floors),1)
        for floor in (0,3,4):
            with self.assertRaises(ValueError):o.physical.paired_z_pulses(models,{key:floor for key in models})
        for mutation in ('missing','level','time','old'):
            bad=copy.deepcopy(models)
            dest=bad['main-z-probe-edges.csv'].rows
            if mutation=='missing':dest.pop()
            if mutation=='level':dest[1]['level']='0'
            if mutation=='time':dest[1]['virtual_time_s']='1.0000011'
            if mutation=='old':dest[1]['virtual_time_s']='-1'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):o.physical.paired_z_pulses(bad,floors)

    def test_extra_edge_after_freeze(self):
        model=probes()['nozzle-z-probe-edges.csv'];model.arm()
        with self.assertRaises(ValueError):model.consume(model.prefix+b'3,3,edge,nozzle_PA7_Z,7,1\n')
        with self.assertRaises(ValueError):model.consume(model.prefix[:-1],final=True)

    def test_final_health_exact_empty_error_and_counters(self):
        models=probes()
        text=''
        for board in ('nozzle','main'):
            text+=f'COLD_PROBE_{board}_BEGIN\r\r\nTrue\r\r\nFalse\r\r\n0x0003\r\r\n0x0000\r\r\n0x0002\r\r\nFalse\r\r\n\r\r\nCOLD_PROBE_{board}_END\r\r\n'
        text+='COLD_CONTACT_BEGIN\nFalse\n4\n0\n\nCOLD_CONTACT_END\n'
        self.assertEqual(o.physical.final_health(text,models)['contact_rows'],4)
        for bad in (text.replace('0x0000','0x0001',1),text.replace('False\r\r\n\r\r\n','False\r\r\n',1),text.replace('False\r\r\n\r\r\n','False\r\r\nerror\r\r\n',1),text+text,text.replace('COLD_PROBE_main_BEGIN','echo "COLD_PROBE_main_BEGIN"')):
            with self.assertRaises(ValueError):o.physical.final_health(bad,models)

    def test_contact_release_transition_not_sampling_claim(self):
        header=','.join(o.physical.CONTACT_HEADER)+'\n'
        rows='0,0,0,0,initial,0,0,0,0,0\n0,0,0,1,initial,0,0,0,0,0\n0,0,0,2,initial,1,0,0,-10.1,0.01\n2,1,2,2,transition,0,0,0,-9.9,0\n'
        self.assertTrue(o.physical.validate_contacts((header+rows).encode(),1,4))
        bads=[(rows,3,4),(rows+'3,2,3,2,transition,1,0,0,-10.1,0.01\n',1,5),(rows.replace('transition,0','transition,1'),1,4)]
        for data,start,count in bads:
            with self.assertRaises(ValueError):o.physical.validate_contacts((header+data).encode(),start,count)

class FinalReportTests(unittest.TestCase):
    def test_45_second_history_report_stays_below_limit(self):
        from test_cold_release import row,csv_data
        import json
        model=o.physical.Physical()
        history=[row(i,i/100) for i in range(4001)]
        for item in history:
            for axis in 'xyz':item[axis+'_angle_rad']='1234.1234567890123'
        model.consume(csv_data(history[:901]),9_000_000_000)
        motion_window=model.latest_window()
        self.assertGreater(motion_window[0]['sequence'],1)
        self.assertLessEqual(len(motion_window),27)
        model.consume(csv_data(history),40_000_000_000)
        model.arm(39.)
        self.assertLessEqual(len(model.prerelease_rows),27)
        for i in range(4001,4501):
            delta=min(1.,(i-4000)/100)
            z=-10.1+delta
            item=row(i,i/100,z,max(0.,-z-10)*20,1. if delta<1 else 0.)
            for axis in 'xyz':item[axis+'_angle_rad']='1234.1234567890123'
            history.append(item)
        model.consume(csv_data(history),45_000_000_000)
        self.assertEqual(len(model.rows),4501)
        self.assertEqual(len(model.release_rows),500)
        self.assertTrue(model.complete())
        report=copy.deepcopy(self.good)
        report['initial_trace_window']=motion_window
        report['physical']=model.summary()
        size=len((json.dumps(report,indent=2,allow_nan=False)+'\n').encode())
        self.assertLess(size,800*1024)
        self.assertEqual(len(model.rows),4501)  # No raw/full history discarded.
        print('Representative45s report bytes:',size)

    def test_mocked_artifact_replay_and_corruption(self):
        def verify(directory,report):
            self.assertTrue(o.validate_artifacts(directory,report))
            for filename in ('release.request.bin','physical-state.csv'):
                path=directory/filename;before=path.read_bytes();path.write_bytes(before+b'partial')
                with self.subTest(filename=filename),self.assertRaises(ValueError):o.validate_artifacts(directory,report)
                path.write_bytes(before)
        run_mock(artifact_check=verify)

    @classmethod
    def setUpClass(cls):cls.good,_=run_mock()
    def test_valid_reparse(self):
        with patch.object(o,'ROOT',PROFILE):self.assertTrue(o.validate_final_report(self.good))
    def test_mutations_fail_closed(self):
        for mutation in ('count','missing_request','repeat_stage','wire','gcode','claim','uncertain','generation','rail','hold','source_gap','extra_probe','old_probe','shell','export'):
            report=copy.deepcopy(self.good)
            if mutation=='count':report['request_count']=11
            elif mutation=='missing_request':report['requests'].pop()
            elif mutation=='repeat_stage':report['requests'][4]['stage']='home_x'
            elif mutation=='wire':report['requests'][8]['result']['wire_hex']+='00'
            elif mutation=='gcode':report['release_gcode']='G91\nG1 Z2 F60\nM400\nG90'
            elif mutation=='claim':report['physical_completion_proven']=True
            elif mutation=='uncertain':report['requests'][8]['queue_outcome']='uncertain'
            elif mutation=='generation':report['generation_attempts'].pop()
            elif mutation=='rail':report['rails'][2]['native_completion']=None
            elif mutation=='hold':report['physical']['release_rows']=report['physical']['release_rows'][:1]
            elif mutation=='source_gap':report['physical']['release_rows'][1]['observation_time_s']+=.1
            elif mutation=='extra_probe':report['probes']['main-z-probe-edges.csv']['armed_count']-=1
            elif mutation=='old_probe':report['z_probe_floors']['main-z-probe-edges.csv']=3
            elif mutation=='shell':report['batches']=[x for x in report['batches'] if x['kind']!='shell']
            elif mutation=='export':report['final_exports_verified']=False
            with self.subTest(mutation=mutation),patch.object(o,'ROOT',PROFILE),self.assertRaises((ValueError,KeyError)):
                o.validate_final_report(report)

if __name__=='__main__':unittest.main(verbosity=2)
