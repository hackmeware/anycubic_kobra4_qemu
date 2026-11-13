"""Actual Renode clock-only step handshake; no native firmware or CPU."""
import pathlib,subprocess,tempfile,sys,json,os,time
root=pathlib.Path(__file__).resolve().parents[3]
import argparse,threading,statistics
a=argparse.ArgumentParser();a.add_argument('--mode',choices=['baseline','local'],required=True);a.add_argument('--output',type=pathlib.Path,required=True);opt=a.parse_args()
sys.path.insert(0,str(root/'rv1106-at32-link/scripts'))
from renode_stepper import RenodeStepper
from timed_baseline_clock import EventClockClient
from batched_lockstep import LockstepCoordinator

out=opt.output;out.mkdir(exist_ok=True,parents=True)
with tempfile.TemporaryDirectory(prefix='renode-step-smoke-') as t:
 t=pathlib.Path(t);ack=t/'ack.json';telemetry=t/'time.json';script=t/'test.resc'
 (t/'home/.config').mkdir(parents=True)
 env=dict(os.environ,HOME=str(t/'home'),XDG_CONFIG_HOME=str(t/'home/.config'),TMPDIR=str(t))
 # Synthetic Cortex-M Thumb increment loop, not native firmware.
 fixture=bytes.fromhex('0248016801310160fbe700bf00000020')
 (out/'counter-loop.bin').write_bytes(fixture)
 lines=[f'include @{root}/printer-shared-mcu/peripherals/VirtualTimeTelemetry.cs',f'include @{pathlib.Path(__file__).parent}/SchedulingProbe.cs',f'include @{pathlib.Path(__file__).parent}/LocalMachineFactory.cs','emulation SetGlobalSerialExecution false', 'emulation SetGlobalQuantum "0.000001"']
 for identity,board in enumerate(['main','motor','nozzle']):
  repl=t/(board+'.repl');repl.write_text('flash: Memory.MappedMemory @ sysbus 0x08000000\n    size: 0x1000\nsram: Memory.MappedMemory @ sysbus 0x20000000\n    size: 0x1000\nnvic: IRQControllers.NVIC @ sysbus 0xE000E000\n    IRQ -> cpu@0\ncpu: CPU.CortexM @ sysbus\n    cpuType: "cortex-m3"\n    nvic: nvic\nprobe: SchedulerExperiment.SchedulingProbe @ sysbus 0x60000000\n    identity: IDENTITY\n    phase: PHASE\n' .replace('IDENTITY',str(identity)).replace('PHASE',str([1,3,7][identity])))
  lines += (["mach set \"main\"",'sysbus.factory CreateNozzle', 'mach set \"nozzle\"'] if board=='nozzle' and opt.mode=='local' else [f'mach create "{board}"'])
  lines += [f'machine LoadPlatformDescription @{repl}',f'sysbus LoadBinary @{out}/counter-loop.bin 0x08000000','cpu PerformanceInMips 100','cpu SP 0x20001000','cpu PC 0x08000001']
  if board=='main':lines += ['machine LoadPlatformDescriptionFromString \"factory: SchedulerExperiment.LocalMachineFactory @ sysbus 0x70000000\"']
 lines += ['emulation CreateUARTHub "orderingUart"']
 for board in ['main','motor','nozzle']:lines += [f'mach set "{board}"','connector Connect sysbus.probe orderingUart']
 for src,dst,n in [('main','nozzle',0),('nozzle','main',1)]:
  name='orderingGpio'+str(n);lines += [f'emulation CreateGPIOConnector "{name}"',f'mach set "{src}"',f'connector Connect sysbus.probe {name}',f'{name} SelectSourcePin sysbus.probe 0',f'mach set "{dst}"',f'connector Connect sysbus.probe {name}',f'{name} SelectDestinationPin sysbus.probe {n}']
 if opt.mode=='local':lines += ['emulation SetGlobalQuantum "0.00001"','mach set "nozzle"','machine SetQuantum "0.000001"']
 lines += ['mach set "main"',f'sysbus.factory Check "{out}/time-hierarchy.txt" {str(opt.mode=="local").lower()}',f'machine LoadPlatformDescriptionFromString "timeTelemetry: PrinterShared.VirtualTimeTelemetry @ sysbus {{ periodMicroseconds: 1000 }}"',f'sysbus.timeTelemetry Enable "{telemetry}"','emulation RunFor "0.001"',f'sysbus.timeTelemetry PublishStep "{ack}" 0']
 script.write_text('\n'.join(lines)+'\n');(out/'fixture.resc.txt').write_text(script.read_text())
 with (out/'renode-step-smoke.log').open('wb') as log:
  p=subprocess.Popen([str(root/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(script)],stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,env=env)
  try:
   from step_sender import SerializedStepSender
   sender_lock=threading.Lock()
   direct=SerializedStepSender(p,sender_lock)
   def send(data):
    # Baseline reproduces run_link.send_peer wrapping. Candidate retains the
    # stepper's explicit main selection and serializes without extra commands.
    if True:data=b'mach set "main"\n'+data+b'\nmach set "main"\n'
    direct(data)
   s=RenodeStepper(p,ack,send,timeout=30)
   values=[s.initial_time_ns]
   for _ in range(0):values.append(s.step())
   assert values==[1000000],values
   result={'passed':True,'actual_times_ns':values,'ack':json.loads(ack.read_text()),'scope':'three synthetic CPU loops plus UART/GPIO/timer ordering, no native firmware'}
   (out/'renode-step-smoke.json').write_text(json.dumps(result,indent=2)+'\n');print(result)
   qp=subprocess.Popen([str(root/'evidence/exact-generic-timer/exact24-runtime/run-qemu-system-arm-exact24'),
     '-M','rv1106,virtual-deadline-enabled=on','-m','64M','-S','-display','none','-serial','null',
     '-monitor','none','-qmp','stdio','-icount','shift=0,align=off,sleep=off',
     '-kernel',str(root/'evidence/qemu-virtual-deadline/synthetic-loop/arm-branch-self.bin')],
     stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
   gate=None
   try:
    q=EventClockClient(qp.stdout,qp.stdin)
    gate=LockstepCoordinator(q,s,out/'lockstep-smoke.json')
    end=time.monotonic()+30
    while len(gate.samples)<100 and not gate.error and time.monotonic()<end:time.sleep(.01)
    gate.close()
    assert gate.error is None,gate.error
    assert len(gate.samples)==100,len(gate.samples)
    assert gate.max_lead==1 and gate.max_lag==1000000
    result={'mode':opt.mode,'combined_steps':len(gate.samples),'max_lead_ns':gate.max_lead,'max_lag_ns':gate.max_lag,'native_calibration':False,
     'mean_phase_wall_s':{k:statistics.mean(x['phase_wall_s'][k] for x in gate.samples) for k in ('boundary','renode','qemu')},
     'steady_steps_per_wall_second':(len(gate.samples)-1)/(gate.samples[-1]['wall_s']-gate.samples[0]['wall_s'])}
    for board in ['main','motor','nozzle']:
     send(f'mach set "{board}"\nsysbus.probe Export "{out}/{board}-ordering.csv"\n'.encode())
    until=time.monotonic()+3
    while not all((out/(board+'-ordering.csv.cpu')).exists() for board in ['main','motor','nozzle']) and time.monotonic()<until:time.sleep(.01)
    assert all((out/(board+'-ordering.csv.cpu')).exists() for board in ['main','motor','nozzle'])
    assert all(int((out/(board+'-ordering.csv.cpu')).read_text())>0 for board in ['main','motor','nozzle'])
    (out/'benchmark.json').write_text(json.dumps(result,indent=2)+'\n');print(result)
   finally:
    if gate:gate.close()
    qp.terminate()
    try:qp.wait(timeout=3)
    except subprocess.TimeoutExpired:qp.kill();qp.wait(timeout=3)
  finally:
   p.terminate()
   try:p.communicate(timeout=3)
   except subprocess.TimeoutExpired:p.kill();p.communicate(timeout=3)
