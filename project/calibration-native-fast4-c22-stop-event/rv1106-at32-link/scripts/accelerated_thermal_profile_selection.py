"""Explicit capacity-scaled functional fixture; legacy selections delegate unchanged.

No native run, runtime clock scaling, PID retuning, or realistic calibration claim.
"""
import copy
import json
from pathlib import Path
import re

import thermal_profile_selection as baseline

EXPERIMENT = 'printer-shared-mcu/experimental/accelerated-functional-thermal'
PROFILES = {'accelerated-functional-4x': 4, 'accelerated-functional-2x': 2}


def add_arguments(parser):
    parser.add_argument('--thermal-profile', choices=['none', baseline.PROFILE, *PROFILES], default='none',
                        help='Explicit hypothetical thermal fixture; accelerated choices are capacity-only functional tests, never real PID validation')


def baseline_args(args):
    if args.thermal_profile not in PROFILES:
        return args
    result = copy.copy(args)
    result.thermal_profile = baseline.PROFILE
    return result


def validate(args):
    # The original helper remains byte-for-byte untouched. Its requirements,
    # setup ownership, diagnostics policy, original clocks and guards all apply.
    baseline.validate(baseline_args(args))


def verify_accelerated_sources(root, selection):
    if selection not in PROFILES:
        raise ValueError('Unreviewed accelerated thermal selection')
    hashes = json.loads((root / EXPERIMENT / 'integration-reviewed-sources.json').read_text())
    for relative, expected in hashes.items():
        if baseline.sha(root / relative) != expected:
            raise ValueError('Reviewed accelerated thermal dependency changed: ' + relative)
    factor = PROFILES[selection]
    selected = root / EXPERIMENT / 'profiles' / (str(factor) + 'x')
    parameters = json.loads((selected / 'parameters.json').read_text())
    required = {'factor': factor, 'synthetic': True, 'realistic': False, 'clock_scale': 1,
                'native_firmware_and_guards_unchanged': True, 'pb9_thermally_unbound': True}
    if any(parameters.get(key) != value for key, value in required.items()):
        raise ValueError('Invalid accelerated functional scenario declarations')
    # Independent of the hash list, permit exactly one changed physical parameter
    # per heater. Ignore comments/empty lines only, not REPL definitions or values.
    for heater, capacity in [('nozzle', 20 / factor), ('bed', 600 / factor)]:
        original = (root / baseline.EXPERIMENT / (heater + '.repl')).read_text()
        expected, count = re.subn(r'(?m)^(    heatCapacityJoulesPerKelvin:) [^\n]+$',
                                  lambda m: m[1] + ' ' + format(capacity, '.12g'), original)
        significant = lambda text: [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith('//')]
        if count != 1 or significant((selected / (heater + '.repl')).read_text()) != significant(expected):
            raise ValueError('Accelerated profile must change heat capacity only: ' + heater)
        source = baseline.PARAMETERS[heater]
        required_values = {'power_w': source['heater_power_w'], 'capacity_j_per_k': capacity,
                           'conductance_w_per_k': source['conductance_w_per_k'], 'ambient_c': 25,
                           'model_maximum_c': source['environment_maximum_c'], 'update_microseconds': 10000}
        if any(parameters['sensors'][heater].get(key) != value for key, value in required_values.items()):
            raise ValueError('Accelerated parameter manifest differs from its selected fixed fixture: ' + heater)
    return hashes, parameters, selected


def prepare_setup(root, args, main, nozzle, motor):
    if args.thermal_profile in PROFILES:
        verify_accelerated_sources(root, args.thermal_profile)
    return baseline.prepare_setup(root, baseline_args(args), main, nozzle, motor)


def select(root, generated, args):
    if args.thermal_profile not in PROFILES:
        # No new files, fields, hashes, naming, profile parameters or command
        # ordering for none/synthetic-calibration. Their output is byte-identical.
        return baseline.select(root, generated, args)
    validate(args)
    accelerated_hashes, scenario, selected = verify_accelerated_sources(root, args.thermal_profile)
    selection = baseline.select(root, generated, baseline_args(args))
    extra = generated / 'thermal-profile'
    manifest_path = generated / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    factor = PROFILES[args.thermal_profile]
    # This is generation only: replace the sole selected platform description
    # BEFORE the generated setup is executed. Never stack or hot-swap ADC writers.
    for heater, namespace in [('bed', 'PrinterMain'), ('nozzle', 'PrinterNozzle')]:
        source = selected / (heater + '.repl')
        dest = extra / (heater + '.repl')
        text = source.read_text().replace('Antmicro.Renode.Peripherals.AT32', 'Antmicro.Renode.Peripherals.' + namespace)
        text = re.sub(r'\bAT32\.', namespace + '.', text)
        dest.write_text(text)
        matches = [entry for entry in manifest if entry['generated'] == str(dest.relative_to(generated))]
        if len(matches) != 1:
            raise ValueError('Expected exactly one generated thermal platform: ' + heater)
        matches[0].update(source=str(source.relative_to(root)), source_sha256=baseline.sha(source),
                          generated_sha256=baseline.sha(dest))
    for entry in manifest:
        if entry.get('experimental_thermal_profile') == baseline.PROFILE:
            entry['experimental_thermal_profile'] = args.thermal_profile
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    info = selection['profile']
    info['selection'] = args.thermal_profile
    info['parameters'] = copy.deepcopy(info['parameters'])
    for heater in ('nozzle', 'bed'):
        info['parameters'][heater]['heat_capacity_j_per_k'] /= factor
    info.update(functional_acceleration_factor=factor, unrealistic_dynamics=True, real_pid_validation=False,
                purpose='Explicit accelerated functional command/GPIO/ADC/shutdown test, not physical printer calibration or real PID validation',
                capacity_scaling_only=True, native_pid_and_sensor_smoothing_unchanged=True,
                emulation_clock_scale=1, automatic_factor_fallback=False,
                accelerated_scenario=scenario,
                baseline_integration_helper_sha256=info['integration_helper_sha256'],
                integration_helper_sha256=baseline.sha(Path(__file__)))
    info['source_sha256'].update(accelerated_hashes)
    info['files'] = {str(path.relative_to(generated)): baseline.sha(path) for path in sorted(extra.iterdir())}
    (args.log_dir / 'thermal-profile.json').write_text(json.dumps(info, indent=2) + '\n')
    return selection


def final_commands(args):
    return baseline.final_commands(baseline_args(args))
