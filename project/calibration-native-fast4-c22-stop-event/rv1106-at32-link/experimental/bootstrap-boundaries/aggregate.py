#!/usr/bin/env python3
"""Read-only comparison of three separately checkpointed native prefix legs."""
import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_CAPTURES = frozenset([
    'main-sram.bin', 'nozzle-sram.bin', 'motor-sram.bin',
    'mcu-tx.bin', 'nozzle-tx.bin', 'motor-tx.bin', 'main-motor-tx.bin',
    'main-homing-edges.csv', 'motor-homing-edges.csv', 'motor-state.csv',
    'nozzle-thermal.csv', 'nozzle-thermal-live.csv', 'nozzle-tmc-edges.csv'])


def compare(paths):
    if len(paths) != 3 or len({p.resolve() for p in paths}) != 3:
        raise ValueError('Three distinct native legs required')
    records = [json.loads((p/'result.json').read_text()) for p in paths]
    for p, r, mode in zip(paths, records, ['legacy', 'segmented', 'legacy']):
        if r.get('paused_motor_probe_enabled') is True or 'paused_motor_probe' in r:
            raise ValueError('Diagnostic probe arms are not equivalence baselines: '+str(p))
        if not (r['passed'] and r['clean_exit'] and r['exit_code'] == 0
                and r.get('process_group_absent') is True and r.get('watchdog_stopped') is True
                and r.get('forced_signals') == []
                and r['vendor_firmware_ran'] and r['kind'] == 'native-prefix'
                and r['mode'] == mode and r['compared_duration_ns'] == 20000000
                and r['global_quantum_ns'] == 1000):
            raise ValueError('Incomplete or invalid native leg: '+str(p))
        if set(r['captures_sha256']) != EXPECTED_CAPTURES:
            raise ValueError('Incomplete capture inventory: '+str(p))
        ack_history = json.loads((p/'acknowledgments.json').read_text())
        expected_times = [20000000] if mode == 'legacy' else list(range(0, 20000001, 1000000))
        ack = ack_history['final_ack']
        if (ack_history['actual_times_ns'] != expected_times
                or ack.get('schema') != 1 or ack.get('source') != 'renode-shared-mcu-step'
                or ack.get('enabled') is not True or ack.get('paused') is not True
                or ack.get('time_went_backwards') is not False
                or not isinstance(ack.get('epoch'), str) or not ack['epoch']
                or ack.get('virtual_time_ns') != 20000000
                or ack.get('step_id') != (0 if mode == 'legacy' else 20)
                or r.get('acknowledged_time_ns') != 20000000
                or json.loads((p/'renode-step.json').read_text()) != ack):
            raise ValueError('Invalid native acknowledgment history: '+str(p))
        for name, digest in r['captures_sha256'].items():
            if name.endswith('-sram.bin') and (p/name).stat().st_size != 0x18000:
                raise ValueError('Truncated SRAM: '+str(p/name))
            if hashlib.sha256((p/name).read_bytes()).hexdigest() != digest:
                raise ValueError('Changed capture: '+str(p/name))
    a, b, c = [r['captures_sha256'] for r in records]
    return {'passed_observed_captures_only': a == b == c,
            'baseline_repeat_equal': a == c, 'candidate_equal': a == b,
            'compared_duration_ns': 20000000, 'vendor_firmware_ran': True,
            'full_native_one_second_proven': False,
            'register_note': 'PC and SP are in each monitor log for manual review; not included in automated equivalence.',
            'differing_captures': [k for k in sorted(set(a)|set(b)|set(c)) if not a.get(k) == b.get(k) == c.get(k)]}

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline_a', type=Path)
    p.add_argument('candidate', type=Path)
    p.add_argument('baseline_b', type=Path)
    a = p.parse_args()
    result = compare([a.baseline_a, a.candidate, a.baseline_b])
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed_observed_captures_only'] else 1)
