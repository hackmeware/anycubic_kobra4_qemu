"""Explicit synthetic Z selection. Default generation and production sources stay untouched."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re

PROFILE = 'synthetic-functional'
MAXIMUM_STATE_AGE_NS = 100000
MAXIMUM_PRODUCER_LEAD_NS = 1000
PARAMETERS = {
    'bed_relative_mm': (float, -10.0),
    'opposite_stop_relative_mm': (float, 252.0),
    'bed_side': (str, 'minimum'),
    'stiffness_n_per_mm': (float, 20.0),
    'damping_ns_per_mm': (float, 0.05),
    'baseline_counts': (int, 0),
    'counts_per_n': (float, 10000.0),
    'signal_polarity': (int, 1),
    'history_capacity': (int, 4096),
    'query_trace_rows': (int, 100000),
    'sensor_trace_rows': (int, 200000),
}


def add_arguments(parser):
    parser.add_argument('--z-probe-profile', choices=['none', PROFILE], default='none',
                        help='Explicit synthetic force/idealized CS1237/assumed PA7-PB2 fixture; no hardware timing claim')
    for key, (kind, _) in PARAMETERS.items():
        options = {'type': kind, 'default': None}
        if key == 'bed_side':
            options['choices'] = ['minimum', 'maximum']
        parser.add_argument('--z-' + key.replace('_', '-'), **options)


def parameters(args):
    return {key: getattr(args, 'z_' + key) if getattr(args, 'z_' + key) is not None else default
            for key, (_, default) in PARAMETERS.items()}


def validate(args):
    if args.z_probe_profile not in ('none', PROFILE):
        raise ValueError('Unknown Z probe profile')
    if args.z_probe_profile == 'none':
        if any(getattr(args, 'z_' + key) is not None for key in PARAMETERS):
            raise ValueError('Z fixture parameters require explicit --z-probe-profile synthetic-functional')
        return
    if not args.shared_mcus or args.motor_plant != 'electromechanical-driver':
        raise ValueError('Synthetic Z requires shared MCUs and the electromechanical-driver plant')
    p = parameters(args)
    for key, value in p.items():
        if isinstance(value, (int, float)) and not math.isfinite(value):
            raise ValueError('Z fixture parameter must be finite: ' + key)
    bed, opposite = p['bed_relative_mm'], p['opposite_stop_relative_mm']
    minimum = p['bed_side'] == 'minimum'
    if p['bed_side'] not in ('minimum', 'maximum') or max(abs(bed), abs(opposite)) > 1000 or not (bed < opposite if minimum else bed > opposite):
        raise ValueError('Invalid synthetic Z geometry')
    if not (0 < p['stiffness_n_per_mm'] <= 10000 and 0 <= p['damping_ns_per_mm'] <= 100
            and -8388608 <= p['baseline_counts'] <= 8388607 and 0 < p['counts_per_n'] <= 1e9
            and p['signal_polarity'] in (-1, 1) and 2 <= p['history_capacity'] <= 1000000
            and 0 <= p['query_trace_rows'] <= 1000000
            and 1 <= p['sensor_trace_rows'] <= 2000000):
        raise ValueError('Invalid synthetic Z calibration/history parameters')


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def expanded_setup(root, board, commands, stack=()):
    """Read nested setup includes to reject early execution or hidden clock overrides."""
    for line in commands:
        line = line.split('#', 1)[0].strip()
        if not line or line.startswith('//'):
            continue
        yield line
        include = re.fullmatch(r'include\s+@([^\s]+)', line)
        if include:
            path = root / (board + '-renode') / include[1] if not include[1].startswith('/') else Path(include[1])
            if path.suffix in ('.cs', '.repl'):
                # Source/platform definitions do not execute monitor time commands.
                # Their reserved model names are checked below, too.
                content = path.read_text()
                if re.search(r'\b(Cs1237|VirtualZBedContactFixture|zForceSource|zForceBinding|syntheticZProbe)', content):
                    raise ValueError('Synthetic Z selector exclusively owns sensor/contact/source/wiring definitions: ' + str(path))
                continue
            path = path.resolve()
            if path in stack:
                raise ValueError('Recursive Z setup include: ' + str(path))
            yield from expanded_setup(root, board, path.read_text().splitlines(), stack + (path,))


def require_setup(root, args, main, nozzle, motor):
    validate(args)
    if args.z_probe_profile == 'none':
        return
    expanded = list(expanded_setup(root, 'at32', main)) + list(expanded_setup(root, 'nozzle', nozzle)) + list(expanded_setup(root, 'motor', motor))
    # The selector has one fixed validated temporal contract. Never infer/adjust CPU rate or bounds.
    quantum = []
    for line in expanded:
        if re.search(r'\b(RunFor|RunUntil|StartAll|Reset|ResetAndClear|SetSeed)\b', line) or re.match(r'^start(?:\s|$)', line):
            raise ValueError('Synthetic Z setup must remain paused at the common zero epoch: ' + line)
        if re.search(r'\b(ConfigureRelativeContact|DisableRelativeContact)\s+(?:2|0x0*2)\b', line) or re.search(r'\b(Cs1237|VirtualZBedContactFixture|zForceSource|zForceBinding|syntheticZProbe)', line):
            raise ValueError('Synthetic Z selector must exclusively own the fixture, source and probe wiring: ' + line)
        if re.search(r'\b(PerformanceInMips|SetQuantum|SetLocalTimeSource)\b', line):
            raise ValueError('Synthetic Z profile does not permit clock/MIPS overrides: ' + line)
        if re.match(r'emulation\s+SetGlobalQuantum\b', line):
            quantum.append(bool(re.fullmatch(r'emulation\s+SetGlobalQuantum\s+"?0\.000001"?', line)))
    if not quantum or not quantum[-1]:
        raise ValueError('Synthetic Z requires an explicit final setup SetGlobalQuantum "0.000001"')


def select(root, generated, args):
    """Apply changes only to the explicitly selected isolated generated tree."""
    validate(args)
    if args.z_probe_profile == 'none':
        return None
    p = parameters(args)
    manifest_path = generated / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    extra = generated / 'z-probe-profile'
    extra.mkdir()

    def record(dest, source, transform, original_sha=None):
        entry = next((e for e in manifest if e['generated'] == str(dest.relative_to(generated))), None)
        if entry is None:
            entry = {'board': 'shared', 'generated': str(dest.relative_to(generated))}
            manifest.append(entry)
        entry.update(source=str(source.relative_to(root)), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                     generated_sha256=hashlib.sha256(dest.read_bytes()).hexdigest(), experimental_z_profile=PROFILE,
                     transformation=transform)
        if original_sha:
            entry['before_selection_sha256'] = original_sha

    def copy(relative, namespace=None):
        source = root / relative
        text = source.read_text()
        if namespace:
            text = text.replace('Antmicro.Renode.Peripherals.AT32', 'Antmicro.Renode.Peripherals.' + namespace)
        dest = extra / source.name
        dest.write_text(text)
        record(dest, source, 'AT32 namespace isolation only' if namespace else 'verbatim')
        return dest

    core = generated / 'motor/peripherals/GenericStepperElectromechanical.cs'
    before = hashlib.sha256(core.read_bytes()).hexdigest()
    extension = module(root / 'motor-renode/experimental/z-bed-contact/prepare_core.py', 'z_isolated_core')
    core.write_text(extension.extended(core.read_text()))
    record(core, root / 'motor-renode/peripherals/GenericStepperElectromechanical.cs',
           'PrinterMotor namespace isolation plus exactly two additive disable methods in generated copy only', before)
    core_entry = next(e for e in manifest if e['generated'] == str(core.relative_to(generated)))
    patch = root / 'motor-renode/experimental/z-bed-contact/disable-contact.patch'
    core_entry['reviewed_patch_sha256'] = hashlib.sha256(patch.read_bytes()).hexdigest()
    core_entry['extension_helper_sha256'] = hashlib.sha256((root / 'motor-renode/experimental/z-bed-contact/prepare_core.py').read_bytes()).hexdigest()
    copy('motor-renode/experimental/z-bed-contact/VirtualZBedContactFixture.cs', 'PrinterMotor')
    copy('nozzle-renode/experimental/cs1237-native/Cs1237NativeGpio.cs', 'PrinterNozzle')
    for name in ['Cs1237FunctionalProtocol.cs', 'Cs1237FunctionalAdapter.cs']:
        copy('nozzle-renode/experimental/cs1237-functional/' + name)
    for name in ['ZForceHistory.cs', 'MotorZForceSource.cs', 'Cs1237ZForceBinding.cs']:
        copy('printer-shared-mcu/experimental/z-force-cs1237-binding/' + name, 'PrinterMotor')
    copy('printer-shared-mcu/experimental/z-probe-profile/SyntheticZProfileEvidence.cs')

    platform = generated / 'nozzle/platforms/nozzle-f1-provisional.repl'
    before = hashlib.sha256(platform.read_bytes()).hexdigest()
    text = platform.read_text()
    anchor = 'gpioA: PrinterNozzle.AT32GPIO'
    if text.count(anchor) != 1:
        raise ValueError('Nozzle GPIO platform anchor changed; review required')
    platform.write_text(text.replace(anchor, 'gpioA: NozzleExperimental.Cs1237NativeGpio'))
    record(platform, root / 'nozzle-renode/platforms/nozzle-f1-provisional.repl', 'namespace isolation and explicit gpioA class selection only', before)
    loader = generated / 'nozzle/scripts/load.resc'
    before = hashlib.sha256(loader.read_bytes()).hexdigest()
    anchor = 'mach create "nozzle"'
    text = loader.read_text()
    if text.count(anchor) != 1:
        raise ValueError('Nozzle loader anchor changed; review required')
    loader.write_text(text.replace(anchor, f'include @{extra}/Cs1237NativeGpio.cs\n' + anchor))
    record(loader, root / 'nozzle-renode/scripts/load.resc', 'namespace/path isolation and GPIO wrapper include before platform load', before)

    def write(name, text):
        path = extra / name
        path.write_text(text)
        return path

    sensor = write('sensor.repl', f'''sensor: NozzleExperimental.Cs1237FunctionalAdapter @ sysbus
    port: gpioA
    syntheticBaseline: {p['baseline_counts']}
    outputDelayNanoseconds: 500
    idealizedElectricalSemantics: true
    maximumTraceRows: {p['sensor_trace_rows']}
''')
    fixture = write('fixture.repl', f'''zBedContactFixture: MotorExperimental.VirtualZBedContactFixture @ sysbus
    plant: electromechanicalPlant
    bedRelativeMillimeters: {p['bed_relative_mm']}
    oppositeStopRelativeMillimeters: {p['opposite_stop_relative_mm']}
    bedIsMinimum: {str(p['bed_side'] == 'minimum').lower()}
    stiffnessNewtonsPerMillimeter: {p['stiffness_n_per_mm']}
    dampingNewtonSecondsPerMillimeter: {p['damping_ns_per_mm']}
    baselineCounts: {p['baseline_counts']}
    countsPerNewton: {p['counts_per_n']}
    signalPolarity: {p['signal_polarity']}
zForceSource: PrinterExperimental.MotorZForceSource @ sysbus
    fixture: zBedContactFixture
    tmr8: tmr8
    maximumStateAgeNanoseconds: {MAXIMUM_STATE_AGE_NS}
    maximumProducerLeadNanoseconds: {MAXIMUM_PRODUCER_LEAD_NS}
    capacity: {p['history_capacity']}
    maximumTraceRows: {p['query_trace_rows']}
zProfileEvidence: PrinterExperimental.SyntheticZProfileEvidence @ sysbus
    source: zForceSource
    fixture: zBedContactFixture
''')
    # Source initial capture MUST follow enable, so load source in a separate overlay.
    fixture_text = fixture.read_text()
    split = fixture_text.index('zForceSource:')
    fixture.write_text(fixture_text[:split])
    source = write('source.repl', fixture_text[split:])
    binding = write('binding.repl', '''zForceBinding: PrinterExperimental.Cs1237ZForceBinding @ sysbus
    port: gpioA
    sensor: sensor
    sourceName: "synthetic_z_force"
''')
    nozzle = [f'include @{extra}/Cs1237FunctionalProtocol.cs', f'include @{extra}/Cs1237FunctionalAdapter.cs',
              f'machine LoadPlatformDescription @{sensor}']
    motor = [f'include @{extra}/VirtualZBedContactFixture.cs', f'include @{extra}/ZForceHistory.cs',
             f'include @{extra}/MotorZForceSource.cs', f'include @{extra}/SyntheticZProfileEvidence.cs',
             f'machine LoadPlatformDescription @{fixture}', 'sysbus.zBedContactFixture SetEnabled true',
             f'machine LoadPlatformDescription @{source}', 'sysbus.zForceSource Register "synthetic_z_force"',
             'mach set "nozzle"', f'include @{extra}/Cs1237ZForceBinding.cs', f'machine LoadPlatformDescription @{binding}',
             'mach set "motor"']
    wire = module(root / 'printer-shared-mcu/experimental/z-probe-wire/prepare_wire.py', 'z_proven_wire')
    tail = wire.connect_commands('syntheticZProbe', 'main')
    tail += [f'include @{root}/printer-shared-mcu/peripherals/PassiveGpioEdgeTrace.cs']
    for board, port, pin, label in [('nozzle', 'gpioA', 7, 'nozzle_PA7_Z'), ('main', 'gpioB', 2, 'main_PB2_Z')]:
        tail += [f'mach set "{board}"', 'machine LoadPlatformDescriptionFromString "zProbeEdges: PrinterShared.PassiveGpioEdgeTrace @ sysbus { maximumRows: 100000 }"',
                 f'sysbus.zProbeEdges Observe sysbus.{port} {pin} "{label}"',
                 f'sysbus.zProbeEdges Start "{args.log_dir}/{board}-z-probe-edges.csv"']
    tail += ['mach set "main"']
    for name, commands in [('nozzle-setup.commands', nozzle), ('motor-tail.commands', motor), ('wire-and-traces.commands', tail)]:
        write(name, '\n'.join(commands) + '\n')
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    info = {'selection': PROFILE, 'experimental': True, 'physical_timing_fidelity': False,
            'physical_geometry_and_calibration_verified': False, 'parameters': p,
            'maximum_state_age_ns': MAXIMUM_STATE_AGE_NS, 'maximum_producer_lead_ns': MAXIMUM_PRODUCER_LEAD_NS,
            'global_quantum_ns': 1000, 'clock_or_mips_changes': False, 'firmware_changes': False,
            'probe_wiring': {'source': 'actual nozzle PA7 resolved GPIO', 'destination': 'main PB2',
                             'noninverting_assumption': True, 'physical_cable_verified': False, 'destination_first': True,
                             'startup_only': True, 'target_reset_requires_new_fixture_or_reviewed_reconnect': True},
            'sensor_status_main_pb2_connected_field': 'Adapter-local capability only, not system wiring; use probe_wiring and edge traces.',
            'trace_limits': {'sensor_rows': p['sensor_trace_rows'], 'gpio_rows': 200000, 'probe_edge_rows_per_board': 100000,
                             'force_query_rows': p['query_trace_rows'], 'overflow_does_not_mean_complete_capture': True},
            'files': {str(x.relative_to(generated)): hashlib.sha256(x.read_bytes()).hexdigest() for x in sorted(extra.iterdir())},
            'wire_helper_sha256': hashlib.sha256((root / 'printer-shared-mcu/experimental/z-probe-wire/prepare_wire.py').read_bytes()).hexdigest()}
    (args.log_dir / 'z-probe-profile.json').write_text(json.dumps(info, indent=2) + '\n')
    return {'nozzle': nozzle, 'motor': motor, 'tail': tail, 'profile': info}


def final_commands(args):
    if args.z_probe_profile == 'none':
        return ''
    out = args.log_dir
    lines = ['pause', 'mach set "nozzle"', f'sysbus.zForceBinding WriteStatus "{out}/z-binding-status.json"', f'sysbus.sensor WriteStatus "{out}/z-sensor-status.json"',
             f'sysbus.sensor WriteTrace "{out}/z-sensor.csv"', f'sysbus.gpioA WriteTrace "{out}/z-nozzle-gpio.csv"',
             'sysbus.sensor Dropped', 'sysbus.gpioA Dropped', 'sysbus.gpioA Synchronizations',
             'mach set "motor"', f'sysbus.zForceSource WriteTrace "{out}/z-force-query.csv"',
             f'sysbus.zProfileEvidence WriteStatus "{out}/z-force-status.json"']
    for board in ['nozzle', 'main']:
        lines += [f'mach set "{board}"', 'sysbus.zProbeEdges Enabled', 'sysbus.zProbeEdges Stop', 'sysbus.zProbeEdges RowsWritten',
                  'sysbus.zProbeEdges DroppedRows', 'sysbus.zProbeEdges EdgeCount', 'sysbus.zProbeEdges LastError']
    lines += ['mach set "main"']
    return '\n'.join(lines) + '\n'
