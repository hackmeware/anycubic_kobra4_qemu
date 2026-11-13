"""Exclusive opt-in thermal fixture. Never modify defaults, firmware or physical clocks."""
import hashlib
import json
from pathlib import Path
import re

PROFILE = 'synthetic-calibration'
EXPERIMENT = 'printer-shared-mcu/experimental/synthetic-calibration-thermal'
SAMPLE_US = 100000
MAXIMUM_ROWS = 100000
# Fixed reviewed component parameters. No per-run overrides are supported.
PARAMETERS = {
    'nozzle': {'heater_power_w': 60, 'heat_capacity_j_per_k': 20, 'conductance_w_per_k': 0.2,
               'ambient_c': 25, 'environment_maximum_c': 400, 'adc_channel': 0,
               'sensor': 'NTC ZM3863 HNS112HC4570G0', 'pull_resistance_ohm': 4700},
    'bed': {'heater_power_w': 200, 'heat_capacity_j_per_k': 600, 'conductance_w_per_k': 1.5,
            'ambient_c': 25, 'environment_maximum_c': 150, 'adc_channel': 8,
            'sensor': 'B3950', 'nominal_resistance_ohm': 100000, 'beta_k': 3950,
            'nominal_c': 25, 'pull_resistance_ohm': 4700},
    'update_us': 10000, 'adc_maximum': 4095, 'stop_heater_at_maximum': True,
    'pb9_thermal_connection': False, 'heater_active_high': True,
}
# This is deliberately a narrow supported setup contract, not a monitor sandbox.
# Setup inputs can only select exact reviewed stock loaders, XY contact geometry,
# passive motor/TMC traces and the declared 1us scheduling resolution.
REPLACED = {
    'main': {'at32-renode/scripts/virtual-bed-ntc.resc'},
    'nozzle': {'nozzle-renode/scripts/virtual-nozzle-ntc.resc',
               'nozzle-renode/scripts/virtual-nozzle-recovered-ntc.resc'},
    'motor': set(),
}
ALLOWED_INCLUDES = {
    'nozzle': {'nozzle-renode/scripts/virtual-tmc2209.resc',
               'nozzle-renode/scripts/passive-tmc-timing-observer.resc'},
    'main': set(),
    'motor': {'motor-renode/peripherals/PassiveMotorStateTrace.cs'},
}
ALLOWED_PLATFORMS = {'motor': {'motor-renode/platforms/passive-motor-state-trace.repl'}, 'main': set(), 'nozzle': set()}


def add_arguments(parser):
    parser.add_argument('--thermal-profile', choices=['none', PROFILE], default='none',
                        help='Explicit hypothetical 60W nozzle/200W bed, resolved GPIO-only heating; defaults unchanged')


def validate(args):
    if args.thermal_profile not in ('none', PROFILE):
        raise ValueError('Unknown thermal profile')
    if args.thermal_profile == 'none':
        return
    if not args.shared_mcus or args.motor_plant != 'electromechanical-driver':
        raise ValueError('Synthetic thermal profile requires shared MCUs and electromechanical-driver')
    if args.mcu_hext not in (None, 24000000):
        raise ValueError('Synthetic thermal profile preserves the shared main24MHz external clock')
    if args.peer_monitor_input:
        raise ValueError('Synthetic thermal profile rejects live monitor input; use normal native heater commands')
    # User-supplied paused final diagnostics must not overwrite the hot plant or
    # manufacture a successful capture after execution. Generated exports below
    # are separate and read-only with respect to the model.
    for path in [args.mcu_final_commands, args.nozzle_final_commands]:
        if path:
            validate_final_commands(path.read_text().splitlines())


def validate_final_commands(commands):
    properties = {'Dropped', 'DroppedRows', 'LastError', 'ContactRowsWritten',
                  'ContactDroppedRows', 'ContactLastError', 'IntegrationCalls',
                  'TemperatureCelsius', 'ADCValue', 'SensorFault', 'SensorCurveOutOfRange',
                  'Overtemperature', 'HeaterLatchedOff', 'LastHeaterDuty', 'LastFanDuty',
                  'Updates', 'AutomaticUpdates'}
    for original in commands:
        line = original.split('#', 1)[0].strip()
        if not line or line.startswith('//'):
            continue
        if line in ('pause', 'machine ElapsedVirtualTime') or re.fullmatch(r'mach set "(?:main|nozzle|motor)"', line):
            continue
        if re.fullmatch(r'dump_file (?:0x[0-9a-fA-F]+|[0-9]+) (?:0x[0-9a-fA-F]+|[0-9]+) @[^\s]+', line):
            continue
        if re.fullmatch(r'sysbus\.gpio[A-Z] ReadDoubleWord (?:0x[0-9a-fA-F]+|[0-9]+)', line):
            continue
        if line == 'sysbus.electromechanicalPlant StopContactTrace':
            continue
        match = re.fullmatch(r'sysbus\.(\w+) (\w+)(?: "([^"\r\n]+)")?', line)
        if match:
            name, method, path = match.groups()
            if path is None and method in properties:
                continue
            observers = {'passiveNozzleThermalObserver', 'passiveBedThermalObserver', 'tmcTimingObserver', 'passiveMotorStateTrace'}
            if name in observers and ((path is not None and method in {'WriteCsv', 'WriteStreamStatus'}) or (path is None and method == 'Stop')):
                continue
            if name in {'nativeNozzleHeaterBinding', 'syntheticBedHeaterBinding'} and path is not None and method == 'WriteStatus':
                continue
        raise ValueError('Synthetic thermal profile rejects unreviewed final command or model override: ' + line)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_sources(root):
    hashes = json.loads((root / EXPERIMENT / 'integration-reviewed-sources.json').read_text())
    for relative, expected in hashes.items():
        if sha(root / relative) != expected:
            raise ValueError('Reviewed thermal integration dependency changed; explicit review required: ' + relative)
    return hashes


def prepare_setup(root, args, main, nozzle, motor):
    """Drop only reviewed stock thermal loaders, before any generated model is loaded."""
    validate(args)
    if args.thermal_profile == 'none':
        return main, nozzle, motor
    verify_sources(root)
    result, quantum = {}, []
    for board, commands, folder in [('main', main, 'at32-renode'), ('nozzle', nozzle, 'nozzle-renode'), ('motor', motor, 'motor-renode')]:
        result[board] = []
        removed = 0
        for original in commands:
            line = original.split('#', 1)[0].strip()
            if not line or line.startswith('//'):
                result[board].append(original)
                continue
            include = re.fullmatch(r'(include|machine LoadPlatformDescription)\s+@([^\s]+)', line)
            if include:
                path = Path(include[2])
                path = (root / folder / path).resolve() if not path.is_absolute() else path.resolve()
                try:
                    relative = str(path.relative_to(root.resolve()))
                except ValueError:
                    raise ValueError('Synthetic thermal setup rejects unreviewed external includes: ' + line)
                if include[1] == 'include' and relative in REPLACED[board]:
                    removed += 1
                    if removed > 1:
                        raise ValueError('Multiple thermal writers selected for ' + board)
                    continue
                permitted = ALLOWED_INCLUDES if include[1] == 'include' else ALLOWED_PLATFORMS
                if relative in permitted[board]:
                    result[board].append(original)
                    continue
                raise ValueError('Synthetic thermal profile exclusively owns thermal writers/bindings; unreviewed setup include: ' + line)
            if re.fullmatch(r'emulation\s+SetGlobalQuantum\s+"?0\.000001"?', line):
                quantum.append(True)
            elif board == 'motor' and re.fullmatch(r'sysbus\.electromechanicalPlant ConfigureRelativeContact [01] [-+0-9.eE]+ [-+0-9.eE]+ [-+0-9.eE]+ [-+0-9.eE]+', line):
                pass
            elif board == 'motor' and re.fullmatch(r'sysbus\.(?:passiveMotorStateTrace Start "[^"\r\n]+"|electromechanicalPlant StartContactTrace "[^"\r\n]+" 100000 true)', line):
                pass
            else:
                raise ValueError('Unreviewed synthetic thermal setup command or override: ' + line)
            result[board].append(original)
    if not quantum:
        raise ValueError('Synthetic thermal profile requires explicit setup SetGlobalQuantum "0.000001"')
    return result['main'], result['nozzle'], result['motor']


def select(root, generated, args, *, publish=True):
    validate(args)
    if args.thermal_profile == 'none':
        return None
    source_hashes = verify_sources(root)
    extra = generated / 'thermal-profile'
    extra.mkdir()
    manifest_path = generated / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())

    def copy(relative, namespace):
        source = root / relative
        text = source.read_text().replace('Antmicro.Renode.Peripherals.AT32', 'Antmicro.Renode.Peripherals.' + namespace)
        text = re.sub(r'\bAT32\.', namespace + '.', text)
        dest = extra / source.name
        dest.write_text(text)
        manifest.append({'board': 'shared', 'source': relative, 'source_sha256': sha(source),
                         'generated': str(dest.relative_to(generated)), 'generated_sha256': sha(dest),
                         'experimental_thermal_profile': PROFILE, 'transformation': 'AT32 namespace isolation only'})
        return dest

    bed_binding = copy(EXPERIMENT + '/ResolvedBedHeaterBinding.cs', 'PrinterMain')
    bed_observer = copy(EXPERIMENT + '/PassiveBedThermalObserver.cs', 'PrinterMain')
    bed = copy(EXPERIMENT + '/bed.repl', 'PrinterMain')
    nozzle = copy(EXPERIMENT + '/nozzle.repl', 'PrinterNozzle')
    # Unchanged production thermal and nozzle binding/observer sources already exist
    # in the generated namespace-isolated tree. Each fixture owns exactly one ADC.
    main = [f'include @{generated}/main/peripherals/VirtualPrinterThermal.cs', f'include @{bed_binding}',
            f'machine LoadPlatformDescription @{bed}', f'include @{bed_observer}',
            'machine LoadPlatformDescriptionFromString "passiveBedThermalObserver: PrinterMain.PassiveBedThermalObserver @ sysbus { portA: gpioA; thermal: virtualBedNTC; sampleMicroseconds: 100000; maximumRows: 100000 }"',
            f'sysbus.passiveBedThermalObserver Start "{args.log_dir}/bed-thermal-live.csv"']
    nozzle_commands = [f'include @{generated}/nozzle/peripherals/VirtualPrinterThermal.cs',
                       f'include @{generated}/nozzle/peripherals/NativeNozzleHeaterBinding.cs',
                       f'machine LoadPlatformDescription @{nozzle}',
                       f'include @{generated}/nozzle/scripts/passive-nozzle-thermal-observer.resc',
                       f'sysbus.passiveNozzleThermalObserver Start "{args.log_dir}/nozzle-thermal-live.csv"']
    for name, commands in [('main-setup.commands', main), ('nozzle-setup.commands', nozzle_commands)]:
        path = extra / name
        path.write_text('\n'.join(commands) + '\n')
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    info = {'selection': PROFILE, 'hypothetical_fixture': True, 'physical_printer_accuracy_claimed': False,
            'parameters': PARAMETERS, 'global_quantum_ns': 1000, 'firmware_changes': False,
            'clock_or_mips_changes': False, 'native_guards_unchanged': True,
            'setup': 'fresh paused zero-epoch generated selection; ordinary ADC writers omitted, never stacked/hot-swapped',
            'heater_bindings': {'nozzle': 'actual resolved PB8 to thermal input0', 'bed': 'actual resolved PA0 to thermal input0',
                                'pb9': 'observed only, no thermal connection; physical fan coupling unknown'},
            'bed_sensor_calibration_verified': False, 'direct_duty_or_temperature_overrides': False,
            'telemetry': {'sample_us': SAMPLE_US, 'maximum_rows_per_buffer_and_stream': MAXIMUM_ROWS,
                          'nozzle': 'nozzle-thermal-live.csv', 'bed': 'bed-thermal-live.csv',
                          'time_domain': 'source-local Renode clock, not host time; bed also records elapsed nanoseconds without synchronization',
                          'native_guard_state_in_model_observer': False, 'native_temperatures_in_model_observer': False,
                          'loss_or_error_invalidates_complete_capture': True},
            'source_sha256': source_hashes,
            'integration_helper_sha256': sha(Path(__file__)),
            'files': {str(p.relative_to(generated)): sha(p) for p in sorted(extra.iterdir())}}
    # Composed callers publish only after all layers have supplied their contract.
    if publish:
        (args.log_dir / 'thermal-profile.json').write_text(json.dumps(info, indent=2) + '\n')
    return {'main': main, 'nozzle': nozzle_commands, 'profile': info}


def final_commands(args):
    if args.thermal_profile == 'none':
        return ''
    lines = ['pause']
    for board, name, observer, binding, fixture in [
            ('nozzle', 'nozzle', 'passiveNozzleThermalObserver', 'nativeNozzleHeaterBinding', 'virtualNozzleNTC'),
            ('main', 'bed', 'passiveBedThermalObserver', 'syntheticBedHeaterBinding', 'virtualBedNTC')]:
        lines += [f'mach set "{board}"', f'sysbus.{observer} WriteCsv "{args.log_dir}/{name}-thermal.csv"',
                  f'sysbus.{observer} Stop', f'sysbus.{observer} WriteStreamStatus "{args.log_dir}/{name}-thermal-live-status.json"',
                  f'sysbus.{binding} WriteStatus "{args.log_dir}/{name}-heater-binding.json"']
        lines += [f'sysbus.{fixture} {property}' for property in ['TemperatureCelsius', 'ADCValue', 'SensorFault', 'Overtemperature', 'HeaterLatchedOff', 'LastHeaterDuty', 'LastFanDuty', 'Updates', 'AutomaticUpdates']]
        if board == 'nozzle':
            lines += [f'sysbus.{fixture} SensorCurveOutOfRange']
    return '\n'.join(lines + ['mach set "main"']) + '\n'
