#!/usr/bin/env python3
"""Connect QEMU serial to Renode UART via a private local PTY; optional loopback-only VNC."""
import argparse, json, os, pathlib, subprocess, tempfile, time, sys, threading
ROOT=pathlib.Path(__file__).resolve().parents[1]

def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qemu',type=pathlib.Path,default=ROOT.parent/'rv1106-qemu/bin/qemu-system-arm')
    p.add_argument('--renode',type=pathlib.Path,default=ROOT.parent/'at32-runtime/renode_1.17.0-portable/renode')
    p.add_argument('--model',type=pathlib.Path,default=ROOT.parent/'at32-renode')
    p.add_argument('--rv-image',type=pathlib.Path,default=ROOT/'firmware/rv1106-test.bin')
    p.add_argument('--mcu-image',type=pathlib.Path,default=ROOT/'firmware/at32-test.bin')
    p.add_argument('--rv-uart',type=int,choices=range(6),default=1)
    p.add_argument('--mcu-uart',choices=['usart1','usart2','usart3','uart4','uart5','usart6','uart7','uart8'],default='usart1')
    p.add_argument('--mcu-hext',type=int,help='Optional main MCU external crystal frequency in Hz; generic default unchanged')
    p.add_argument('--mcu-base',type=lambda s:int(s,0),default=0x08000000)
    p.add_argument('--renode-host-jit',choices=['default','single-tier'],default='default',help='Experimental host-only .NET compilation option; never changes MCU/QEMU virtual clocks')
    p.add_argument('--timeout',type=float,default=30)
    p.add_argument('--stop-request',type=pathlib.Path,help='Opt-in local stop-file checked during startup and observation; preserves initialized diagnostics and cleanup')
    p.add_argument('--virtual-baud',type=int,help='Opt-in Renode virtual-time serial wire baud, preserves hardware RX depth')
    p.add_argument('--pace-rv-byte',type=float,default=0,help='Optional diagnostic host seconds per RV-to-MCU byte (not baud accurate)')
    p.add_argument('--nozzle-setup-commands',type=pathlib.Path,help='Explicit nozzle environment setup monitor commands before firmware runs')
    p.add_argument('--mcu-setup-commands',type=pathlib.Path,help='Explicit main MCU environment setup monitor commands before firmware runs')
    p.add_argument('--nozzle-final-commands',type=pathlib.Path,help='Diagnostic nozzle monitor commands before stopping')
    p.add_argument('--final-export-transport',choices=['stdin','include-file'],default='stdin',help='Opt-in shared-monitor final file transport; identical commands, acknowledgements and cleanup deadline')
    p.add_argument('--mcu-final-commands',type=pathlib.Path,help='Diagnostic monitor commands before stopping Renode')
    p.add_argument('--vnc',action='store_true',help='Serve actual framebuffer and diagnostic touch only on127.0.0.1')
    p.add_argument('--vnc-port',type=int,default=5900,help='Local VNC TCP port; default5900, zero selects a free port')
    p.add_argument('--live-display',action='store_true',help='Show actual framebuffer through shared RAM and SDL2; diagnostic touch only')
    p.add_argument('--live-headless',action='store_true',help='Exercise live capture without a window; requires --live-display')
    p.add_argument('--screenshot',type=pathlib.Path,help='Optional QEMU PPM screenshot near end of observation')
    p.add_argument('--nozzle-image',type=pathlib.Path,help='Optional second MCU firmware linked to RV UART0')
    p.add_argument('--nozzle-model',type=pathlib.Path,default=ROOT.parent/'nozzle-renode')
    p.add_argument('--nozzle-base',type=lambda s:int(s,0),default=0x08004000)
    p.add_argument('--clock-coupled',action='store_true',help='Experimental measured virtual-time QMP gate; requires sharedMCUs and clock QEMU binary')
    p.add_argument('--clock-source',choices=['qom','diagnostic-timer-fixture','qom-deadline'],default='qom',help='Explicit diagnostic timer or native QEMU deadline gating; requires matching QEMU capabilities')
    p.add_argument('--clock-client',choices=['scalar','stop-event','snapshot'],default='scalar',help='Explicit deadline client; snapshot requires shared lockstep QOM deadlines and icount')
    p.add_argument('--renode-bootstrap',choices=['legacy','segmented'],default='legacy',help='Opt-in segmented 1s bootstrap with cancellation at acknowledged 1ms boundaries; equivalence not established')
    p.add_argument('--clock-lockstep',action='store_true',help='Explicit paused-boundary 1ms advancement of both emulators; requires shared MCUs, QOM deadline and icount')
    p.add_argument('--qemu-icount-shift',type=int,choices=range(11),help='Explicit diagnostic instruction-count time: 2**shift ns/instruction with idle warp; not physical cycle accuracy')
    p.add_argument('--trace-homing-gpio',action='store_true',help='Passive resolved edge recording in shared main/motor machines')
    p.add_argument('--assumed-xy-diag-cable',action='store_true',help='Explicit non-inverting motor PB5/PB4 to main PA6/PA15 hypothesis, not established PCB wiring')
    p.add_argument('--shared-mcus',action='store_true',help='Opt-in one Renode time domain for all3 MCUs and actual PA8 motor sync')
    p.add_argument('--motor-image',type=pathlib.Path,help='Original third MCU, linked main USART2 to motor USART2')
    p.add_argument('--motor-model',type=pathlib.Path,default=ROOT.parent/'motor-renode')
    p.add_argument('--motor-setup-commands',type=pathlib.Path,help='Explicit shared motor model setup before original firmware runs')
    from z_probe_selection import add_arguments
    add_arguments(p)
    from pid_thermal_profile_selection import add_arguments as add_thermal_arguments
    add_thermal_arguments(p)
    from native_dual_lis_selection import add_arguments as add_lis_arguments
    add_lis_arguments(p)
    p.add_argument('--nozzle-tmc-model',choices=['fixed','autobaud'],default='fixed',help='Explicit experimental external UART model; firmware unchanged')
    p.add_argument('--motor-enable-wiring',choices=['direct-bridge-gate','mcu-control-only'],default='direct-bridge-gate',help='Explicit generic wiring assumption; no PCB verification')
    p.add_argument('--motor-plant',choices=['electrical','zero-current','electromechanical-driver'],default='electrical')
    p.add_argument('--memory',type=int,choices=[64,128,256],default=64)
    p.add_argument('--cpu', help='Optional QEMU CPU model, e.g. cortex-a7,has_el3=off')
    p.add_argument('--disk',type=pathlib.Path,help='Optional raw eMMC image, always snapshot=on')
    p.add_argument('--console-commands',type=pathlib.Path,help='Explicit guest shell commands on debug console after Linux readiness marker')
    p.add_argument('--peer-monitor-input',type=pathlib.Path,help='Local append-only Renode commands broadcast to main and nozzle peers')
    p.add_argument('--console-input',type=pathlib.Path,help='Optional local append-only guest command file, processed after startup commands')
    p.add_argument('--console-chunk-bytes',type=int,default=64)
    p.add_argument('--console-chunk-delay',type=float,default=.01)
    p.add_argument('--console-line-delay',type=float,default=.1)
    p.add_argument('--console-ready',default='RV1106_OFFLINE_USERSPACE_READY')
    p.add_argument('--test',action='store_true',help='Require built-in round-trip success marker')
    p.add_argument('--log-dir',type=pathlib.Path,default=ROOT/'test-results')
    return p

def observation_stop_requested(path):
    # The file is a signal only: never execute, consume, delete, or interpret it.
    return path is not None and path.exists()

class StartupAborted(RuntimeError):
    """Startup failed closed before QEMU was allowed to launch."""

class StartupWait:
    """One absolute budget for all Renode startup phases and launch checks."""
    def __init__(self, deadline, stop_request):
        self.deadline=deadline
        self.stop_request=stop_request
        self.phase='before Renode launch'
        self.peers=[]

    def check(self):
        # Cancellation and expiration win over readiness, including when a
        # readiness predicate itself observes a stop or consumes the budget.
        if observation_stop_requested(self.stop_request):
            raise StartupAborted('Renode startup aborted: stop requested during '+self.phase)
        if time.monotonic()>=self.deadline:
            raise StartupAborted('Renode startup aborted: deadline expired during '+self.phase)
        for proc,logfile in self.peers:
            if proc.poll() is not None:
                raise StartupAborted('Renode startup aborted: process exited during '+self.phase)
            if b'There was an error' in logfile.read_bytes():
                raise StartupAborted('Renode startup aborted: model error during '+self.phase+'; inspect '+logfile.name)
        # Recheck after log IO as well as before it.
        if observation_stop_requested(self.stop_request):
            raise StartupAborted('Renode startup aborted: stop requested during '+self.phase)
        if time.monotonic()>=self.deadline:
            raise StartupAborted('Renode startup aborted: deadline expired during '+self.phase)

    def wait(self, phase, ready):
        self.phase=phase
        while True:
            self.check()
            done=ready()
            self.check()
            if done:return
            time.sleep(min(.05,max(0,self.deadline-time.monotonic())))

    def settle(self):
        until=time.monotonic()+.2
        self.wait('Renode startup settling',lambda:time.monotonic()>=until)


class CleanupFailures:
    """Attempt every resource cleanup, retaining the original task failure."""
    def __init__(self):self.errors=[]

    def attempt(self, label, action):
        try:return action()
        except Exception as error:self.errors.append((label,error))

    def finish(self, original_error):
        if not self.errors:return
        message='Cleanup unconfirmed: '+'; '.join(label+': '+str(error) for label,error in self.errors)
        print(message,file=sys.stderr,flush=True)
        if original_error is not None:
            original_error.add_note(message)
        else:
            raise RuntimeError(message) from self.errors[0][1]


def terminate_children(processes, initialized, failures, deadline=None):
    # Record internal escalation separately from the outer supervisor's signals.
    records=[{'index':index,'pid':getattr(proc,'pid',None),'term_attempted':False,
              'kill_attempted':False,'reaped':False,'returncode':None,'errors':[]}
             for index,proc in enumerate(processes)]
    # One failed signal/wait must not prevent attempts on all other children.
    def attempt(label, action, record):
        before=len(failures.errors)
        failures.attempt(label,action)
        record['errors'].extend(str(error) for _,error in failures.errors[before:])
    for index,proc in reversed(list(enumerate(processes))):
        record=records[index]
        def terminate(proc=proc,record=record):
            if proc.poll() is None:
                record['term_attempted']=True
                proc.terminate()
        attempt('terminate child '+str(index),terminate,record)
    for index,proc in enumerate(processes):
        record=records[index]
        def reap(proc=proc,record=record):
            timeout=5 if initialized else .5
            if deadline is not None:timeout=min(timeout,max(0,deadline-.5-time.monotonic()))
            try:code=proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record['kill_attempted']=True
                proc.kill()
                # Never block indefinitely even if a process cannot be killed.
                timeout=.5 if deadline is None else min(.5,max(0,deadline-time.monotonic()))
                code=proc.wait(timeout=timeout)
            record.update(reaped=True,returncode=code)
        attempt('reap child '+str(index),reap,record)
    return records


def quote(path):
    s=str(path)
    if any(c in s for c in '\n\r"'): raise ValueError('Path contains unsupported monitor characters')
    return '"'+s+'"'

def renode_host_environment(environment, selection):
    """Return child-only environment; default does not alter inherited settings."""
    if selection not in ('default', 'single-tier'):
        raise ValueError('Unknown Renode host JIT selection')
    child = dict(environment)
    if selection == 'single-tier':
        for name in ('DOTNET_TieredCompilation', 'COMPlus_TieredCompilation'):
            if name in child and child[name] != '0':
                raise ValueError('Conflicting Renode host JIT override: ' + name)
        child['DOTNET_TieredCompilation'] = '0'
    return child

def execution_args(a):
    from z_probe_selection import validate
    validate(a)
    from pid_thermal_profile_selection import validate as validate_thermal
    validate_thermal(a)
    from native_dual_lis_selection import validate as validate_lis
    validate_lis(ROOT.parent,a)
    if a.nozzle_tmc_model!='fixed' and not a.shared_mcus:
        raise ValueError('Experimental nozzle TMC selection requires shared MCUs')
    if a.trace_homing_gpio and not a.shared_mcus:
        raise ValueError('Homing GPIO trace requires shared MCUs')
    if a.motor_enable_wiring!='direct-bridge-gate' and (not a.shared_mcus or a.motor_plant!='electromechanical-driver'):
        raise ValueError('Alternate enable wiring requires shared dynamic driver profile')
    if a.assumed_xy_diag_cable and (not a.shared_mcus or a.motor_plant!='electromechanical-driver'):
        raise ValueError('Assumed diagnostic cable requires shared causal dynamic motor profile')
    if a.renode_bootstrap=='segmented' and (not a.shared_mcus or not a.clock_coupled or a.clock_source!='qom-deadline' or not a.clock_lockstep or a.qemu_icount_shift is None):
        raise ValueError('Segmented bootstrap requires shared MCUs, coupled QOM deadlines, lockstep and explicit icount')
    if a.clock_client in ('stop-event','snapshot') and (not a.shared_mcus or not a.clock_coupled or a.clock_source!='qom-deadline' or not a.clock_lockstep or a.qemu_icount_shift is None):
        raise ValueError('Snapshot client requires shared MCUs, coupled QOM deadlines, lockstep and explicit icount')
    if a.clock_lockstep and (not a.clock_coupled or a.clock_source!='qom-deadline' or a.qemu_icount_shift is None or not a.shared_mcus):
        raise ValueError('Lockstep requires shared MCUs, coupled QOM deadlines and explicit icount')
    if a.clock_lockstep and a.peer_monitor_input:
        raise ValueError('Lockstep rejects live monitor commands; use final diagnostics at paused completion')
    if a.qemu_icount_shift is None:return []
    if not a.clock_coupled or a.clock_source!='qom-deadline':
        raise ValueError('Instruction-count diagnostic requires coupled QOM deadline mode')
    return ['-icount',f'shift={a.qemu_icount_shift},align=off,sleep=off']

def open_deadline_client(selection,base,timeout=3):
    from event_clock_client import EventClockClient,open_clock_pipes
    if selection=='scalar':
        return EventClockClient.from_pipes(base,timeout=timeout)
    if selection=='stop-event':
        sys.path.insert(0,str(ROOT/'experimental/stop-event-clock'))
        from stop_event_clock import StopEventClockClient
        return open_clock_pipes(StopEventClockClient,base,timeout=timeout)
    if selection!='snapshot':
        raise ValueError('Unknown clock client: '+str(selection))
    # Optional experimental imports never affect the default scalar path.
    sys.path[:0]=[str(ROOT/'experimental/clock-snapshot/client'),
                  str(ROOT/'experimental/stop-event-clock')]
    from snapshot_clock import SnapshotClockClient
    return open_clock_pipes(SnapshotClockClient,base,timeout=timeout)


def main():
    a=parser().parse_args()
    if a.final_export_transport=='include-file' and not a.shared_mcus:raise ValueError('Include-file final export requires shared MCUs')
    try:icount_args=execution_args(a)
    except ValueError as e:raise SystemExit(str(e))
    if a.motor_plant=='electromechanical-driver' and not a.shared_mcus:
        raise SystemExit('Electromechanical driver profile requires --shared-mcus')
    if a.motor_setup_commands and not a.shared_mcus:
        raise SystemExit('--motor-setup-commands requires --shared-mcus')
    if a.clock_source=='diagnostic-timer-fixture' and (not a.clock_coupled or not a.console_commands):
        raise SystemExit('Diagnostic timer fixture requires --clock-coupled and offline guest console commands')
    if a.clock_source=='qom-deadline' and not a.clock_coupled:
        raise SystemExit('QOM deadline mode requires --clock-coupled')
    for name in ['qemu','renode','model','rv_image','mcu_image','log_dir','disk','console_commands','screenshot','nozzle_image','nozzle_model','motor_image','motor_model','stop_request']:
        if getattr(a,name) is not None: setattr(a,name,getattr(a,name).resolve())
    if a.test and (a.rv_uart!=1 or a.mcu_uart!='usart1' or a.mcu_base!=0x08000000):
        raise SystemExit('Built-in test firmware requires RV UART1 and AT32 USART1 at default load base.')
    if a.vnc and (a.live_display or a.live_headless): raise SystemExit('Choose --vnc or --live-display, not both')
    if not 0<=a.vnc_port<=65535: raise SystemExit('Invalid VNC port')
    if a.vnc: a.live_display=True
    if a.live_headless and not a.live_display: raise SystemExit('--live-headless requires --live-display')
    if a.live_display and not a.console_commands: raise SystemExit('--live-display requires --console-commands including diagnostic touchscreen setup')
    if a.mcu_hext is not None and a.mcu_hext<=0: raise SystemExit('--mcu-hext must be positive')
    if a.timeout<=0: raise SystemExit('--timeout must be positive')
    if a.console_chunk_bytes<1 or min(a.console_chunk_delay,a.console_line_delay)<0: raise SystemExit('Invalid console pacing')
    if a.virtual_baud is not None and (a.virtual_baud<=0 or a.pace_rv_byte): raise SystemExit('Virtual baud must be positive and cannot combine with wall-clock pacing')
    if a.pace_rv_byte<0: raise SystemExit('--pace-rv-byte must not be negative')
    if ',' in str(a.log_dir): raise SystemExit('Log directory must not contain commas')
    final_commands=a.mcu_final_commands.read_bytes()+b'\n' if a.mcu_final_commands else None
    nozzle_final=a.nozzle_final_commands.read_bytes()+b'\n' if a.nozzle_final_commands else None
    if a.z_probe_profile!='none':
        from z_probe_selection import final_commands as z_final_commands
        final_commands=(final_commands or b'')+z_final_commands(a).encode()
    if a.thermal_profile!='none':
        from pid_thermal_profile_selection import final_commands as thermal_final_commands
        final_commands=(final_commands or b'')+thermal_final_commands(a).encode()
    mcu_setup=a.mcu_setup_commands.read_text().splitlines() if a.mcu_setup_commands else []
    nozzle_setup=a.nozzle_setup_commands.read_text().splitlines() if a.nozzle_setup_commands else []
    a.log_dir.mkdir(parents=True,exist_ok=True)
    if a.clock_lockstep and (a.log_dir/'renode-step.json').exists():raise ValueError('Lockstep acknowledgment already exists; use a new run directory')
    if a.vnc:(a.log_dir/'vnc-endpoint.json').unlink(missing_ok=True)
    if a.nozzle_image and a.rv_uart==0: raise SystemExit('Main and nozzle cannot share RV UART0')
    if a.console_commands and a.rv_uart==2: raise SystemExit('UART2 link conflicts with debug console commands')
    if a.disk and ',' in str(a.disk): raise SystemExit('Disk path must not contain commas')
    if a.disk and not a.disk.is_file(): raise SystemExit('Disk image does not exist')
    command_bytes=a.console_commands.read_bytes()+b'\n' if a.console_commands else None
    if any(c.isspace() for c in str(a.mcu_image)): raise SystemExit('Renode image path must not contain whitespace')
    data=a.mcu_image.read_bytes()
    if len(data)<8: raise SystemExit('MCU image lacks initial SP/reset vector')
    import struct
    sp,pc=struct.unpack_from('<II',data)
    if a.motor_image and (not a.virtual_baud or a.mcu_uart=="usart2"): raise SystemExit("Motor link requires virtual baud and a separate main host UART")
    if a.clock_coupled and not a.shared_mcus:raise SystemExit('--clock-coupled requires --shared-mcus')
    if a.shared_mcus and (not a.motor_image or not a.nozzle_image or a.virtual_baud!=576000 or a.mcu_uart!='usart1' or a.motor_plant not in ('electrical','electromechanical-driver')):
        raise SystemExit('Shared MCU profile requires mainUSART1, nozzle+motor images, virtualbaud576000, supported electrical motor plant')
    processes=[]
    startup_complete=False
    stepper=None
    peers={}
    peer_write_lock=threading.Lock()
    def send_peer(board,data,select_machine=True):
        peer=peers.get(board)
        if peer is None or peer.poll() is not None:return
        if a.shared_mcus and select_machine:data=(f'mach set "{board}"\n').encode()+data+b'\nmach set "main"\n'
        with peer_write_lock:
            peer.stdin.write(data);peer.stdin.flush()
    motor_relay=None;motor_proc=None;clock_gate=None
    relay=None
    nozzle_relay=None
    nozzle_pty=None
    monitor_fds=[]
    viewer=None;viewer_log=None;vnc_announced=False;touch_offset=0;next_vop_dump=0;touch_pending=b''
    with tempfile.TemporaryDirectory(prefix='rv-at32-link-') as tmp:
        tmp=pathlib.Path(tmp); pty=tmp/'uart'
        resc=tmp/'link.resc'
        wire_commands=[]
        endpoint=a.mcu_uart
        wire_source=ROOT.parent/'at32-renode/peripherals/AT32F403A_VirtualSerialWire.cs'
        if a.virtual_baud:
            wire=tmp/'wire.repl'
            wire.write_text(f'serialWire: AT32.AT32VirtualSerialWire @ sysbus\n    uart: {a.mcu_uart}\n    baud: {a.virtual_baud}\n    bitsPerFrame: 10\n')
            wire_commands=[f'include @{wire_source}',f'machine LoadPlatformDescription @{wire}']
            endpoint='serialWire'
        if a.motor_image:
            motorwire=tmp/'main-motor.repl'
            motorwire.write_text(f'motorWire: AT32.AT32VirtualSerialWire @ sysbus\n    uart: usart2\n    baud: {a.virtual_baud}\n    bitsPerFrame: 10\n')
            wire_commands += [f'machine LoadPlatformDescription @{motorwire}',f'emulation CreateUartPtyTerminal "motor_link" {quote(tmp/"motor-uart")}', 'connector Connect sysbus.motorWire motor_link',f'sysbus.usart2 CreateFileBackend @{tmp}/main-motor-tx.bin']
        resc.write_text('\n'.join([
            'include @scripts/load.resc',
            *([f'sysbus.crm HextFrequency {a.mcu_hext}'] if a.mcu_hext else []),
            *wire_commands,
            f'emulation CreateUartPtyTerminal "rv_link" {quote(pty)}',
            f'connector Connect sysbus.{endpoint} rv_link',
            f'sysbus.{a.mcu_uart} CreateFileBackend @{tmp}/mcu-tx.bin',
            f'sysbus LoadBinary @{a.mcu_image} 0x{a.mcu_base:x}',
            f'sysbus.cpu VectorTableOffset 0x{a.mcu_base:x}',
            f'sysbus.cpu SP 0x{sp:x}',f'sysbus.cpu PC 0x{pc:x}',
            *mcu_setup,
            # Initialize the test receiver before QEMU can transmit.
            'emulation RunFor "0.01"','start','']))
        if a.shared_mcus:
            from shared_mcu import prepare
            resc,nozzle_pty=prepare(a,tmp,mcu_setup,nozzle_setup)
        env=dict(os.environ,HOME=str(tmp/'home'),XDG_CONFIG_HOME=str(tmp/'home/.config'),TMPDIR=str(tmp))
        (tmp/'home/.config').mkdir(parents=True)
        with (a.log_dir/'renode.log').open('wb') as rlog, (a.log_dir/'qemu.log').open('wb') as qlog, (a.log_dir/'console.bin').open('wb') as console:
            startup=StartupWait(time.monotonic()+(300 if a.shared_mcus else 60),a.stop_request)
            try:
                startup.check()
                renode_env=renode_host_environment(env,a.renode_host_jit)
                (a.log_dir/'renode-host-runtime.json').write_text(json.dumps({'host_jit':a.renode_host_jit,'DOTNET_TieredCompilation':renode_env.get('DOTNET_TieredCompilation'),'COMPlus_TieredCompilation':renode_env.get('COMPlus_TieredCompilation'),'virtual_clock_settings_changed':False},indent=2)+'\n')
                r=subprocess.Popen([str(a.renode),'--disable-gui','--console',str(resc)],cwd=a.model,env=renode_env,stdin=subprocess.PIPE,stdout=rlog,stderr=subprocess.STDOUT)
                processes.append(r);peers['main']=r
                if a.shared_mcus:peers.update(nozzle=r,motor=r);motor_proc=r
                startup.peers.append((r,a.log_dir/'renode.log'))
                startup.wait('main UART PTY',pty.exists)
                # PTY appears before model/load commands finish. Wait for RunFor completion.
                def initialization_ready():
                    if a.clock_lockstep:return (a.log_dir/'renode-step.json').exists()
                    return b'Starting emulation' in (a.log_dir/'renode.log').read_bytes()
                startup.wait('main initialization',initialization_ready)
                if a.renode_bootstrap=='segmented':
                    from renode_stepper import RenodeStepper
                    from renode_bootstrap import bootstrap, bounded_send, BOOTSTRAP_WRITE_TIMEOUT, BOOTSTRAP_ACK_TIMEOUT
                    startup.phase='segmented Renode bootstrap'
                    try:
                        stepper=RenodeStepper(r,a.log_dir/'renode-step.json',
                            lambda data:bounded_send(r,peer_write_lock,data,timeout=BOOTSTRAP_WRITE_TIMEOUT),timeout=BOOTSTRAP_ACK_TIMEOUT)
                        bootstrap(stepper,startup.check,a.log_dir/'renode-bootstrap.json')
                        # Retain this instance/epoch/id, restore normal coordinator bounds.
                        stepper.timeout=10
                        stepper.send_callback=lambda data:bounded_send(r,peer_write_lock,data,timeout=10)
                    except Exception as error:
                        raise StartupAborted('Renode startup aborted during segmented bootstrap: '+str(error)) from error
                startup.settle()
                if a.pace_rv_byte>0:
                    from paced_serial import PacedSerial
                    relay=PacedSerial(str(pty),a.pace_rv_byte)
                    pty=pathlib.Path(relay.path)
                if a.nozzle_image and not a.shared_mcus:
                    from renode_peer import start_peer
                    nozzle_pty=start_peer(a.renode,a.nozzle_model,a.nozzle_image,a.nozzle_base,tmp/'nozzle',a.log_dir,processes,a.virtual_baud,wire_source,nozzle_setup,startup_wait=startup)
                    peers['nozzle']=processes[-1]
                    if a.pace_rv_byte>0:
                        from paced_serial import PacedSerial
                        nozzle_relay=PacedSerial(str(nozzle_pty),a.pace_rv_byte)
                        nozzle_pty=pathlib.Path(nozzle_relay.path)
                if a.motor_image and not a.shared_mcus:
                    from renode_peer import start_peer
                    from pty_bridge import PtyBridge
                    motor_setup=['include @scripts/board-clock-and-rtc.resc','include @scripts/'+('generic-stationary-rl.resc' if a.motor_plant=='electrical' else 'stationary-current-plant.resc')]
                    motor_pty=start_peer(a.renode,a.motor_model,a.motor_image,0x08008000,tmp/'motor',a.log_dir,processes,a.virtual_baud,wire_source,motor_setup,uart='usart2',name='motor',startup='1',startup_wait=startup)
                    motor_proc=processes[-1];peers['motor']=motor_proc
                    motor_relay=PtyBridge(tmp/'motor-uart',motor_pty)
                monitor='none' 
                if a.screenshot or a.live_display:
                    if a.screenshot: a.screenshot.parent.mkdir(parents=True,exist_ok=True)
                    mon=tmp/'qemu-monitor'
                    for suffix in ['.in','.out']:
                        os.mkfifo(str(mon)+suffix)
                        monitor_fds.append(os.open(str(mon)+suffix,os.O_RDWR|os.O_NONBLOCK))
                    monitor='pipe:'+str(mon)
                backend={2:0,0:1,1:2,3:3,4:4,5:5}[a.rv_uart]
                args=[str(a.qemu),'-M','rv1106','-m',str(a.memory)+'M','-display','none','-monitor',monitor,'-chardev',f'serial,id=mcu,path={pty},logfile={a.log_dir}/rv-tx.bin']
                if a.live_display:
                    args[args.index('rv1106')]='rv1106,memory-backend=displayram'
                    args+=['-object',f'memory-backend-file,id=displayram,size={a.memory}M,mem-path={tmp}/guest-ram.bin,share=on']
                if nozzle_pty: args+=['-chardev',f'serial,id=nozzle,path={nozzle_pty},logfile={a.log_dir}/rv-nozzle-tx.bin']
                for i in range(max(backend,1 if nozzle_pty else 0)+1):
                    args+=['-serial','chardev:mcu' if i==backend else ('chardev:nozzle' if nozzle_pty and i==1 else ('stdio' if i==0 else 'null'))]
                args+=['-kernel',str(a.rv_image)]
                if a.cpu: args+=['-cpu',a.cpu]
                if a.disk: args+=['-drive',f'if=sd,index=0,file={a.disk},format=raw,snapshot=on']
                if a.clock_coupled:
                    if a.clock_source in ('diagnostic-timer-fixture','qom-deadline'):
                        for suffix in ('.in','.out'):os.mkfifo(str(tmp/'qmp')+suffix)
                        args+=['-qmp',f'pipe:{tmp}/qmp']
                        if a.clock_source=='qom-deadline':
                            args[args.index('-M')+1]+=',virtual-deadline-enabled=on'
                            args+=['-S']
                    else:args+=['-S','-qmp',f'unix:{tmp}/qmp.sock,server=on,wait=off']
                args+=icount_args
                (a.log_dir/'qemu-execution.json').write_text(json.dumps({'args':args,'execution_time_model':'instruction-count with idle warp' if icount_args else 'host-running elapsed time','icount_shift':a.qemu_icount_shift,'ns_per_instruction':2**a.qemu_icount_shift if icount_args else None,'physical_cycle_accuracy_claimed':False},indent=2)+'\n')
                startup.phase='before QEMU launch'
                startup.check()
                q=subprocess.Popen(args,stdin=subprocess.PIPE if command_bytes else subprocess.DEVNULL,stdout=console,stderr=qlog)
                processes.append(q)
                startup_complete=True
                if a.clock_coupled:
                    from clock_coordinator import ClockCoordinator
                    client=None
                    if a.clock_source=='diagnostic-timer-fixture':
                        from clock_fixture_runner import bootstrap_native_clock
                        client=bootstrap_native_clock(tmp/'qmp',a.log_dir/'console.bin',q,a.console_ready,a.console_chunk_bytes,a.console_chunk_delay,a.console_line_delay)
                    elif a.clock_source=='qom-deadline':
                        client=open_deadline_client(a.clock_client,tmp/'qmp')
                    if a.clock_lockstep:
                        from renode_stepper import RenodeStepper
                        from lockstep_coordinator import LockstepCoordinator
                        if stepper is None:
                            stepper=RenodeStepper(r,a.log_dir/'renode-step.json',lambda data:send_peer('main',data,select_machine=False),timeout=10)
                        clock_gate=LockstepCoordinator(client,stepper,a.log_dir/'clock-coordinator.json',max_lead_ns=5000000)
                    else:
                        clock_gate=ClockCoordinator(tmp/'qmp.sock',a.log_dir/'virtual-time.json',q,a.log_dir/'clock-coordinator.json',qmp_client=client,pulse_mode=a.clock_source=='diagnostic-timer-fixture',event_mode=a.clock_source=='qom-deadline')
                if a.live_display:
                    display_root=ROOT.parent/'rv1106-linux-display'
                    sys.path.insert(0,str(display_root))
                    from run_live import event_command
                    touch=tmp/'touch.jsonl';touch.write_text('')
                    ram=tmp/'guest-ram.bin';until=time.monotonic()+10
                    while not ram.exists() or ram.stat().st_size!=a.memory*1024*1024:
                        if q.poll() is not None or time.monotonic()>until: raise RuntimeError('QEMU shared RAM initialization failed')
                        time.sleep(.05)
                    viewer_args=[sys.executable,str(display_root/('vnc_view.py' if a.vnc else 'live_view.py')),'--ram',str(ram),'--vop',str(tmp/'live-vop.bin'),'--touch-output',str(touch),'--report',str(a.log_dir/'live-viewer.json'),'--ppm',str(a.log_dir/'live-last-frame.ppm')]
                    if a.vnc: viewer_args+=['--port',str(a.vnc_port),'--endpoint',str(a.log_dir/'vnc-endpoint.json')]
                    if a.live_headless: viewer_args+=['--headless']
                    viewer_log=(a.log_dir/'live-viewer.log').open('wb')
                    viewer=subprocess.Popen(viewer_args,stdout=viewer_log,stderr=subprocess.STDOUT)
                    processes.append(viewer)
                print(f'Connected RV1106 UART{a.rv_uart} to AT32 {a.mcu_uart} using local PTY.',flush=True)
                deadline=time.monotonic()+a.timeout
                command_started=False; next_command_chunk=0; console_input_offset=0; monitor_input_offset=0
                stop_requested=False
                while time.monotonic()<deadline:
                    if clock_gate and clock_gate.error:raise RuntimeError('Clock coordinator stopped: '+clock_gate.error)
                    if observation_stop_requested(a.stop_request):
                        stop_requested=True
                        reason={'reason':'explicit observation stop file','path':str(a.stop_request),
                                'pending_console_bytes':len(command_bytes or b''),
                                'monotonic_seconds':time.monotonic()}
                        (a.log_dir/'observation-stop.json').write_text(json.dumps(reason,indent=2)+'\n')
                        print('Observation stopped early by explicit stop file: '+str(a.stop_request),flush=True)
                        break
                    if a.peer_monitor_input and a.peer_monitor_input.exists():
                        with a.peer_monitor_input.open('rb') as source:
                            source.seek(monitor_input_offset); pending=source.read(); end=pending.rfind(b'\n')
                        if end>=0:
                            for board in (['main','nozzle'] if a.nozzle_image else ['main']):send_peer(board,pending[:end+1])
                            monitor_input_offset+=end+1
                    if viewer:
                        if a.vnc and not vnc_announced and (a.log_dir/'vnc-endpoint.json').exists():
                            ep=json.loads((a.log_dir/'vnc-endpoint.json').read_text())
                            print(f"VNC: {ep['host']}:{ep['port']} (local only; no password).",flush=True);vnc_announced=True
                        if viewer.poll() is not None:
                            if viewer.returncode: raise RuntimeError('Live viewer failed; inspect live-viewer.log')
                            break
                        if time.monotonic()>=next_vop_dump:
                            os.write(monitor_fds[0],f'pmemsave 0xff990000 0x200 "{tmp}/live-vop.bin"\n'.encode())
                            next_vop_dump=time.monotonic()+.5
                        try:
                            while True: os.read(monitor_fds[1],65536)
                        except BlockingIOError: pass
                        if command_started and not command_bytes:
                            with touch.open('r') as tf:
                                tf.seek(touch_offset)
                                while True:
                                    before=tf.tell();line=tf.readline()
                                    if not line or not line.endswith('\n'):
                                        touch_offset=before;break
                                    touch_pending+=event_command(json.loads(line));touch_offset=tf.tell()
                            if touch_pending and time.monotonic()>=next_command_chunk:
                                newline=touch_pending.find(b'\n');count=min(a.console_chunk_bytes,newline+1)
                                chunk=touch_pending[:count];touch_pending=touch_pending[count:]
                                q.stdin.write(chunk);q.stdin.flush()
                                next_command_chunk=time.monotonic()+(a.console_line_delay if chunk.endswith(b'\n') else a.console_chunk_delay)
                    if motor_relay and (motor_relay.error or motor_proc.poll() is not None): raise RuntimeError("Motor peer/bridge failed: "+str(motor_relay.error))
                    if nozzle_relay and nozzle_relay.error: raise RuntimeError('Nozzle pacing relay failed: '+nozzle_relay.error)
                    if relay and relay.error: raise RuntimeError('Serial pacing relay failed: '+relay.error)
                    out=(a.log_dir/'console.bin').read_bytes()
                    if a.console_input and command_started and not command_bytes and a.console_input.exists():
                        with a.console_input.open('rb') as extra:
                            extra.seek(console_input_offset); pending=extra.read(); end=pending.rfind(b'\n')
                        if end>=0:
                            command_bytes=pending[:end+1];console_input_offset+=end+1
                    if command_bytes and not command_started and a.console_ready.encode() in out:
                        command_started=True
                    if command_bytes and command_started and time.monotonic()>=next_command_chunk:
                        newline=command_bytes.find(b'\n')
                        count=min(a.console_chunk_bytes,newline+1 if newline>=0 else len(command_bytes))
                        chunk=command_bytes[:count]
                        q.stdin.write(chunk); q.stdin.flush(); command_bytes=command_bytes[count:]
                        next_command_chunk=time.monotonic()+(a.console_line_delay if chunk.endswith(b'\n') else a.console_chunk_delay)
                    if a.test and b'PASS: 256 UART round trips, all byte values' in out:
                        print(out.decode(errors='replace').strip()); return 0
                    if (a.test and b'FAIL:' in out) or q.poll() is not None or r.poll() is not None:
                        raise RuntimeError('Emulator stopped or test failed; inspect logs')
                    time.sleep(.01)
                if a.test: raise RuntimeError('UART test timed out; inspect logs')
                if command_bytes and not stop_requested: raise RuntimeError('Guest console commands not fully sent before timeout; check readiness and console pacing')
                if a.screenshot:
                    from capture_vop import capture
                    capture(monitor_fds,tmp,a.screenshot,a.log_dir,a.memory)
                print(('Requested observation stopped early; logs saved to ' if stop_requested else 'Requested observation interval ended; logs saved to ')+str(a.log_dir));return 0
            except StartupAborted as error:
                print(str(error),file=sys.stderr,flush=True)
                try:
                    (a.log_dir/'startup-abort.json').write_text(json.dumps({
                        'status':'aborted','phase':startup.phase,'reason':str(error),
                        'stop_request':str(a.stop_request) if a.stop_request else None,
                        'deadline_monotonic':startup.deadline,'monotonic_seconds':time.monotonic(),
                        'qemu_started':False,
                        'renode_bootstrap':a.renode_bootstrap,
                        'last_confirmed_boundary':({'step_id':stepper.step_id,
                            'virtual_time_ns':stepper.time_ns,'epoch':stepper.epoch}
                            if stepper is not None else None),
                        'uncertain_in_flight_step_id':(stepper.step_id+1
                            if stepper is not None and stepper.failed else None),
                        'initial_boundary_unconfirmed':a.renode_bootstrap=='segmented' and stepper is None
                        },indent=2)+'\n')
                except OSError as report_error:
                    note='Startup abort report unavailable: '+str(report_error)
                    error.add_note(note)
                    print(note,file=sys.stderr,flush=True)
                raise
            finally:
                original_error=sys.exc_info()[1]
                failures=CleanupFailures()
                # Spend no extra observer/outer cleanup time. Clock closure is
                # charged to the same window; reserve 3s for teardown/reporting.
                cleanup_started=time.monotonic()
                export_deadline=cleanup_started+5
                cleanup_deadline=cleanup_started+7.5 if startup_complete else None
                final_export={'status':'not_started','batches':[],
                              'export_budget_seconds':5,'cleanup_budget_seconds':8}
                def export(board,commands):
                    from final_export import acknowledge_batch
                    final_export['batches'].append(acknowledge_batch(board,commands,
                        peers,peer_write_lock,a.log_dir,a.shared_mcus,export_deadline,transport=a.final_export_transport))
                try:
                    if clock_gate:clock_gate.close()
                    # Never write to a partially loaded model or its possibly full pipe.
                    if startup_complete and not (stepper is not None and stepper.failed):
                        if a.virtual_baud:
                            for board in (['main','nozzle'] if a.nozzle_image else ['main']):
                                export(board,b'pause\nsysbus.serialWire PendingBytes\nsysbus.serialWire DeliveredBytes\nsysbus.serialWire RejectedBytes\n')
                        for board,commands in [('nozzle',nozzle_final),('main',final_commands)]:
                            if commands:
                                export(board,commands)
                        if a.motor_image:
                            export('main',b'pause\nsysbus.motorWire PendingBytes\nsysbus.motorWire DeliveredBytes\nsysbus.motorWire RejectedBytes\n')
                            wire='mainWire' if a.shared_mcus else 'serialWire'
                            export('motor',f'pause\nsysbus.{wire} PendingBytes\nsysbus.{wire} DeliveredBytes\nsysbus.{wire} RejectedBytes\ndump_file 0x20000C00 0x30 @{a.log_dir}/motor-status.bin\ndump_file 0xE000ED28 8 @{a.log_dir}/motor-cpu-faults.bin\n'.encode())
                            if a.motor_plant=='electromechanical-driver':
                                export('motor',f'machine ElapsedVirtualTime\nsysbus.genericDriver EnableInput\nsysbus.electromechanicalPlant CaptureTrace\nsysbus.electromechanicalPlant WriteCsv "{a.log_dir}/rotor-state.csv"\n'.encode())
                        final_export['status']='complete'
                    elif startup_complete and (final_commands or nozzle_final):
                        raise RuntimeError('Final export skipped after uncertain Renode step')
                    if motor_relay:
                        (a.log_dir/'motor-bridge.json').write_text(json.dumps({'direction_bytes':motor_relay.counts,'error':motor_relay.error,'plant':a.motor_plant,'timing_records_dropped':motor_relay.timing_dropped},indent=2))
                        (a.log_dir/'motor-chunk-timing.json').write_text(json.dumps(motor_relay.events,indent=2))
                except Exception as cleanup_error:
                    final_export.update(status='incomplete',error=str(cleanup_error))
                    failures.errors.append(('diagnostics/report',cleanup_error))
                finally:
                    cleanup_records=terminate_children(processes,startup_complete,failures,cleanup_deadline)
                    if startup_complete:
                        failures.attempt('save final export evidence',lambda:
                            (a.log_dir/'final-export.json').write_text(json.dumps(final_export,indent=2)+'\n'))
                    for label,resource in [('motor relay',motor_relay),('relay',relay),('nozzle relay',nozzle_relay),('viewer log',viewer_log)]:
                        if resource is not None:failures.attempt('close '+label,resource.close)
                    for fd in monitor_fds:
                        failures.attempt('close monitor',lambda fd=fd:os.close(fd))
                    def save_transcripts():
                        if (tmp/'nozzle/tx.bin').exists():
                            (a.log_dir/'nozzle-tx.bin').write_bytes((tmp/'nozzle/tx.bin').read_bytes())
                        for source,target in [('motor/tx.bin','motor-tx.bin'),('main-motor-tx.bin','main-motor-tx.bin'),('motor-tx.bin','motor-tx.bin'),('nozzle-tx.bin','nozzle-tx.bin'),('mcu-tx.bin','mcu-tx.bin')]:
                            if (tmp/source).exists(): (a.log_dir/target).write_bytes((tmp/source).read_bytes())
                    failures.attempt('save transcripts',save_transcripts)
                    if not startup_complete:
                        def save_startup_cleanup():
                            (a.log_dir/'startup-cleanup.json').write_text(json.dumps({
                                'status':'reaped' if all(record['reaped'] for record in cleanup_records) else 'unconfirmed',
                                'processes':cleanup_records,
                                'errors':[{'stage':label,'error':str(error)} for label,error in failures.errors]
                            },indent=2)+'\n')
                        failures.attempt('save startup cleanup evidence',save_startup_cleanup)
                    failures.finish(original_error)
if __name__=='__main__':
    try: sys.exit(main())
    except (RuntimeError,ValueError,OSError) as e: sys.exit(str(e))
