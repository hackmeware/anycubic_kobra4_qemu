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
    p.add_argument('--timeout',type=float,default=30)
    p.add_argument('--stop-request',type=pathlib.Path,help='Opt-in local stop-file checked during observation; preserves final diagnostics and cleanup')
    p.add_argument('--virtual-baud',type=int,help='Opt-in Renode virtual-time serial wire baud, preserves hardware RX depth')
    p.add_argument('--pace-rv-byte',type=float,default=0,help='Optional diagnostic host seconds per RV-to-MCU byte (not baud accurate)')
    p.add_argument('--nozzle-setup-commands',type=pathlib.Path,help='Explicit nozzle environment setup monitor commands before firmware runs')
    p.add_argument('--mcu-setup-commands',type=pathlib.Path,help='Explicit main MCU environment setup monitor commands before firmware runs')
    p.add_argument('--nozzle-final-commands',type=pathlib.Path,help='Diagnostic nozzle monitor commands before stopping')
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
    from accelerated_thermal_profile_selection import add_arguments as add_thermal_arguments
    add_thermal_arguments(p)
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

def quote(path):
    s=str(path)
    if any(c in s for c in '\n\r"'): raise ValueError('Path contains unsupported monitor characters')
    return '"'+s+'"'

def execution_args(a):
    from z_probe_selection import validate
    validate(a)
    from accelerated_thermal_profile_selection import validate as validate_thermal
    validate_thermal(a)
    if a.nozzle_tmc_model!='fixed' and not a.shared_mcus:
        raise ValueError('Experimental nozzle TMC selection requires shared MCUs')
    if a.trace_homing_gpio and not a.shared_mcus:
        raise ValueError('Homing GPIO trace requires shared MCUs')
    if a.motor_enable_wiring!='direct-bridge-gate' and (not a.shared_mcus or a.motor_plant!='electromechanical-driver'):
        raise ValueError('Alternate enable wiring requires shared dynamic driver profile')
    if a.assumed_xy_diag_cable and (not a.shared_mcus or a.motor_plant!='electromechanical-driver'):
        raise ValueError('Assumed diagnostic cable requires shared causal dynamic motor profile')
    if a.clock_lockstep and (not a.clock_coupled or a.clock_source!='qom-deadline' or a.qemu_icount_shift is None or not a.shared_mcus):
        raise ValueError('Lockstep requires shared MCUs, coupled QOM deadlines and explicit icount')
    if a.clock_lockstep and a.peer_monitor_input:
        raise ValueError('Lockstep rejects live monitor commands; use final diagnostics at paused completion')
    if a.qemu_icount_shift is None:return []
    if not a.clock_coupled or a.clock_source!='qom-deadline':
        raise ValueError('Instruction-count diagnostic requires coupled QOM deadline mode')
    return ['-icount',f'shift={a.qemu_icount_shift},align=off,sleep=off']

def main():
    a=parser().parse_args()
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
        from accelerated_thermal_profile_selection import final_commands as thermal_final_commands
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
    peers={}
    peer_write_lock=threading.Lock()
    def send_peer(board,data):
        peer=peers.get(board)
        if peer is None or peer.poll() is not None:return
        if a.shared_mcus:data=(f'mach set "{board}"\n').encode()+data+b'\nmach set "main"\n'
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
            try:
                r=subprocess.Popen([str(a.renode),'--disable-gui','--console',str(resc)],cwd=a.model,env=env,stdin=subprocess.PIPE,stdout=rlog,stderr=subprocess.STDOUT)
                processes.append(r);peers['main']=r
                if a.shared_mcus:peers.update(nozzle=r,motor=r);motor_proc=r
                deadline=time.monotonic()+(180 if a.shared_mcus else 60)
                while not pty.exists():
                    if r.poll() is not None or time.monotonic()>deadline or b'There was an error' in (a.log_dir/'renode.log').read_bytes():
                        raise RuntimeError('Renode did not create UART PTY; inspect renode.log')
                    time.sleep(.1)
                # PTY appears before model/load commands finish. Wait for RunFor completion.
                def initialization_ready():
                    if a.clock_lockstep:return (a.log_dir/'renode-step.json').exists()
                    return b'Starting emulation' in (a.log_dir/'renode.log').read_bytes()
                while not initialization_ready():
                    if r.poll() is not None or time.monotonic()>deadline or b'There was an error' in (a.log_dir/'renode.log').read_bytes():
                        raise RuntimeError('Renode initialization failed; inspect renode.log')
                    time.sleep(.1)
                time.sleep(.2)
                if a.pace_rv_byte>0:
                    from paced_serial import PacedSerial
                    relay=PacedSerial(str(pty),a.pace_rv_byte)
                    pty=pathlib.Path(relay.path)
                if a.nozzle_image and not a.shared_mcus:
                    from renode_peer import start_peer
                    nozzle_pty=start_peer(a.renode,a.nozzle_model,a.nozzle_image,a.nozzle_base,tmp/'nozzle',a.log_dir,processes,a.virtual_baud,wire_source,nozzle_setup)
                    peers['nozzle']=processes[-1]
                    if a.pace_rv_byte>0:
                        from paced_serial import PacedSerial
                        nozzle_relay=PacedSerial(str(nozzle_pty),a.pace_rv_byte)
                        nozzle_pty=pathlib.Path(nozzle_relay.path)
                if a.motor_image and not a.shared_mcus:
                    from renode_peer import start_peer
                    from pty_bridge import PtyBridge
                    motor_setup=['include @scripts/board-clock-and-rtc.resc','include @scripts/'+('generic-stationary-rl.resc' if a.motor_plant=='electrical' else 'stationary-current-plant.resc')]
                    motor_pty=start_peer(a.renode,a.motor_model,a.motor_image,0x08008000,tmp/'motor',a.log_dir,processes,a.virtual_baud,wire_source,motor_setup,uart='usart2',name='motor',startup='1')
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
                q=subprocess.Popen(args,stdin=subprocess.PIPE if command_bytes else subprocess.DEVNULL,stdout=console,stderr=qlog)
                processes.append(q)
                if a.clock_coupled:
                    from clock_coordinator import ClockCoordinator
                    client=None
                    if a.clock_source=='diagnostic-timer-fixture':
                        from clock_fixture_runner import bootstrap_native_clock
                        client=bootstrap_native_clock(tmp/'qmp',a.log_dir/'console.bin',q,a.console_ready,a.console_chunk_bytes,a.console_chunk_delay,a.console_line_delay)
                    elif a.clock_source=='qom-deadline':
                        from event_clock_client import EventClockClient
                        client=EventClockClient.from_pipes(tmp/'qmp')
                    if a.clock_lockstep:
                        from renode_stepper import RenodeStepper
                        from lockstep_coordinator import LockstepCoordinator
                        stepper=RenodeStepper(r,a.log_dir/'renode-step.json',lambda data:send_peer('main',data),timeout=10)
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
            finally:
                if clock_gate:clock_gate.close()
                if a.virtual_baud:
                    for board in (['main','nozzle'] if a.nozzle_image else ['main']):
                        try:send_peer(board,b'pause\nsysbus.serialWire PendingBytes\nsysbus.serialWire DeliveredBytes\nsysbus.serialWire RejectedBytes\n')
                        except OSError:pass
                    time.sleep(.3)
                for board,commands in [('nozzle',nozzle_final),('main',final_commands)]:
                    if commands:
                        try:send_peer(board,commands);time.sleep(.5)
                        except OSError as error:print('Final diagnostics unavailable: '+str(error),file=sys.stderr)
                if a.motor_image:
                    send_peer('main',b'pause\nsysbus.motorWire PendingBytes\nsysbus.motorWire DeliveredBytes\nsysbus.motorWire RejectedBytes\n')
                    wire='mainWire' if a.shared_mcus else 'serialWire'
                    send_peer('motor',f'pause\nsysbus.{wire} PendingBytes\nsysbus.{wire} DeliveredBytes\nsysbus.{wire} RejectedBytes\ndump_file 0x20000C00 0x30 @{a.log_dir}/motor-status.bin\ndump_file 0xE000ED28 8 @{a.log_dir}/motor-cpu-faults.bin\n'.encode());time.sleep(.5)
                    if a.motor_plant=='electromechanical-driver':
                        send_peer('motor',f'machine ElapsedVirtualTime\nsysbus.genericDriver EnableInput\nsysbus.electromechanicalPlant CaptureTrace\nsysbus.electromechanicalPlant WriteCsv "{a.log_dir}/rotor-state.csv"\n'.encode());time.sleep(.5)
                if motor_relay:
                    (a.log_dir/'motor-bridge.json').write_text(json.dumps({'direction_bytes':motor_relay.counts,'error':motor_relay.error,'plant':a.motor_plant,'timing_records_dropped':motor_relay.timing_dropped},indent=2))
                    (a.log_dir/'motor-chunk-timing.json').write_text(json.dumps(motor_relay.events,indent=2))
                    motor_relay.close()
                for proc in reversed(processes):
                    if proc.poll() is None: proc.terminate()
                for proc in processes:
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired: proc.kill();proc.wait()
                if relay: relay.close()
                if nozzle_relay: nozzle_relay.close()
                if (tmp/'nozzle/tx.bin').exists():
                    (a.log_dir/'nozzle-tx.bin').write_bytes((tmp/'nozzle/tx.bin').read_bytes())
                for source,target in [('motor/tx.bin','motor-tx.bin'),('main-motor-tx.bin','main-motor-tx.bin'),('motor-tx.bin','motor-tx.bin'),('nozzle-tx.bin','nozzle-tx.bin')]:
                    if (tmp/source).exists(): (a.log_dir/target).write_bytes((tmp/source).read_bytes())
                for fd in monitor_fds: os.close(fd)
                if viewer_log: viewer_log.close()
                if (tmp/'mcu-tx.bin').exists():
                    (a.log_dir/'mcu-tx.bin').write_bytes((tmp/'mcu-tx.bin').read_bytes())
if __name__=='__main__':
    try: sys.exit(main())
    except (RuntimeError,ValueError,OSError) as e: sys.exit(str(e))
