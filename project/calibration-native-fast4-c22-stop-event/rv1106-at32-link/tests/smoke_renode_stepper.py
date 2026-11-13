"""Actual Renode clock-only step handshake; no native firmware or CPU."""
import pathlib,subprocess,tempfile,sys,json,os,time
root=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'rv1106-at32-link/scripts'))
from renode_stepper import RenodeStepper
from event_clock_client import EventClockClient
from lockstep_coordinator import LockstepCoordinator
out=root/'evidence/bidirectional-lockstep';out.mkdir(exist_ok=True,parents=True)
with tempfile.TemporaryDirectory(prefix='renode-step-smoke-') as t:
 t=pathlib.Path(t);ack=t/'ack.json';telemetry=t/'time.json';script=t/'test.resc'
 (t/'home/.config').mkdir(parents=True)
 env=dict(os.environ,HOME=str(t/'home'),XDG_CONFIG_HOME=str(t/'home/.config'),TMPDIR=str(t))
 script.write_text(f'''include @{root}/printer-shared-mcu/peripherals/VirtualTimeTelemetry.cs
mach create "main"
emulation SetGlobalQuantum "0.00001"
machine LoadPlatformDescriptionFromString "timeTelemetry: PrinterShared.VirtualTimeTelemetry @ sysbus {{ periodMicroseconds: 1000 }}"
sysbus.timeTelemetry Enable "{telemetry}"
emulation RunFor "0.001"
sysbus.timeTelemetry PublishStep "{ack}" 0
''')
 with (out/'renode-step-smoke.log').open('wb') as log:
  p=subprocess.Popen([str(root/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(script)],stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,env=env)
  try:
   def send(data):p.stdin.write(data);p.stdin.flush()
   s=RenodeStepper(p,ack,send,timeout=30)
   values=[s.initial_time_ns]
   for _ in range(3):values.append(s.step())
   assert values==[1000000,2000000,3000000,4000000],values
   result={'passed':True,'actual_times_ns':values,'ack':json.loads(ack.read_text()),'scope':'clock-only Renode, no CPU/native firmware'}
   (out/'renode-step-smoke.json').write_text(json.dumps(result,indent=2)+'\n');print(result)
   qp=subprocess.Popen([str(root/'evidence/qemu-virtual-deadline/runtime-pending-stop-barrier/run-qemu-system-arm'),
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
    assert len(gate.samples)>=100,len(gate.samples)
    assert gate.max_lead==1 and gate.max_lag==1000000
    print({'combined_steps':len(gate.samples),'max_lead_ns':gate.max_lead,'max_lag_ns':gate.max_lag,'native_calibration':False})
   finally:
    if gate:gate.close()
    qp.terminate()
    try:qp.wait(timeout=3)
    except subprocess.TimeoutExpired:qp.kill();qp.wait(timeout=3)
  finally:
   p.terminate()
   try:p.communicate(timeout=3)
   except subprocess.TimeoutExpired:p.kill();p.communicate(timeout=3)
