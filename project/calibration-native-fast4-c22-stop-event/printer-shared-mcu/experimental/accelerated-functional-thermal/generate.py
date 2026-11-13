#!/usr/bin/env python3
"""Opt-in synthetic functional-test profiles. Never starts or modifies a running model."""
from pathlib import Path
import argparse, hashlib, json, math, re
BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
REFERENCE = BASE.parent / 'synthetic-calibration-thermal'
FACTORS = (1, 2, 4, 10)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def factor_value(value):
    if isinstance(value, bool):
        raise ValueError('Factor must be one of 1, 2, 4, 10; bool is not a factor')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError('Factor must be one of 1, 2, 4, 10') from None
    if not math.isfinite(number) or number not in FACTORS:
        raise ValueError('Only reviewed factors 1, 2, 4, 10 are supported')
    return int(number)

def profile_text(sensor, factor):
    factor = factor_value(factor)
    if sensor not in ('nozzle', 'bed'):
        raise ValueError('Sensor must be nozzle or bed')
    source = (REFERENCE / (sensor + '.repl')).read_text()
    capacity = (20 if sensor == 'nozzle' else 600) / factor
    result, count = re.subn(r'(?m)^(    heatCapacityJoulesPerKelvin:) [^\n]+$',
                           lambda m: m[1] + ' ' + format(capacity, '.12g'), source)
    if count != 1:
        raise RuntimeError('Expected exactly one original heat capacity')
    return (f'// SYNTHETIC ACCELERATED FUNCTIONAL TEST ONLY: {factor}x capacity scaling.\n'
            '// NOT physical-printer calibration, PID validation, stable regulation, or print readiness.\n'
            '// Only heat capacity differs from the optional synthetic baseline.\n' + result)

def parameters(factor):
    factor = factor_value(factor)
    sensors = {}
    for sensor, power, capacity, loss, target, maximum in [
            ('nozzle', 60, 20, .2, 230, 400), ('bed', 200, 600, 1.5, 60, 150)]:
        c = capacity / factor
        sensors[sensor] = dict(power_w=power, capacity_j_per_k=c, conductance_w_per_k=loss,
            ambient_c=25, model_maximum_c=maximum, target_c=target,
            initial_rate_c_per_s=power/c, time_constant_s=c/loss,
            mathematical_full_duty_equilibrium_c=25+power/loss,
            target_hold_duty=(target-25)*loss/power,
            ideal_full_power_target_seconds=-c/loss*math.log(1-(target-25)*loss/power),
            first_100ms_rise_c=power/loss*(-math.expm1(-loss*.1/c)),
            first_1s_rise_c=power/loss*(-math.expm1(-loss/c)),
            full_power_rate_at_target_c_per_s=(power-loss*(target-25))/c,
            full_power_extra_1s_rise_from_target_c=(25+power/loss-target)*(-math.expm1(-loss/c)),
            update_microseconds=10000)
    return dict(factor=factor, synthetic=True, realistic=False,
        purpose='functional command/GPIO/ADC/shutdown plumbing only; not PID validation',
        clock_scale=1, native_pwm_seconds=.1, native_sensor_smoothing_seconds=1,
        native_firmware_and_guards_unchanged=True, pb9_thermally_unbound=True, sensors=sensors)

def write_profiles(factors=FACTORS):
    for factor in factors:
        factor = factor_value(factor)
        target = BASE / 'profiles' / f'{factor}x'
        target.mkdir(parents=True, exist_ok=True)
        for sensor in ('nozzle', 'bed'):
            (target / (sensor + '.repl')).write_text(profile_text(sensor, factor))
        (target / 'parameters.json').write_text(json.dumps(parameters(factor), indent=2)+'\n')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--factor', type=factor_value, default=4,
                        help='Explicit profile to write; default 4. This does not activate it.')
    parser.add_argument('--all', action='store_true', help='Write 1x control and 2x/4x/10x comparisons')
    args = parser.parse_args()
    write_profiles(FACTORS if args.all else [args.factor])
    print('Prepared source profiles only. No running machine or central configuration changed.')
