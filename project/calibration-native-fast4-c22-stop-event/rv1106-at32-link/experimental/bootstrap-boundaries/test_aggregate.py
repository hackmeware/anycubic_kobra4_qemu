import hashlib, json, tempfile, unittest
from pathlib import Path
import aggregate

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.paths=[Path(self.temp.name)/x for x in ['a','b','c']]
        for p,mode in zip(self.paths,['legacy','segmented','legacy']):
            p.mkdir(); hashes={}
            for name in aggregate.EXPECTED_CAPTURES:
                data=bytes(0x18000) if name.endswith('-sram.bin') else b'fixture\n'
                (p/name).write_bytes(data);hashes[name]=hashlib.sha256(data).hexdigest()
            r=dict(passed=True,clean_exit=True,exit_code=0,process_group_absent=True,watchdog_stopped=True,forced_signals=[],vendor_firmware_ran=True,kind='native-prefix',mode=mode,compared_duration_ns=20000000,acknowledged_time_ns=20000000,global_quantum_ns=1000,captures_sha256=hashes)
            self.save(p/'result.json',r)
            ack=dict(schema=1,source='renode-shared-mcu-step',enabled=True,paused=True,time_went_backwards=False,epoch='fixture',virtual_time_ns=20000000,step_id=0 if mode=='legacy' else 20)
            self.save(p/'renode-step.json',ack)
            self.save(p/'acknowledgments.json',dict(actual_times_ns=[20000000] if mode=='legacy' else list(range(0,20000001,1000000)),final_ack=ack))
    def save(self,p,v):p.write_text(json.dumps(v))
    def test_valid_inventory_and_history(self):self.assertTrue(aggregate.compare(self.paths)['passed_observed_captures_only'])
    def test_missing_inventory_rejected(self):
        p=self.paths[0]/'result.json';r=json.loads(p.read_text());r['captures_sha256'].pop('main-sram.bin');self.save(p,r)
        with self.assertRaisesRegex(ValueError,'inventory'):aggregate.compare(self.paths)
    def test_changed_history_rejected(self):
        p=self.paths[1]/'acknowledgments.json';r=json.loads(p.read_text());r['actual_times_ns'][1]=2000000;self.save(p,r)
        with self.assertRaisesRegex(ValueError,'history'):aggregate.compare(self.paths)
    def test_unpaused_ack_rejected(self):
        p=self.paths[0]/'acknowledgments.json';r=json.loads(p.read_text());r['final_ack']['paused']=False;self.save(p,r)
        with self.assertRaisesRegex(ValueError,'history'):aggregate.compare(self.paths)
    def test_duplicate_leg_rejected(self):
        with self.assertRaisesRegex(ValueError,'distinct'):aggregate.compare([self.paths[0],self.paths[1],self.paths[0]])
    def test_truncated_sram_rejected_even_with_updated_hash(self):
        p=self.paths[0];(p/'main-sram.bin').write_bytes(b'x');r=json.loads((p/'result.json').read_text());r['captures_sha256']['main-sram.bin']=hashlib.sha256(b'x').hexdigest();self.save(p/'result.json',r)
        with self.assertRaisesRegex(ValueError,'Truncated'):aggregate.compare(self.paths)
if __name__=='__main__':unittest.main()
