#!/usr/bin/env python3
"""Passive post-ack command plan and strict, read-only diagnostic verification.

Importing or executing this module never starts an emulator or any subprocess.
A successful diagnostic is not evidence of baseline or segmented equivalence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BOARDS = ('main', 'nozzle', 'motor')
PHASES = ('before-a', 'between-a-b', 'after-b', 'before-existing', 'after-existing')
DUMP_SIZE = 0x18000
SOURCE = 'paused-motor-probe'
EXPECTED_CAPTURES = frozenset((
    'main-sram.bin', 'nozzle-sram.bin', 'motor-sram.bin',
    'mcu-tx.bin', 'nozzle-tx.bin', 'motor-tx.bin', 'main-motor-tx.bin',
    'main-homing-edges.csv', 'motor-homing-edges.csv', 'motor-state.csv',
    'nozzle-thermal.csv', 'nozzle-thermal-live.csv', 'nozzle-tmc-edges.csv'))
UNAVAILABLE = {
    'full_cpu_registers': 'unavailable: no verified full-register API used',
    'instruction_counts': 'unavailable: no verified instruction-count API used',
    'crm_frequencies': 'unavailable: omitted from minimal passive helper',
    'pc_sp_automated_comparison': 'unavailable: existing PC/SP monitor outputs remain manual-only',
    'timer_and_peripheral_hidden_state': 'unavailable: intentionally not read',
}


def fence_commands(out, phase):
    if phase not in PHASES:
        raise ValueError('Unknown fence phase')
    commands = []
    for board in BOARDS:
        commands += [f'mach set "{board}"',
                     f'sysbus.pausedMotorProbe Export "{out}/probe-{phase}-{board}.json" "{board}" "{phase}"']
    return commands


def before_capture_commands(out):
    # The initial mapped-memory anchor precedes helper compilation/installation.
    # It is post-ack, but intentionally has no new per-board fence before it.
    commands = ['mach set "motor"',
                f'dump_file 0x20000000 0x18000 @{out}/motor-probe-anchor.bin',
                'cpu PC', 'cpu SP', f'include @{HERE}/PausedMotorProbe.cs']
    for board in BOARDS:
        commands += [f'mach set "{board}"',
                     'machine LoadPlatformDescriptionFromString "pausedMotorProbe: BootstrapExperiment.PausedMotorProbe @ sysbus"']
    commands += fence_commands(out, 'before-a')
    commands += ['mach set "motor"', f'dump_file 0x20000000 0x18000 @{out}/motor-probe-a.bin', 'cpu PC', 'cpu SP']
    commands += fence_commands(out, 'between-a-b')
    commands += ['mach set "motor"', f'dump_file 0x20000000 0x18000 @{out}/motor-probe-b.bin', 'cpu PC', 'cpu SP']
    commands += fence_commands(out, 'after-b')
    commands += fence_commands(out, 'before-existing')
    return commands


def after_capture_commands(out):
    return fence_commands(out, 'after-existing')


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: '+key)
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=unique)


def validate_probe(out):
    """Validate observations only; full acceptance additionally needs both guards."""
    local_times, fences, dumps = {}, {}, {}
    instability = []
    expected_keys = {'schema', 'source', 'board', 'phase', 'phase_index',
                     'paused_before', 'paused_after', 'local_time_before_ns', 'local_time_after_ns'}
    for board in BOARDS:
        times = []
        for index, phase in enumerate(PHASES):
            name = f'probe-{phase}-{board}.json'
            path = out/name
            row = read_json(path)
            if not isinstance(row, dict) or set(row) != expected_keys:
                raise ValueError('Malformed fence: '+name)
            if (type(row['schema']) is not int or row['schema'] != 1
                    or row['source'] != SOURCE or row['board'] != board or row['phase'] != phase
                    or type(row['phase_index']) is not int or row['phase_index'] != index):
                raise ValueError('Wrong fence identity: '+name)
            if type(row['paused_before']) is not bool or type(row['paused_after']) is not bool:
                raise ValueError('Malformed pause state: '+name)
            if row['paused_before'] is not True or row['paused_after'] is not True:
                instability.append('Machine not paused at fence: '+name)
            before, after = row['local_time_before_ns'], row['local_time_after_ns']
            if (type(before) is not int or type(after) is not int
                    or not 0 <= before <= 2**64-1 or not 0 <= after <= 2**64-1):
                raise ValueError('Malformed local time: '+name)
            if before != after:
                instability.append('Machine time changed within fence: '+name)
            times.append(before)
            fences[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if len(set(times)) != 1:
            instability.append('Machine local time changed across captures: '+board)
        local_times[board] = times[0]
    data = []
    for name in ('motor-probe-a.bin', 'motor-probe-b.bin', 'motor-sram.bin'):
        value = (out/name).read_bytes()
        if len(value) != DUMP_SIZE:
            raise ValueError('Truncated or oversized motor SRAM: '+name)
        data.append(value)
        dumps[name] = hashlib.sha256(value).hexdigest()
    if not data[0] == data[1] == data[2]:
        instability.append('Motor SRAM differs between paused A/B/existing captures')
    anchor = (out/'motor-probe-anchor.bin').read_bytes()
    if len(anchor) != DUMP_SIZE:
        raise ValueError('Truncated or oversized motor SRAM: motor-probe-anchor.bin')
    dumps['motor-probe-anchor.bin'] = hashlib.sha256(anchor).hexdigest()
    anchor_preserved = anchor == data[0]
    main_endpoint_preserved = local_times['main'] == 20000000
    observations_passed = not instability and main_endpoint_preserved and anchor_preserved
    return {'schema': 1, 'observations_passed': observations_passed,
            'diagnostic_evidence_complete': True, 'within_pause_stable': not instability,
            'original_main_ack_preserved': main_endpoint_preserved,
            'motor_sram_preserved_across_helper_installation': anchor_preserved,
            'pre_install_per_board_time_and_full_registers': 'unavailable',
            'equal_board_endpoints': len(set(local_times.values())) == 1,
            'instability': instability,
            'status': ('observations_passed_pending_both_guards' if observations_passed
                       else 'complete_observations_failed_stability_endpoint_or_anchor'),
            'equivalence_established': False, 'full_native_one_second_proven': False,
            'local_times_ns': local_times,
            'all_local_times_equal_20ms_ack': all(t == 20000000 for t in local_times.values()),
            'board_matches_20ms_ack': {board: value == 20000000 for board, value in local_times.items()},
            'fences_sha256': fences, 'motor_dumps_sha256': dumps,
            'unavailable_fields': UNAVAILABLE}


def validate_ack(out, record):
    history = read_json(out/'acknowledgments.json')
    ack = history['final_ack']
    if (history['actual_times_ns'] != [20000000]
            or type(ack.get('schema')) is not int or ack.get('schema') != 1
            or ack.get('source') != 'renode-shared-mcu-step'
            or ack.get('enabled') is not True or ack.get('paused') is not True
            or ack.get('time_went_backwards') is not False
            or not isinstance(ack.get('epoch'), str) or not ack['epoch']
            or type(ack.get('virtual_time_ns')) is not int or ack['virtual_time_ns'] != 20000000
            or type(ack.get('step_id')) is not int or ack['step_id'] != 0
            or record.get('acknowledged_time_ns') != 20000000
            or read_json(out/'renode-step.json') != ack):
        raise ValueError('Invalid original 20 ms acknowledgment')


def verify_guarded(out, guard_path):
    out = out.resolve()
    record = read_json(out/'result.json')
    guard = read_json(guard_path)
    if not (record.get('passed') is True and record.get('clean_exit') is True
            and type(record.get('exit_code')) is int and record['exit_code'] == 0
            and record.get('process_group_absent') is True and record.get('watchdog_stopped') is True
            and record.get('forced_signals') == [] and record.get('forced_termination') is False
            and record.get('vendor_firmware_ran') is True and record.get('kind') == 'native-prefix'
            and record.get('mode') == 'legacy' and record.get('compared_duration_ns') == 20000000
            and record.get('global_quantum_ns') == 1000 and record.get('paused_motor_probe_enabled') is True
            and record.get('equivalence_established') is False
            and record.get('full_native_one_second_proven') is False):
        raise ValueError('Invalid or unclean inner diagnostic result')
    if not (type(guard.get('schema')) is int and guard.get('schema') == 1
            and 'failure' in guard and guard.get('passed') is True
            and guard.get('status') == 'finished' and guard.get('failure') is None
            and type(guard.get('comparator_exit_code')) is int and guard['comparator_exit_code'] == 0
            and guard.get('whole_groups_absent') is True and guard.get('all_descendants_absent') is True
            and guard.get('signals') == [] and guard.get('surviving_processes') == []
            and guard.get('surviving_group_members') == []
            and type(guard.get('wall_budget_s')) in (int, float) and 3 <= guard['wall_budget_s'] <= 45):
        raise ValueError('Invalid, unclean, or over-budget outer guard result')
    # Bind guard evidence to this exact output and diagnostic invocation.
    command = guard.get('command')
    if isinstance(command, list) and command[1:2] == ['-B']:
        command = command[:1]+command[2:]
    if (not isinstance(command, list) or len(command) != 11
            or not all(isinstance(x, str) for x in command)
            or Path(command[1]).resolve() != HERE/'compare.py'
            or command[2:7] != ['--kind', 'native-prefix', '--mode', 'legacy', '--wall-seconds']
            or command[8:10] != ['--paused-motor-probe', '--output']
            or Path(command[10]).resolve() != out):
        raise ValueError('Outer guard command is not the exact documented diagnostic invocation')
    if not 5 <= float(command[7]) <= min(42, guard['wall_budget_s']-3):
        raise ValueError('Comparator budget does not preserve outer cleanup reserve')
    validate_ack(out, record)
    if set(record.get('captures_sha256', {})) != EXPECTED_CAPTURES:
        raise ValueError('Original 13-capture inventory changed')
    for name, digest in record['captures_sha256'].items():
        value = (out/name).read_bytes()
        if name.endswith('-sram.bin') and len(value) != DUMP_SIZE:
            raise ValueError('Truncated original SRAM capture: '+name)
        if hashlib.sha256(value).hexdigest() != digest:
            raise ValueError('Original capture changed: '+name)
    result = validate_probe(out)
    if not result['observations_passed']:
        raise ValueError('Paused observations fail stability, main acknowledgment endpoint, or pre-install anchor')
    if record.get('paused_motor_probe') != result:
        raise ValueError('Probe observations changed after inner validation')
    result.update(status='guarded_paused_motor_diagnostic_passed_only',
                  diagnostic_passed=True, both_guards_verified=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--outer-record', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_guarded(args.output, args.outer_record)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result = {'diagnostic_passed': False, 'equivalence_established': False,
                  'status': 'failed_or_inconclusive', 'error': repr(exc)}
    print(json.dumps(result, indent=2))
    return 0 if result.get('diagnostic_passed') else 1


if __name__ == '__main__':
    sys.exit(main())
