"""Prepare one Renode emulation containing three namespace-isolated MCU models."""
import pathlib,re,struct,subprocess,sys,json,hashlib

def prepare(a,tmp,main_setup,nozzle_setup):
    root=pathlib.Path(__file__).resolve().parents[2]
    from accelerated_thermal_profile_selection import prepare_setup as prepare_thermal_setup, select as select_thermal
    motor_setup=a.motor_setup_commands.read_text().splitlines() if a.motor_setup_commands else []
    main_setup,nozzle_setup,motor_setup=prepare_thermal_setup(root,a,main_setup,nozzle_setup,motor_setup)
    if a.nozzle_tmc_model=='autobaud':
        from tmc_model_selection import require_quantum
        extra=motor_setup
        require_quantum(main_setup+nozzle_setup+extra)
    from z_probe_selection import require_setup as require_z_setup, select as select_z
    require_z_setup(root,a,main_setup,nozzle_setup,motor_setup)
    generated=tmp/'shared-models'
    subprocess.run([sys.executable,str(root/'printer-shared-mcu/tools/generate.py'),'--root',str(root),'--output',str(generated)],check=True,stdout=subprocess.DEVNULL)
    from tmc_model_selection import select
    tmc_selection=select(root,generated,a.nozzle_tmc_model)
    z_selection=select_z(root,generated,a)
    thermal_selection=select_thermal(root,generated,a)
    if a.motor_plant=='electromechanical-driver':
        bootstrap=generated/'shared-load.resc'
        text=bootstrap.read_text().replace('motor/scripts/generic-stationary-rl.resc','motor/scripts/generic-electromechanical.resc')
        driver_platform='generic-driver.repl' if a.motor_enable_wiring=='direct-bridge-gate' else 'generic-driver-mcu-control-only.repl'
        text+='\n'.join(['', 'mach set "main"', 'emulation CreateGPIOConnector "motorEnable"',
            'connector Connect sysbus.gpioC motorEnable', 'motorEnable SelectSourcePin sysbus.gpioC 13',
            'mach set "motor"', f'include @{generated}/motor/peripherals/GenericMotorDriver.cs',
            f'machine LoadPlatformDescription @{generated}/motor/platforms/{driver_platform}',
            'connector Connect sysbus.genericDriver motorEnable', 'motorEnable SelectDestinationPin sysbus.genericDriver 0',
            'mach set "main"', 'sysbus.gpioC OnGPIO 13 true', ''])
        bootstrap.write_text(text)
    if a.assumed_xy_diag_cable:
        bootstrap=generated/'shared-load.resc'
        cable=[]
        for axis,source_pin,target_pin in [('X',5,6),('Y',4,15)]:
            name='assumedDiag'+axis
            cable += ['mach set "motor"',f'emulation CreateGPIOConnector "{name}"',
                f'connector Connect sysbus.gpioB {name}',f'{name} SelectSourcePin sysbus.gpioB {source_pin}',
                'mach set "main"',f'connector Connect sysbus.gpioA {name}',
                f'{name} SelectDestinationPin sysbus.gpioA {target_pin}']
        bootstrap.write_text(bootstrap.read_text()+'\n'.join(cable)+'\n')
    (a.log_dir/'shared-model-manifest.json').write_bytes((generated/'manifest.json').read_bytes())
    (a.log_dir/'shared-profile.json').write_text(json.dumps({'mcu_time_domain':'shared Renode emulation','qemu_time_domain':'independent Linux/QEMU clock','gpio_connection':'main PA8 to motor TMR2 CH1 capture input','uart_connection':'main USART2 to motor USART2 via virtual576000baud','firmware_sha256':{name:hashlib.sha256(image.read_bytes()).hexdigest() for name,image in [('main',a.mcu_image),('nozzle',a.nozzle_image),('motor',a.motor_image)]}},indent=2)+'\n')
    def setup(board,lines):
        return [re.sub(r'@(scripts|platforms|peripherals)/([^\s"\n]+)',lambda m:'@'+str(generated/board/m[1]/m[2]),line) for line in lines]
    lines=[f'include @{generated}/shared-load.resc']
    if thermal_selection:
        main_setup=thermal_selection['main']+main_setup
        nozzle_setup=thermal_selection['nozzle']+nozzle_setup
    if z_selection:
        nozzle_setup=nozzle_setup+z_selection['nozzle']
        motor_setup=motor_setup+z_selection['motor']
    for board,image,base,commands in [('main',a.mcu_image,a.mcu_base,main_setup),('nozzle',a.nozzle_image,a.nozzle_base,nozzle_setup),('motor',a.motor_image,0x08008000,motor_setup)]:
        sp,pc=struct.unpack_from('<II',image.read_bytes())
        lines += [f'mach set "{board}"',f'sysbus LoadBinary @{image} 0x{base:x}',f'cpu VectorTableOffset 0x{base:x}',f'cpu SP 0x{sp:x}',f'cpu PC 0x{pc:x}']
        if board=='main' and a.mcu_hext:lines += [f'sysbus.crm HextFrequency {a.mcu_hext}']
        lines += setup(board,commands)
        if board in ('main','nozzle'):
            ns='PrinterMain' if board=='main' else 'PrinterNozzle'
            pty=tmp/('uart' if board=='main' else 'nozzle-uart')
            if board=='nozzle':lines += [f'include @{generated}/nozzle/peripherals/AT32F403A_VirtualSerialWire.cs']
            lines += [f'machine LoadPlatformDescriptionFromString "serialWire: {ns}.AT32VirtualSerialWire @ sysbus {{ uart: usart1; baud: 576000 }}"',f'emulation CreateUartPtyTerminal "{board}Host" "{pty}"',f'connector Connect sysbus.serialWire {board}Host']
        uart='usart2' if board=='motor' else 'usart1'
        filename={'main':'mcu-tx.bin','nozzle':'nozzle-tx.bin','motor':'motor-tx.bin'}[board]
        lines += [f'sysbus.{uart} CreateFileBackend @{tmp}/{filename}']
        if board=='main':lines += [f'sysbus.usart2 CreateFileBackend @{tmp}/main-motor-tx.bin']
    if z_selection:lines += z_selection['tail']
    if a.trace_homing_gpio:
        lines += [f'include @{root}/printer-shared-mcu/peripherals/PassiveGpioEdgeTrace.cs']
        for board,signals in [('main',[('gpioA',6,'main_PA6_X'),('gpioA',15,'main_PA15_Y'),('gpioC',13,'main_PC13')]),('motor',[('gpioB',5,'motor_PB5_X'),('gpioB',4,'motor_PB4_Y'),('gpioB',2,'motor_PB2')])]:
            lines += [f'mach set "{board}"','machine LoadPlatformDescriptionFromString "homingEdges: PrinterShared.PassiveGpioEdgeTrace @ sysbus { maximumRows: 100000 }"']
            lines += [f'sysbus.homingEdges Observe sysbus.{port} {pin} "{label}"' for port,pin,label in signals]
            lines += [f'sysbus.homingEdges Start "{a.log_dir}/{board}-homing-edges.csv"']
    if a.clock_coupled:
        lines += ['mach set "main"',f'include @{root}/printer-shared-mcu/peripherals/VirtualTimeTelemetry.cs','machine LoadPlatformDescriptionFromString "timeTelemetry: PrinterShared.VirtualTimeTelemetry @ sysbus { periodMicroseconds: 1000 }"',f'sysbus.timeTelemetry Enable "{a.log_dir}/virtual-time.json"']
    if a.nozzle_tmc_model=='autobaud' or z_selection or thermal_selection:
        lines += ['emulation SetGlobalQuantum "0.000001"'] # Reassert the explicitly validated setting after includes.
    lines += ['emulation RunFor "1"','mach set "main"']
    if a.clock_lockstep:
        lines += [f'sysbus.timeTelemetry PublishStep "{a.log_dir}/renode-step.json" 0']
    else:
        lines += ['start']
    script=tmp/'shared-link.resc';script.write_text('\n'.join(lines)+'\n')
    # Retain exact run configuration before the temporary executor tree disappears.
    (a.log_dir/'shared-link.resc.txt').write_text(script.read_text())
    (a.log_dir/'shared-load.resc.txt').write_text((generated/'shared-load.resc').read_text())
    profile_path=a.log_dir/'shared-profile.json'
    profile=json.loads(profile_path.read_text())
    if z_selection:profile['z_probe_profile']=z_selection['profile']
    if thermal_selection:profile['thermal_profile']=thermal_selection['profile']
    profile['nozzle_tmc_model']=tmc_selection
    profile['motor_plant']=a.motor_plant
    profile['motor_enable_wiring']={'assumption':a.motor_enable_wiring,'physical_pcb_verified':False,'supply_and_external_fault_gates_preserved':True}
    profile['clock_lockstep']=a.clock_lockstep
    profile['passive_homing_gpio_edges']=a.trace_homing_gpio
    profile['assumed_xy_diag_cable']={'enabled':a.assumed_xy_diag_cable,'mapping':'motor PB5 -> main PA6; motor PB4 -> main PA15','inverting':False,'physical_pcb_wiring_verified':False,'source':'genuine motor GPIO outputs only; never geometric stop or firmware RAM writes'}
    if a.clock_lockstep:profile['qemu_time_domain']='explicit instruction-count virtual clock, paired1ms paused-boundary advancement'
    if a.motor_plant=='electromechanical-driver':
        profile['enable_net']='main PC13 to motor PB2, active-low; released input pull-high hypothesis'
        profile['electrical_fault_inputs']='active-low X PA12, Y PB1, Z PC12'
        profile['homing_state_modified']=False
    profile_path.write_text(json.dumps(profile,indent=2)+'\n')
    return script,tmp/'nozzle-uart'
