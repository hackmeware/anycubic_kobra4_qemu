#!/usr/bin/env python3
"""Read a live/saved passive CSV once; compare explicit shared-virtual-time stages.

No commands are sent and no inputs are changed. JSON is written only to stdout.
Example: trace.csv --stage startup:0:1 --stage before:14:17 --stage homing:17:22
Stage boundaries must come from verified shared-clock evidence, not wall time.
"""
import argparse
import collections
import csv
import hashlib
import io
import json
import math
from pathlib import Path

REQUIRED = ('virtual_time_s sample trigger_count axis logical_enable '
            'derived_raw_enable_level bridge_enabled external_fault '
            'commutation_mode state_070d_raw state_0713_raw state_0716_raw '
            'status_word_raw detector_50_raw detector_51_raw control_angle_u16 '
            'control_speed_word_raw pwm_reg_00 pwm_reg_18 pwm_reg_1c pwm_reg_20 '
            'pwm_reg_2c pwm_reg_44 physical_relative_mm physical_angle_rad '
            'physical_velocity_rad_s physical_ia_amp physical_ib_amp').split()


def read_snapshot(data):
    # A concurrent write may leave a partial final line or sample. Never salvage
    # malformed interior lines or silently treat a partial sample as complete.
    end = data.rfind(b'\n') + 1
    complete = data[:end].decode('utf-8')
    lines = [line for line in complete.splitlines() if not line.startswith('#')]
    if not lines:
        return [], dict(partial_tail_bytes=len(data)-end, incomplete_sample_rows=0)
    reader = csv.DictReader(io.StringIO('\n'.join(lines)))
    missing = set(REQUIRED) - set(reader.fieldnames or [])
    if missing:
        raise ValueError('Missing columns: ' + ', '.join(sorted(missing)))
    groups, group, prior_sample, prior_time = [], [], None, None
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError('Malformed complete CSV row')
        converted = {}
        for key, value in row.items():
            converted[key] = float(value) if key == 'virtual_time_s' or key.startswith('physical_') else int(value)
            if not math.isfinite(converted[key]):
                raise ValueError('Nonfinite value in ' + key)
        row = converted
        if group and row['sample'] != group[0]['sample']:
            if [item['axis'] for item in group] != [0, 1, 2]:
                raise ValueError('Incomplete interior three-axis sample')
            groups.extend(group)
            prior_sample, prior_time = group[0]['sample'], group[0]['virtual_time_s']
            group = []
        if not group:
            if prior_sample is not None and (row['sample'] <= prior_sample or row['virtual_time_s'] < prior_time):
                raise ValueError('Sample or virtual time moved backwards')
        elif row['virtual_time_s'] != group[0]['virtual_time_s'] or row['trigger_count'] != group[0]['trigger_count']:
            raise ValueError('Inconsistent three-axis sample timestamp/counter')
        if row['axis'] != len(group):
            raise ValueError('Unexpected axis order')
        group.append(row)
    dropped = 0
    if len(group) == 3:
        groups.extend(group)
    else:
        dropped = len(group)
    return groups, dict(partial_tail_bytes=len(data)-end, incomplete_sample_rows=dropped)


def pwm(row):
    modes, selections, enables, polarities = [], [], [], []
    for channel in range(4):
        config = row['pwm_reg_18' if channel < 2 else 'pwm_reg_1c'] >> (8*(channel % 2))
        modes.append((config >> 4) & 7)
        selections.append(config & 3)
        enables.append((row['pwm_reg_20'] >> (4*channel)) & 1)
        polarities.append((row['pwm_reg_20'] >> (4*channel+1)) & 1)
    return dict(modes=modes, channel_selections=selections, channel_enables=enables,
                polarities=polarities, counter_enabled=bool(row['pwm_reg_00'] & 1),
                main_output_enable=bool(row['pwm_reg_44'] & 0x8000) if row['axis'] == 1 else None,
                period=row['pwm_reg_2c'])


def limits(rows, field):
    values = [row[field] for row in rows]
    return dict(first=values[0], last=values[-1], minimum=min(values), maximum=max(values))


def transitions(rows, field, maximum=32):
    result = []
    for before, after in zip(rows, rows[1:]):
        if before[field] != after[field]:
            result.append(dict(after_time=before['virtual_time_s'], by_time=after['virtual_time_s'],
                               before=before[field], after=after[field]))
    return dict(count=len(result), first_transitions=result[:maximum], truncated=len(result)>maximum)


def summarize(rows):
    if not rows:
        return dict(samples=0)
    categorical = ['logical_enable', 'derived_raw_enable_level', 'bridge_enabled', 'external_fault',
                   'commutation_mode', 'state_070d_raw', 'state_0713_raw', 'state_0716_raw',
                   'status_word_raw', 'detector_50_raw', 'detector_51_raw']
    states = {key: dict(sorted(collections.Counter(row[key] for row in rows).items())) for key in categorical}
    pwm_states = collections.Counter(json.dumps(pwm(row), sort_keys=True) for row in rows)
    physical = {key: limits(rows, key) for key in ['physical_relative_mm', 'physical_angle_rad',
                'physical_velocity_rad_s', 'physical_ia_amp', 'physical_ib_amp']}
    delta = rows[-1]['physical_relative_mm']-rows[0]['physical_relative_mm']
    return dict(samples=len(rows), first_time=rows[0]['virtual_time_s'], last_time=rows[-1]['virtual_time_s'],
                state_sample_counts=states,
                state_transitions={key: transitions(rows, key) for key in categorical},
                control_angle_u16=limits(rows, 'control_angle_u16'),
                control_angle_changed_intervals=sum(a['control_angle_u16'] != b['control_angle_u16'] for a,b in zip(rows,rows[1:])),
                control_speed_word_raw=limits(rows, 'control_speed_word_raw'),
                pwm_sample_counts=[dict(configuration=json.loads(config), samples=count) for config,count in pwm_states.items()],
                physical=physical, sampled_physical_delta_mm=delta)


def analyze(data, stages):
    rows, partial = read_snapshot(data)
    result = dict(snapshot_sha256=hashlib.sha256(data).hexdigest(), snapshot_bytes=len(data),
                  coverage=partial, stages=[],
                  limits='Decimated snapshots, not complete events. Control angle is a firmware reference, not rotor truth. Physical travel belongs to the assumed plant; no command acceptance, contact or homing success inferred. Stage times use shared virtual seconds. PWM configuration counts do not establish actual applied voltage.')
    for name, start, end in stages:
        selected = [row for row in rows if start <= row['virtual_time_s'] < end]
        result['stages'].append(dict(name=name, start=start, end=end if math.isfinite(end) else None,
            axes={str(axis): summarize([row for row in selected if row['axis'] == axis]) for axis in range(3)}))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', type=Path)
    parser.add_argument('--stage', action='append', default=[], metavar='NAME:START:END')
    args = parser.parse_args()
    stages = []
    for value in args.stage:
        name, start, end = value.rsplit(':', 2)
        start, end = float(start), float(end)
        if not name or not math.isfinite(start) or not math.isfinite(end) or end <= start:
            parser.error('Stage needs a name and finite increasing boundaries')
        stages.append((name, start, end))
    print(json.dumps(analyze(args.csv.read_bytes(), stages or [('all', 0, math.inf)]), indent=2))
