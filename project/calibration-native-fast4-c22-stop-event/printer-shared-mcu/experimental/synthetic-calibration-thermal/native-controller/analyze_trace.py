"""Independent arithmetic over frozen actual GPIO/physical/ADC traces; no execution."""
import csv
import json
import io
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[4]


def analyze(path, heater, *, power_override=None, profile_selection='synthetic-calibration'):
    if heater not in ('nozzle', 'bed'):
        raise ValueError('Unknown heater')
    rows = list(csv.DictReader(io.StringIO(path.read_text())))
    if not rows or int(rows[0]['time_us']) != 0 or int(rows[0]['thermal_updates']) != 0:
        raise ValueError('Cannot independently replay trace without fresh zero-epoch start')
    nozzle = heater == 'nozzle'
    pin, levelkey = ('PB8', 'pb8_level') if nozzle else ('PA0', 'pa0_level')
    power, capacity, loss = (60, 20, .2) if nozzle else (200, 600, 1.5)
    factors = {'synthetic-calibration': 1, 'accelerated-functional-4x': 4}
    capacity /= factors[profile_selection]
    if power_override is not None:
        power = power_override  # Offline historical replay test only; never a model/runner option.
    changes = [(int(r['time_us']), int(r['changed_level'])) for r in rows
               if r['event'] == 'edge' and r['changed_pin'] == pin]
    previous, level = -1, int(rows[0][levelkey])
    for stamp, value in changes:
        if stamp < previous or value not in (0, 1) or value == level:
            raise ValueError('GPIO transitions missing/repeated/backwards')
        previous, level = stamp, value
    pos, level, temp = 0, int(rows[0][levelkey]), 25.
    predicted = [(temp, 0.)]
    high_total = 0
    max_updates = max(int(r['thermal_updates']) for r in rows)
    if max_updates > 36000:
        raise ValueError('Trace exceeds explicit360s integration budget')
    for i in range(1, max_updates + 1):
        low, high = (i - 1) * 10000, i * 10000
        mark, on = low, 0
        while pos < len(changes) and changes[pos][0] <= high:
            stamp, value = changes[pos]
            if stamp < mark:
                raise ValueError('Backwards GPIO window')
            on += (stamp - mark) * level
            level, mark = value, stamp
            pos += 1
        on += (high - mark) * level
        high_total += on
        duty = on / 10000.
        equilibrium = 25 + power * duty / loss
        temp = equilibrium + (temp - equilibrium) * math.exp(-loss * .01 / capacity)
        predicted.append((temp, duty))
    segments = json.loads((ROOT / 'evidence/recovered-nozzle-thermal/nozzle-thermal-recovered-evidence.json').read_text())['live_converter']['segments']

    def adc(temperature):
        if nozzle:
            for segment in segments:
                upper = segment['resistance_upper_breakpoint_ohms']
                m, c = segment['temperature_per_ohm'], segment['temperature_intercept_celsius']
                if temperature >= upper * m + c:
                    resistance = (temperature - c) / m
                    break
            else:
                raise ValueError('Nozzle outside recovered native curve')
        else:
            resistance = 100000 * math.exp(3950 * (1 / (temperature + 273.15) - 1 / 298.15))
        return math.floor(4095 * resistance / (4700 + resistance) + .5)

    t_error, duty_error = 0., 0.
    for row in rows:
        if any(row[key] != '0' for key in ('model_overtemperature', 'model_heater_latched_off', 'last_fan_duty')) or row['sensor_fault'] != 'none':
            raise ValueError('Faulted trace cannot establish nominal causal replay')
        actual = float(row['physical_temperature_c'])
        predicted_t, predicted_duty = predicted[int(row['thermal_updates'])]
        t_error = max(t_error, abs(actual - predicted_t))
        duty_error = max(duty_error, abs(float(row['last_heater_duty']) - predicted_duty))
        if int(row['published_adc_code']) != adc(actual):
            raise ValueError('ADC disagrees with unchanged sensor equation')
    if t_error > 3e-6 or duty_error > 1e-12:
        raise ValueError('GPIO-derived heat/duty does not match physical trace: ' + str((t_error, duty_error)))
    return {'profile_selection': profile_selection, 'heat_capacity_j_per_k': capacity, 'rows': len(rows), 'heater_edges': len(changes), 'integrated_high_us': high_total,
            'gpio_energy_j': power * high_total / 1e6,
            'max_physical_error_c_from_gpio': t_error, 'max_duty_error_from_gpio': duty_error,
            'all_adc_codes_match_unchanged_sensor': True,
            'scope': 'Independent frozen GPIO arithmetic, not a native PID completion flag'}
