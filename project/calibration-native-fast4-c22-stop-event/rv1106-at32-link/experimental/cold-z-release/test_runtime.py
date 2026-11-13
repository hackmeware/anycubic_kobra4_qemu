"""Mocked adapter tests: synthetic files only; launch never starts a process."""
from test_cold_release import *

class FakeBoundary:
    def __init__(self):
        self.p = types.SimpleNamespace(**p.__dict__)
        self.p.shell_check_command_batch=lambda token:'SHELL '+token+'\n'
        self.p.verify_shell_check=lambda text,token: {'verified':True} if 'SHELL_DONE '+token+'\n' in text else None
    log_command_batch=b.log_command_batch
    validate_profile=lambda self,directory: {'mock':True}
    packet=b.packet
    build=b.build
    verify_wire=b.verify_wire
    mode=b.mode
    def commands(self,stage,token,client):return 'RPC '+stage+' '+token+'\n'
    def capture(self,stage,token,text):
        if 'RPC_DONE '+token+'\n' not in text:return None
        wire=READY_WIRE if stage=='ready' else STATUS_WIRE if self.mode(stage)=='GetStatus' else unary()
        return dict(self.verify_wire(stage,wire), physical_completion_proven=False,wire_hex=wire.hex(),wire_sha256=__import__('hashlib').sha256(wire).hexdigest(),guest_uptime_seconds=[1.,2.],client_exit_status=5 if self.mode(stage)=='GetStatus' else 0,transport_exit_status=5 if self.mode(stage)=='GetStatus' else 0)

class FakeNozzle:
    def __init__(self):self.rows=[];self.last_growth_shared_ns=None
    def consume(self,data,now):
        self.rows=[{'time_us':str(now//1000)}];self.last_growth_shared_ns=now
    def summary(self):return {'available':bool(self.rows)}

class Harness:
    def __init__(self,root,bad=None):
        self.root=root;self.bad=bad;self.t=0.;self.rows=[];self.release=None;self.commands=[];self.wall=0.
    def monotonic(self):return self.wall
    def launch(self,args,env):
        self.args=args;self.env=env;self.d=self.root/'runs'/args[1];self.d.mkdir(parents=True)
        self.console='COUPLED_STARTUP_COMMANDS_DONE\n[1970-01-01 00:00:00.001] [info] [1] Printer is ready at 0.001.\n'
        if self.bad=='late_ready':self.console='COUPLED_STARTUP_COMMANDS_DONE\n'
        (self.d/'console-input.commands').write_text('')
        (self.d/'nozzle-thermal-live.csv').write_text('synthetic')
        self.sample()
        for filename,label,pin in [('nozzle-z-probe-edges.csv','nozzle_PA7_Z',7),('main-z-probe-edges.csv','main_PB2_Z',2)]:
            (self.d/filename).write_text('# PASSIVE GPIO EDGE TRACE v1; source-local virtual timestamps; no SyncTime or signal writes\nvirtual_time_s,sequence,kind,label,pin,level\n0,0,initial,'+label+','+str(pin)+',0\n')
        return self
    def poll(self):return None
    def sample(self):
        z=-10.1; force=2.;v=0.
        if self.release is not None:
            dz=min(1.,max(0,self.t-self.release));z+=dz;force=max(0,-z-10)*20;v=1. if dz<1 else 0.
            if self.bad=='wrong_direction':z=-10.2;force=4;v=-1
        self.rows.append(row(len(self.rows),self.t,z,force,v))
        (self.d/'physical-state.csv').write_bytes(csv_data(self.rows))
        (self.d/'console.bin').write_text(self.console)
        (self.d/'virtual-time.json').write_text(json.dumps({'schema':1,'source':'renode-shared-mcu','enabled':True,'time_went_backwards':False,'virtual_time_ns':round(self.t*1e9),'sequence':len(self.rows),'epoch':'mock'}))
    def sleep(self,seconds):
        self.wall+=.1;self.t=round(self.t+.01,8)
        if self.bad=='late_ready' and self.t>=6 and 'Printer is ready' not in self.console:self.console+='[1970-01-01 00:00:00.001] [info] [1] Printer is ready at 0.001.\n'
        self.sample()
    def wait(self,timeout):
        if self.bad=='cleanup':raise o.subprocess.TimeoutExpired('mock',timeout)
        self.sleep(.1)
        status={'rows_written':len(self.rows),'dropped_rows':0,'error_count':0,'capacity_reached':False,'last_error':'','stopped':True}
        (self.d/'physical-state-status.json').write_text(json.dumps(status))
        return 0
    def owner(self,path):
        harness=self
        class Owner:
            pending=None
            def check(self):pass
            def close(self):pass
            def complete(self,label):
                if self.pending!=label:raise ValueError('mock mismatch')
                self.pending=None
            def append_once(self,label,commands):
                if self.pending is not None:raise ValueError('mock overlapping append')
                self.pending=label;harness.commands.append(commands)
                parts=commands.split();kind=parts[0]
                if harness.bad=='uncertain' and kind=='RPC':raise OSError('mock uncertain append')
                if kind=='SHELL':harness.console+='SHELL_DONE '+parts[1]+'\n'
                elif commands.startswith("AMBIENT_MARKER=$(printf '"):
                    # Consume the REAL cold-only formatter; never mock its label
                    # allowlist or marker-encoding contracts. No shell executes.
                    import re
                    encoded=commands.split("'",2)[1]
                    prefix=''.join(chr(int(value,8)) for value in re.findall(r'\\([0-7]{3})',encoded))
                    if not re.fullmatch(r'AMB_[a-f0-9]{20}_L(?:[1-9]|[1-9][0-9]|1[0-9]{2}|200)',prefix):raise ValueError('invalid real log prefix')
                    harness.console+=prefix+'_B\nMOCK_LOG\n'+prefix+'_E\n'
                else:
                    stage,token=parts[1:];harness.console+='RPC_DONE '+token+'\n'
                    if stage.startswith('home_'):
                        axis=stage[-1];stamp=100+len(harness.commands)
                        harness.console+=f'[1970-01-01 00:00:01.{stamp:03d}] [info] [1] Home Rail Begin - stepper: {axis}\n'
                        if harness.bad!='missing_rail':harness.console+=f'[1970-01-01 00:00:01.{stamp+1:03d}] [info] [1] Home Rail Complete - stepper: {axis}\n'
                    if stage=='home_z':
                        for filename,label,pin in [('nozzle-z-probe-edges.csv','nozzle_PA7_Z',7),('main-z-probe-edges.csv','main_PB2_Z',2)]:
                            with (harness.d/filename).open('a') as f:f.write(f'{harness.t},1,edge,{label},{pin},1\n{harness.t+.001},2,edge,{label},{pin},0\n')
                    if stage=='release':harness.release=harness.t
                (harness.d/'console.bin').write_text(harness.console)
        return Owner()

def run_mock(bad=None, artifact_check=None):
    temp=tempfile.TemporaryDirectory();root=Path(temp.name);h=Harness(root,bad)
    mocked=types.ModuleType('mockbase');mocked.__dict__.update(base.__dict__)
    mocked.ConsoleOwner=h.owner;mocked.PassiveNozzle=FakeNozzle;mocked.verify_classification_baseline=lambda:None;mocked.final_passive=lambda *args:{'final_export_verified':True}
    def probe_final(directory,trace,probes,record,base):record['no_extra_probe_pulse']=True;record['trace_health']={'mock':True}
    with patch.object(o.cp,'load',return_value=(FakeBoundary(),mocked)),patch.object(o,'ROOT',root),patch.object(o,'verify_probe_exports',probe_final),patch.object(o,'validate_model_exports',return_value={'mock':True}):
        result=o.run(root,'mock','/tmp/unused',h)
        if artifact_check is not None:artifact_check(h.d,result)
    temp.cleanup();return result,h

class RuntimeTests(unittest.TestCase):
    def test_late_ready_passes_L21_with_real_formatter(self):
        result,h=run_mock('late_ready')
        self.assertTrue(result['success'],result.get('error'))
        logs=[batch for batch in result['batches'] if batch['kind']=='log']
        self.assertGreaterEqual(len(logs),21)
        self.assertTrue(any(batch['label'].endswith('_L21') for batch in logs))
        self.assertTrue(all(not command.startswith('LOG ') for command in h.commands))

    def test_complete_fixed_ten_mocked(self):
        result,h=run_mock()
        self.assertTrue(result['success'],result.get('error'))
        self.assertEqual([r['stage'] for r in result['requests']],list(o.cp.STAGES))
        self.assertTrue(result['virtual_release_proven'])
        self.assertFalse(result['physical_completion_proven'])
        self.assertEqual(sum(c.startswith('RPC release ') for c in h.commands),1)
        self.assertEqual(h.env['PASSIVE_MOTOR_TRACE'],'0')
    def test_uncertain_append_never_retry(self):
        result,h=run_mock('uncertain')
        self.assertFalse(result['success']);self.assertEqual(result['request_count'],1)
        self.assertEqual(sum(c.startswith('RPC ') for c in h.commands),1)
    def test_wrong_direction_stops_without_fallback(self):
        result,h=run_mock('wrong_direction')
        self.assertFalse(result['success']);self.assertEqual(result['request_count'],9)
        self.assertIn('Wrong-sign',result['error'])
    def test_bounded_cleanup_failure(self):
        result,h=run_mock('cleanup')
        self.assertFalse(result['success']);self.assertTrue(result['cleanup_timeout'])

if __name__=='__main__':unittest.main(verbosity=2)
