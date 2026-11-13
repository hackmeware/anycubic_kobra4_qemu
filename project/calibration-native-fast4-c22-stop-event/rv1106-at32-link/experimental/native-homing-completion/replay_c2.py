#!/usr/bin/env python3
"""Read-only deterministic replay of c2 evidence; never a c3 native pass."""
import csv
import hashlib
import io
import json
from pathlib import Path
import types

HERE = Path(__file__).resolve().parent

from test_support import source_profile, c2_run_directory

def observer_module():
    module = types.ModuleType('replay_homing_observer')
    module.__file__ = str(HERE / 'observer.py')
    exec(compile(Path(module.__file__).read_bytes(), module.__file__, 'exec'), module.__dict__)
    return module

def replay(directory=None, profile=None):
    o = observer_module()
    profile = source_profile(profile)
    directory = c2_run_directory(directory)
    boundary, base = o.cp.load(profile)
    old = json.loads((directory / 'cold-release-observation.json').read_text())
    assert old['success'] is False and old['request_count'] == 8
    assert [r['stage'] for r in old['requests']] == list(o.cp.STAGES)
    console = (directory / 'console.bin').read_bytes().decode('utf-8', errors='replace')
    review = base.NativeReview(); review.observe(console, final=True)
    assert o.review_rail_sequence(console, base) == 6
    for item in old['requests']:
        stage = item['stage']
        assert item['complete'] and (directory / (stage + '.request.bin')).read_bytes() == boundary.packet(stage)
        wire = (directory / (stage + '.response.http2.bin')).read_bytes()
        assert wire.hex() == item['result']['wire_hex']
        assert all(item['result'][k] == v for k, v in boundary.verify_wire(stage, wire).items())
        batch = next(b for b in old['batches'] if b.get('stage') == stage and b['kind'] == 'rpc')
        assert boundary.capture(stage, item['token'], console[batch['offset']:]) == item['result']
    probes = {}
    for filename, label, pin in [('nozzle-z-probe-edges.csv', 'nozzle_PA7_Z', 7), ('main-z-probe-edges.csv', 'main_PB2_Z', 2)]:
        model = o.physical.Probe(label, pin)
        model.consume((directory / filename).read_bytes(), final=True)
        model.arm(); probes[filename] = model
    pairs = o.physical.paired_z_pulses(probes, old['z_probe_floors'])
    health = o.physical.final_health((directory / 'renode.log').read_bytes().decode('utf-8'), probes)
    raw = (directory / 'physical-state.csv').read_bytes()
    lines = raw.splitlines(keepends=True)
    rows = [o.physical.Physical.parse(r) for r in csv.DictReader(io.StringIO(raw.decode('ascii')))]
    native_ns = old['rails'][2]['native_completion']['observed_shared_ns']
    status_ns = old['requests'][7]['completed_shared_ns']
    def index_before(now):
        return max(i for i, row in enumerate(rows) if row['observation_time_s'] <= now / 1e9)
    trace = o.physical.Physical()
    native_index = index_before(native_ns)
    trace.consume(b''.join(lines[:native_index + 2]), native_ns)
    at_native = {'observed_shared_ns': native_ns, 'physical_source_s': rows[native_index]['observation_time_s'],
                 'ready': trace.complete(), 'status_z_completed': False,
                 'clearance_mm': rows[native_index]['z_bed_clearance_mm'], 'z_velocity_mm_s': rows[native_index]['z_velocity_mm_s']}
    assert at_native['ready'] is False
    status_index = index_before(status_ns)
    trace.consume(b''.join(lines[:status_index + 2]), status_ns)
    anchor = {'home_z_queue_source_s': rows[index_before(old['requests'][6]['queued_shared_ns'])]['observation_time_s'],
              'probe_last_edge_source_s': max(float(m.rows[-1]['virtual_time_s']) for m in probes.values()),
              'native_complete_observed_shared_ns': native_ns, 'status_z_completed_shared_ns': status_ns,
              'status_z_completed_source_s': rows[status_index]['observation_time_s']}
    trace.arm_completion(anchor)
    at_status = {'observed_shared_ns': status_ns, 'physical_source_s': rows[status_index]['observation_time_s'],
                 'ready': trace.complete(), 'z_velocity_mm_s': rows[status_index]['z_velocity_mm_s']}
    first_ready = trace.readiness_source_s
    for i in range(status_index + 1, len(rows)):
        trace.consume(b''.join(lines[:i + 2]), round(rows[i]['observation_time_s'] * 1e9))
        if trace.complete() and first_ready is None:
            first_ready = rows[i]['observation_time_s']
    now = base.Clock().observe(base.safe_json(directory / 'virtual-time.json'))
    trace.consume(raw, now, final=True)
    o.physical.validate_status(base.safe_json(directory / 'physical-state-status.json'), len(trace.rows), final=True)
    contact = o.physical.validate_contacts((directory / 'contact-transitions.csv').read_bytes(), anchor, health['contact_rows'], trace.first_clear_source_s)
    assert at_status['ready'] is False and first_ready is not None and trace.complete()
    assert trace.clear_start > at_status['physical_source_s']
    assert trace.release_rows[0]['observation_time_s'] < at_status['physical_source_s']
    base.final_passive(directory, base.PassiveNozzle(), now, old['requests'][-1]['status_queue_source_us'])
    boundary.validate_profile(directory)
    model = o.validate_model_exports(directory, base)
    evidence = ['cold-release-observation.json', 'physical-state.csv', 'physical-state-status.json', 'renode.log',
                'contact-transitions.csv', 'console.bin', 'nozzle-z-probe-edges.csv', 'main-z-probe-edges.csv']
    return {'scope': 'OFFLINE deterministic replay of immutable c2 only; no c3 native execution or pass',
            'offline_replay_passed': True, 'native_execution_performed': False, 'c2_strict_success_unchanged': False,
            'rpc_stages': list(o.cp.STAGES), 'paired_z_pulses': pairs, 'anchor': anchor,
            'anchor_source_note': 'c2 did not persist queue physical samples; replay derives latest raw physical row at or before the recorded shared queue/completion times. c3 persists those samples directly.',
            'at_home_rail_complete': at_native, 'at_status_z_completion': at_status,
            'first_readiness_source_s': first_ready, 'settled_start_source_s': trace.clear_start,
            'final_source_s': trace.rows[-1]['observation_time_s'], 'final_clearance_mm': trace.rows[-1]['z_bed_clearance_mm'],
            'settled_duration_s': trace.rows[-1]['observation_time_s'] - trace.clear_start,
            'contact_release': contact, 'trace_health': health,
            'calibration_completed': False, 'hardware_accuracy_proven': False,
            'source_sha256': {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in evidence}}

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory', type=Path)
    parser.add_argument('--source-profile', type=Path)
    args = parser.parse_args()
    print(json.dumps(replay(args.run_directory, args.source_profile), indent=2))
