"""Offline only: fake acknowledgement producer and mocked launcher processes."""
import json
import os
from pathlib import Path
import re
import signal
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_link
from renode_bootstrap import bootstrap, bounded_send
from renode_stepper import RenodeStepper, StepError
from shared_mcu import prepare

VALID=['--shared-mcus','--clock-coupled','--clock-source','qom-deadline',
       '--clock-lockstep','--qemu-icount-shift','0','--renode-bootstrap','segmented']

class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.ack=self.root/'ack.json'
        self.output=self.root/'bootstrap.json';self.proc=Mock();self.proc.poll.return_value=None
        self.value=dict(schema=1,source='renode-shared-mcu-step',enabled=True,paused=True,
                        time_went_backwards=False,epoch='epoch',step_id=0,virtual_time_ns=123000)
        self.write();self.pending_hook=lambda:None
        self.stepper=RenodeStepper(self.proc,self.ack,self.send,timeout=.01)
    def write(self):self.ack.write_text(json.dumps(self.value))
    def send(self,command):
        step=int(re.search(rb'PublishStep .* (\d+)\n',command)[1])
        self.pending_hook()
        self.value.update(step_id=step,virtual_time_ns=123000+step*1000000);self.write()
    def report(self):return json.loads(self.output.read_text())
    def test_exact_second_and_monotonic_handoff(self):
        result=bootstrap(self.stepper,lambda:None,self.output)
        self.assertIs(result,self.stepper);self.assertEqual(result.step_id,1000)
        self.assertEqual(result.time_ns-123000,1000000000)
        self.assertEqual(self.report()['status'],'complete')
        result.step();self.assertEqual(result.step_id,1001)
    def test_stop_during_pending_step_waits_for_ack(self):
        stop=[];self.pending_hook=lambda:stop.append(True)
        def check():
            if stop:raise run_link.StartupAborted('stop requested')
        with self.assertRaises(run_link.StartupAborted):bootstrap(self.stepper,check,self.output)
        report=self.report();self.assertEqual(report['completed_steps'],1)
        self.assertEqual(report['last_confirmed_step_id'],1)
        self.assertIsNone(report['uncertain_in_flight_step_id'])
        self.proc.send_signal.assert_not_called()
    def test_stop_before_first_step(self):
        with self.assertRaises(run_link.StartupAborted):
            bootstrap(self.stepper,Mock(side_effect=run_link.StartupAborted('stop')),self.output)
        self.assertEqual(self.report()['completed_steps'],0)
    def test_timeout_epoch_delta_fail_closed(self):
        for mode in ('timeout','epoch','delta'):
            with self.subTest(mode=mode):
                self.value.update(epoch='epoch',step_id=0,virtual_time_ns=123000);self.write()
                def send(command):
                    if mode=='timeout':return
                    self.send(command)
                    if mode=='epoch':self.value['epoch']='new'
                    else:self.value['virtual_time_ns']+=1000
                    self.write()
                stepper=RenodeStepper(self.proc,self.ack,send,timeout=.003)
                with self.assertRaises(StepError):bootstrap(stepper,lambda:None,self.output)
                self.assertTrue(stepper.failed)
                self.assertEqual(self.report()['uncertain_in_flight_step_id'],1)
                self.assertEqual(self.report()['last_confirmed_step_id'],0)
                self.proc.send_signal.assert_called_with(signal.SIGSTOP)
    def test_deadline_during_step_only_checked_after_ack(self):
        wait=run_link.StartupWait(1,None)
        with patch.object(run_link.time,'monotonic',return_value=0) as now:
            self.pending_hook=lambda:setattr(now,'return_value',2)
            with self.assertRaisesRegex(run_link.StartupAborted,'deadline'):
                bootstrap(self.stepper,wait.check,self.output)
        self.assertEqual(self.report()['last_confirmed_step_id'],1)
        self.assertIsNone(self.report()['uncertain_in_flight_step_id'])
    def test_bounded_full_pipe_and_restored_flags(self):
        read,write=os.pipe();self.addCleanup(os.close,read);self.addCleanup(os.close,write)
        self.proc.stdin.fileno.return_value=write
        with self.assertRaisesRegex(RuntimeError,'timed out'):
            bounded_send(self.proc,threading.Lock(),b'x'*1000000,timeout=.01)
        self.assertTrue(os.get_blocking(write))

    def test_writer_faults_always_release_lock(self):
        read,write=os.pipe();self.addCleanup(os.close,read);self.addCleanup(os.close,write)
        self.proc.stdin.fileno.return_value=write
        for name in ('get_blocking','set_blocking'):
            lock=threading.Lock()
            with patch('renode_bootstrap.os.'+name,side_effect=OSError('flags failure')):
                with self.assertRaisesRegex(OSError,'flags failure'):
                    bounded_send(self.proc,lock,b'x')
            self.assertFalse(lock.locked())
        lock=threading.Lock()
        with patch('renode_bootstrap.os.set_blocking',side_effect=[None,OSError('restore failed')]), \
             patch('renode_bootstrap.os.write',side_effect=OSError('write failed')):
            with self.assertRaisesRegex(OSError,'write failed') as caught:
                bounded_send(self.proc,lock,b'x')
        self.assertFalse(lock.locked())
        self.assertIn('restore failed',str(caught.exception.__notes__))

    def test_write_failure_preserved_if_sigstop_also_fails(self):
        primary=OSError('primary write failure')
        self.stepper.send_callback=Mock(side_effect=primary)
        self.proc.send_signal.side_effect=OSError('SIGSTOP failed')
        with self.assertRaisesRegex(OSError,'primary write failure') as caught:
            bootstrap(self.stepper,lambda:None,self.output)
        self.assertIs(caught.exception,primary)
        self.assertIn('SIGSTOP failed',str(primary.__notes__))
        self.assertTrue(self.stepper.failed)
        self.assertEqual(self.report()['uncertain_in_flight_step_id'],1)
        self.assertEqual(self.report()['last_confirmed_step_id'],0)
        self.assertIn('SIGSTOP failed',str(self.report()['error_notes']))

    def test_restore_failure_after_successful_write(self):
        read,write=os.pipe();self.addCleanup(os.close,read);self.addCleanup(os.close,write)
        self.proc.stdin.fileno.return_value=write
        lock=threading.Lock()
        with patch('renode_bootstrap.os.set_blocking',side_effect=[None,OSError('restore failed')]):
            with self.assertRaisesRegex(OSError,'restore failed'):
                bounded_send(self.proc,lock,b'sent')
        self.assertFalse(lock.locked())
        self.assertEqual(os.read(read,4),b'sent')

class ConfigurationTests(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(run_link.parser().parse_args([]).renode_bootstrap,'legacy')
        self.assertEqual(run_link.execution_args(run_link.parser().parse_args(VALID)),['-icount','shift=0,align=off,sleep=off'])
        for field,value in [('shared_mcus',False),('clock_lockstep',False),('clock_coupled',False),('clock_source','qom'),('qemu_icount_shift',None)]:
            a=run_link.parser().parse_args(VALID);setattr(a,field,value)
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'Segmented bootstrap requires'):
                run_link.execution_args(a)
    def test_script_only_runfor_removed(self):
        root=Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            tmp=Path(directory);a=run_link.parser().parse_args(VALID)
            a.mcu_image=root/'inputs/mcu.bin';a.nozzle_image=root/'inputs/nozzle.bin';a.motor_image=root/'inputs/motor.bin'
            a.log_dir=tmp/'logs';a.log_dir.mkdir()
            a.renode_bootstrap='legacy';script,_=prepare(a,tmp,[],[]);legacy=script.read_text()
            a.renode_bootstrap='segmented';script,_=prepare(a,tmp,[],[]);segmented=script.read_text()
            self.assertIn('emulation RunFor "1"\n',legacy)
            self.assertEqual(segmented,legacy.replace('emulation RunFor "1"\n',''))
            self.assertTrue(segmented.rstrip().endswith('renode-step.json" 0'))
    def test_incomplete_never_launches_qemu(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);image=root/'image.bin';image.write_bytes(b'\0'*8)
            logs=root/'logs';proc=Mock();proc.poll.return_value=None;proc.pid=123;proc.wait.return_value=-15
            args=['run_link',*VALID,'--mcu-image',str(image),'--nozzle-image',str(image),
                  '--motor-image',str(image),'--virtual-baud','576000','--log-dir',str(logs)]
            with patch.object(sys,'argv',args),patch('shared_mcu.prepare',return_value=(root/'script',root/'pty')), \
                 patch.object(run_link.StartupWait,'wait'),patch.object(run_link.StartupWait,'check'), \
                 patch.object(run_link.subprocess,'Popen',return_value=proc) as spawn, \
                 patch('renode_stepper.RenodeStepper',return_value=Mock(failed=True,step_id=0,time_ns=123000,epoch='same-epoch')), \
                 patch('renode_bootstrap.bootstrap',side_effect=StepError('uncertain step')):
                with self.assertRaisesRegex(run_link.StartupAborted,'uncertain step'):run_link.main()
            self.assertEqual(spawn.call_count,1)
            self.assertIn('--disable-gui',spawn.call_args.args[0])
            self.assertFalse(json.loads((logs/'startup-abort.json').read_text())['qemu_started'])

    def test_real_ack_failures_reject_launch_and_cleanup(self):
        for mode in ('malformed-initial','unpaused-initial','step-and-sigstop-fail'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);image=root/'image.bin';image.write_bytes(b'\0'*8)
                logs=root/'logs';ack=logs/'renode-step.json'
                proc=Mock();proc.poll.return_value=None;proc.pid=123;proc.wait.return_value=-15
                value=dict(schema=1,source='renode-shared-mcu-step',enabled=True,paused=True,
                           time_went_backwards=False,epoch='epoch',step_id=0,virtual_time_ns=123000)
                def spawn(*args,**kwargs):
                    if mode=='unpaused-initial':value['paused']=False
                    ack.write_text('{' if mode=='malformed-initial' else json.dumps(value))
                    return proc
                def send(*args,**kwargs):
                    value.update(step_id=1,virtual_time_ns=123001)
                    ack.write_text(json.dumps(value))
                proc.send_signal.side_effect=OSError('SIGSTOP failed')
                args=['run_link',*VALID,'--mcu-image',str(image),'--nozzle-image',str(image),
                      '--motor-image',str(image),'--virtual-baud','576000','--log-dir',str(logs)]
                with patch.object(sys,'argv',args),patch('shared_mcu.prepare',return_value=(root/'script',root/'pty')), \
                     patch.object(run_link.StartupWait,'wait'),patch.object(run_link.StartupWait,'check'), \
                     patch.object(run_link.subprocess,'Popen',side_effect=spawn) as launch, \
                     patch('renode_bootstrap.bounded_send',side_effect=send) as writer:
                    with self.assertRaises(run_link.StartupAborted) as caught:run_link.main()
                self.assertEqual(launch.call_count,1)
                proc.terminate.assert_called_once();proc.wait.assert_called_once()
                self.assertEqual(json.loads((logs/'startup-cleanup.json').read_text())['status'],'reaped')
                report=json.loads((logs/'startup-abort.json').read_text())
                self.assertFalse(report['qemu_started'])
                if mode=='step-and-sigstop-fail':
                    self.assertIn('actual step delta',str(caught.exception))
                    self.assertIsInstance(caught.exception.__cause__,StepError)
                    self.assertIn('SIGSTOP failed',str(caught.exception.__cause__.__notes__))
                    proc.send_signal.assert_called_once_with(signal.SIGSTOP)
                    self.assertEqual(report['uncertain_in_flight_step_id'],1)
                    self.assertEqual(report['last_confirmed_boundary']['step_id'],0)
                    self.assertFalse(report['initial_boundary_unconfirmed'])
                    bootstrap_report=json.loads((logs/'renode-bootstrap.json').read_text())
                    self.assertEqual(bootstrap_report['uncertain_in_flight_step_id'],1)
                    self.assertEqual(bootstrap_report['last_confirmed_step_id'],0)
                    self.assertIn('actual step delta',bootstrap_report['reason'])
                    self.assertIn('SIGSTOP failed',str(bootstrap_report['error_notes']))
                else:
                    self.assertTrue(report['initial_boundary_unconfirmed'])
                    self.assertIsNone(report['last_confirmed_boundary'])
                    self.assertIsNone(report['uncertain_in_flight_step_id'])
                    writer.assert_not_called();proc.send_signal.assert_not_called()

    def test_success_hands_same_stepper_to_coordinator(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);image=root/'image.bin';image.write_bytes(b'\0'*8)
            logs=root/'logs';proc=Mock();proc.poll.return_value=None;proc.pid=123;proc.wait.return_value=-15
            stepper=Mock(failed=False,step_id=1000,time_ns=1000123000,epoch='same-epoch')
            gate=Mock(error=None)
            args=['run_link',*VALID,'--mcu-image',str(image),'--nozzle-image',str(image),
                  '--motor-image',str(image),'--virtual-baud','576000','--log-dir',str(logs),'--timeout','0.001']
            with patch.object(sys,'argv',args),patch('shared_mcu.prepare',return_value=(root/'script',root/'pty')), \
                 patch.object(run_link.StartupWait,'wait'),patch.object(run_link.StartupWait,'check'), \
                 patch.object(run_link.subprocess,'Popen',return_value=proc) as spawn, \
                 patch('renode_stepper.RenodeStepper',return_value=stepper) as constructor, \
                 patch('renode_bootstrap.bootstrap',return_value=stepper) as boot, \
                 patch.object(run_link,'open_deadline_client'), \
                 patch('lockstep_coordinator.LockstepCoordinator',return_value=gate) as coordinator, \
                 patch.object(run_link.time,'sleep'):
                self.assertEqual(run_link.main(),0)
            self.assertEqual(spawn.call_count,2)
            constructor.assert_called_once()
            self.assertEqual(constructor.call_args.kwargs['timeout'],2)
            self.assertIs(boot.call_args.args[0],stepper)
            self.assertIs(coordinator.call_args.args[1],stepper)
            self.assertEqual(stepper.timeout,10)
            self.assertEqual(stepper.step_id,1000)
            self.assertEqual(stepper.epoch,'same-epoch')

if __name__=='__main__':unittest.main()
