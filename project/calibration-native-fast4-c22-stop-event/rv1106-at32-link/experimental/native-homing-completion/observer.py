#!/usr/bin/env python3
"""Bounded native homing and automatic release observation. No extra motion.

This entry point is inert on import. Parent owns source/profile closure,
resource supervision and descendant cleanup. Samples bound observation, not
physical hardware safety or an instantaneous shutdown guarantee.
"""
if not __debug__:
    raise SystemExit('Optimized Python is prohibited')
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import types

def source_module(name):
    path = Path(__file__).with_name(name + '.py')
    if path.is_symlink():
        raise ValueError('Symlink observer dependency')
    mod = types.ModuleType('homing_' + name)
    mod.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), mod.__dict__)
    return mod

cp = source_module('protocol')
physical = source_module('physical')
ROOT = Path(__file__).resolve().parents[3]
ACTIVE_SECONDS = 4768
WORK_SECONDS = 4760
SHARED_STOP_NS = 45_000_000_000
CLEANUP_SECONDS = 8
REPORT_NAME = 'homing-completion.json'
READY_NAME = 'ready-prerequisite.json'


def fixed_environment(root, cache):
    return {'PATH': '/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin:/usr/bin:/bin',
            'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPYCACHEPREFIX': cache,
            'RUN_SECONDS': str(ACTIVE_SECONDS), 'GLOBAL_QUANTUM_US': '1', 'NOZZLE_TMC_MODEL': 'autobaud',
            'HEADLESS_READY_ONLY': '1', 'THERMAL_PROFILE': 'none', 'Z_PROBE_PROFILE': 'synthetic-functional',
            'NATIVE_NOZZLE_HEATER': '0', 'CLOCK_CLIENT': 'scalar', 'ICOUNT_SHIFT': '0',
            'RENODE_BOOTSTRAP': 'legacy', 'PASSIVE_MOTOR_TRACE': '0', 'PASSIVE_PHYSICAL_TRACE': '1',
            'PASSIVE_CONTACT_TRACE': '1', 'RECOVERED_NOZZLE_NTC': '1', 'ASSUMED_XY_DIAG_CABLE': '1',
            'MOTOR_ENABLE_WIRING': 'mcu-control-only', 'PASSIVE_NOZZLE_TRACE': '1',
            'PASSIVE_HOMING_GPIO': '1', 'PASSIVE_TMC_TRACE': '1',
            'Z_BED_RELATIVE_MM': '-10', 'Z_OPPOSITE_STOP_RELATIVE_MM': '252', 'Z_BED_SIDE': 'minimum',
            'Z_STIFFNESS_N_PER_MM': '20', 'Z_DAMPING_NS_PER_MM': '0.05', 'Z_COUNTS_PER_N': '10000',
            'Z_HISTORY_CAPACITY': '4096',
            'QEMU_BINARY': str(root / 'rv1106-at32-link/experimental/clock-snapshot/runtime/run-baseline')}


def deadlines(elapsed, now, ready, stage_start=None, release=False):
    if not math.isfinite(elapsed) or elapsed < 0 or elapsed >= WORK_SECONDS or now is not None and now >= SHARED_STOP_NS:
        raise TimeoutError('Absolute observer budget reached')
    if not ready and (elapsed >= 1500 or now is not None and now >= 18_000_000_000):
        raise TimeoutError('Readiness budget reached')
    if stage_start is not None:
        host, shared = stage_start
        if elapsed - host >= (600 if release else 1500) or now - shared >= (5_000_000_000 if release else 18_000_000_000):
            raise TimeoutError('Fixed stage budget reached')


class Rail:
    def __init__(self, axis, text, source_ns, base):
        self.axis = axis
        self.base = base
        entries = base.native_entries(text)
        self.floor = max((e[1] for e in entries), default='')
        self.seen = {e[0] for e in entries}
        self.queued_ns = source_ns
        self.begin = self.end = None

    def observe(self, text, now):
        for line, stamp, severity, source, message in self.base.native_entries(text):
            if line in self.seen:
                continue
            self.seen.add(line)
            if stamp <= self.floor:
                continue
            match = re.fullmatch(r'Home Rail (Begin|Complete) - stepper: ([xyz])', message)
            if not match:
                continue
            if match[2] != self.axis:
                raise ValueError('Unexpected rail axis/fallback')
            event = {'line': line, 'stamp': stamp, 'observed_shared_ns': now}
            if match[1] == 'Begin':
                if self.begin is not None or self.end is not None:
                    raise ValueError('Repeated rail begin')
                self.begin = event
            else:
                if self.begin is None or self.end is not None or stamp <= self.begin['stamp']:
                    raise ValueError('Unpaired/repeated rail completion')
                self.end = event
        return self.end is not None

    def summary(self):
        return {'axis': self.axis, 'queued_shared_ns': self.queued_ns, 'native_begin': self.begin, 'native_completion': self.end}


def validate_final_report(report):
    if report.get('schema_version') != 1 or report.get('phase') != 'verified_homing_completion' or report.get('success') is not True:
        raise ValueError('Homing completion not verified')
    if report.get('launcher_exit_code') != 0 or report.get('cleanup_timeout') or report.get('error') or report.get('pending_batch') is not None:
        raise ValueError('Incomplete/error lifecycle')
    for key in ('final_export_requested', 'final_exports_verified', 'final_log_verified', 'final_revalidation_verified', 'no_extra_probe_pulse'):
        if report.get(key) is not True:
            raise ValueError('Missing final gate: ' + key)
    for key in ('calibration_completed', 'shutdown_qualification', 'old_provenance_restored', 'host_coordinates_equated_to_physical'):
        if report.get(key) is not False:
            raise ValueError('Unsupported claim: ' + key)
    requests = report.get('requests')
    if type(requests) is not list or [r.get('stage') for r in requests] != list(cp.STAGES):
        raise ValueError('Not exactly the fixed eight RPCs')
    if (report.get('homing_completed') is not True or report.get('natural_release_observed') is not True or
            report.get('physical_completion_proven') is not False or 'release_gcode' in report):
        raise ValueError('Unsupported homing/automatic-release claim')
    boundary, _ = cp.load(ROOT)
    if type(report.get('request_count')) is not int or report['request_count'] != 8 or len(report.get('generation_attempts', [])) != 8:
        raise ValueError('Unexpected attempts')
    if [entry.get('stage') for entry in report['generation_attempts']] != list(cp.STAGES):
        raise ValueError('Generation ordering/attempt mismatch')
    batches = report.get('batches', [])
    if [entry.get('stage') for entry in batches if entry.get('kind') == 'rpc'] != list(cp.STAGES) or len([entry for entry in batches if entry.get('kind') == 'shell']) != 8:
        raise ValueError('Serialized batch lifecycle mismatch')
    if any(entry.get('queue_outcome') != 'appended' for entry in batches):
        raise ValueError('Uncertain batch')
    tokens = set()
    for item in requests:
        if item.get('queue_outcome') != 'appended' or item.get('complete') is not True or item.get('shell_verified') is not True:
            raise ValueError('Unverified/uncertain RPC stage')
        if item.get('token') in tokens or not re.fullmatch('[a-f0-9]{20}', item.get('token', '')):
            raise ValueError('Ambiguous stage token')
        tokens.add(item['token'])
        if boundary.packet(item['stage']) is None or hashlib.sha256(boundary.packet(item['stage'])).hexdigest() != item.get('packet_sha256'):
            raise ValueError('Packet identity mismatch')
        parsed = boundary.verify_wire(item['stage'], bytes.fromhex(item['result']['wire_hex']))
        if any(item['result'].get(key) != value for key, value in parsed.items()):
            raise ValueError('Final wire/result mismatch')
        if not 0 <= item['queued_shared_ns'] <= item['completed_shared_ns'] < SHARED_STOP_NS or not 0 <= item['queued_host_s'] <= item['completed_host_s'] < WORK_SECONDS:
            raise ValueError('Stage time bound')
    rails = report.get('rails', [])
    if [r.get('axis') for r in rails] != list('xyz'):
        raise ValueError('Missing ordered XYZ rails')
    for rail in rails:
        begin, end = rail.get('native_begin'), rail.get('native_completion')
        if not begin or not end or begin['stamp'] >= end['stamp'] or not rail['queued_shared_ns'] <= begin['observed_shared_ns'] <= end['observed_shared_ns']:
            raise ValueError('Invalid fresh rail evidence')
    probes = {}
    for filename, label, pin in [('nozzle-z-probe-edges.csv', 'nozzle_PA7_Z', 7), ('main-z-probe-edges.csv', 'main_PB2_Z', 2)]:
        saved = report.get('probes', {}).get(filename, {})
        model = physical.Probe(label, pin)
        import csv, io
        output = io.StringIO()
        output.write('# PASSIVE GPIO EDGE TRACE v1; source-local virtual timestamps; no SyncTime or signal writes\n')
        writer = csv.DictWriter(output, fieldnames=physical.Probe.HEADER, lineterminator='\n')
        writer.writeheader(); writer.writerows(saved.get('rows', []))
        model.consume(output.getvalue().encode('ascii'), final=True)
        if not model.rows or saved.get('armed_count') != len(model.rows) or model.rows[-1]['level'] != '0':
            raise ValueError('Final probe freeze incomplete')
        probes[filename] = model
    if physical.paired_z_pulses(probes, report.get('z_probe_floors', {})) != report.get('z_probe_pulses'):
        raise ValueError('Final Z pulse evidence mismatch')
    window = report.get('initial_trace_window', [])
    if len(window) < 2 or window[0]['sequence'] < 1 or window[-1]['observation_time_s'] - window[0]['observation_time_s'] < .25:
        raise ValueError('No sustained pre-motion cadence after startup')
    previous = None
    for row in window:
        checked = physical.Physical.parse({key: str(row[key]) for key in physical.HEADER})
        if previous is not None and (checked['sequence'] != previous['sequence'] + 1 or not 0 < checked['observation_time_s'] - previous['observation_time_s'] <= physical.MAX_GAP):
            raise ValueError('Initial motion window discontinuity')
        previous = checked
    summary = report.get('physical', {})
    anchor = summary.get('anchor')
    if not anchor or summary.get('host_coordinates_equated_to_physical') is not False:
        raise ValueError('Missing completion source anchor')
    home_z, status_z = requests[6], requests[7]
    if (anchor['home_z_queue_source_s'] != home_z.get('physical_queue_source_s') or
            anchor['status_z_completed_shared_ns'] != status_z['completed_shared_ns'] or
            anchor['status_z_completed_source_s'] != status_z.get('physical_completion_source_s') or
            anchor['native_complete_observed_shared_ns'] != rails[2]['native_completion']['observed_shared_ns'] or
            anchor['probe_last_edge_source_s'] != max(float(m.rows[-1]['virtual_time_s']) for m in probes.values())):
        raise ValueError('Completion anchor differs from fresh native/RPC/probe evidence')
    for filename, model in probes.items():
        if any(float(row['virtual_time_s']) <= anchor['home_z_queue_source_s'] for row in model.rows[report['z_probe_floors'][filename]:]):
            raise ValueError('Stale pre-request Z probe pulse')
    proof = physical.Physical()
    previous = None
    for row in summary.get('release_rows', []):
        checked = physical.Physical.parse({key: str(row[key]) for key in physical.HEADER})
        if previous is not None and (checked['sequence'] != previous['sequence'] + 1 or not 0 < checked['observation_time_s'] - previous['observation_time_s'] <= physical.MAX_GAP):
            raise ValueError('Final physical continuity')
        proof.rows.append(checked)
        previous = checked
    proof.arm_completion(anchor)
    if not proof.complete() or proof.summary() != summary:
        raise ValueError('Physical automatic-release acceptance absent/inconsistent')
    health = report.get('trace_health', {})
    for board, filename in [('nozzle', 'nozzle-z-probe-edges.csv'), ('main', 'main-z-probe-edges.csv')]:
        count = len(probes[filename].rows)
        if health.get(board) != {'rows': count, 'edges': count - 1, 'drops': 0, 'stopped': True}:
            raise ValueError('Incomplete final probe health')
    contact = report.get('contact_release', {})
    if (type(health.get('contact_rows')) is not int or health['contact_rows'] < 3 or
            contact.get('contact_rows') != health['contact_rows'] or contact.get('no_recontact_after_clearance') is not True or
            not anchor['probe_last_edge_source_s'] <= contact.get('final_z_contact_off_source_s', -1) <= summary['first_clear_source_s'] or
            not anchor['home_z_queue_source_s'] < contact.get('last_z_contact_on_source_s', -1) < contact['final_z_contact_off_source_s']):
        raise ValueError('Incomplete fresh contact release evidence')
    if (type(report.get('launcher_exit_code')) is not int or report['launcher_exit_code'] != 0 or
            report.get('settling_start') != report.get('native_z_completion_budget_start') or not report.get('settling_start')):
        raise ValueError('Missing normal cleanup/settling budget')
    host_start, shared_start = report['settling_start']
    if (shared_start != anchor['native_complete_observed_shared_ns'] or
            not 0 <= host_start <= status_z['completed_host_s'] or
            not 0 <= report['host_elapsed_seconds'] - host_start < 600 or
            not 0 <= report['last_shared_mcu_ns'] - shared_start < 5_000_000_000):
        raise ValueError('Post-Z settling exceeded fixed budget')
    return True



class Runtime:
    """Inject only in offline tests; production main fixes all paths and budgets."""
    monotonic = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)
    launch = staticmethod(subprocess.Popen)


def run(root, run_name, cache, runtime=None):
    runtime = runtime or Runtime()
    boundary, base = cp.load(root)
    base.verify_classification_baseline()
    directory = root / 'runs' / run_name
    if directory.exists() or directory.is_symlink():
        raise ValueError('Fresh run required')
    start = runtime.monotonic()
    now = None
    owner = process = pending = rail = None
    stage_index = 0
    stage_start = None
    shell_ok = False
    next_log_ns = 0
    log_count = 0
    previous_console = b''
    trace = physical.Physical()
    nozzle = base.PassiveNozzle()
    review = base.NativeReview()
    clock = base.Clock()
    settling_start = None
    status_queue_source_us = None
    probes = {'nozzle-z-probe-edges.csv': physical.Probe('nozzle_PA7_Z', 7), 'main-z-probe-edges.csv': physical.Probe('main_PB2_Z', 2)}
    record = {'schema_version': 1, 'phase': 'waiting_ready', 'success': False, 'requests': [], 'request_count': 0,
              'generation_attempts': [], 'batches': [], 'rails': [], 'pending_batch': None,
              'final_export_requested': False, 'calibration_completed': False, 'shutdown_qualification': False,
              'old_provenance_restored': False, 'host_coordinates_equated_to_physical': False, 'physical_completion_proven': False, 'homing_completed': False, 'natural_release_observed': False,
              'bounds': {'active_host_s': ACTIVE_SECONDS, 'work_host_s': WORK_SECONDS, 'shared_ns': SHARED_STOP_NS, 'post_z_host_s': 600, 'post_z_shared_ns': 5_000_000_000},
              'native_error_review_scope': base.NATIVE_REVIEW_SCOPE,
              'sensor_acquisition_age_known': False, 'passive_bed_available': False}

    def elapsed():
        return runtime.monotonic() - start

    def check():
        nonlocal now
        if (directory / 'virtual-time.json').exists():
            now = clock.observe(base.safe_json(directory / 'virtual-time.json'))
        deadlines(elapsed(), now, record.get('ready_result') is not None, settling_start or stage_start, settling_start is not None)
        if directory.exists() and (directory / 'stop-request').exists():
            raise ValueError('External stop requested')

    def save():
        record.update(pending_batch=pending, host_elapsed_seconds=elapsed(), last_shared_mcu_ns=now,
                      physical=trace.summary(), probes={key: model.summary() for key, model in probes.items()}, passive_nozzle=nozzle.summary(), native_auxiliary_occurrences=review.occurrences)
        if directory.is_dir():
            # Revalidate the exact final snapshot after save refreshes elapsed
            # time; never persist success from an earlier pre-save timestamp.
            if record.get('success') is True:
                validate_final_report(record)
            base.atomic_json(directory / REPORT_NAME, record)

    def stop(reason):
        if directory.is_dir():
            if not (directory / 'stop-request').exists():
                base.create_bytes(directory / 'stop-request', reason.encode() + b'\n')
            record['final_export_requested'] = True

    def append(batch, commands):
        nonlocal pending
        if pending is not None:
            raise ValueError('One pending batch including logs')
        check()
        pending = dict(batch, offset=len(previous_console.decode('utf-8', errors='replace')), queue_outcome='uncertain', queued_host_s=elapsed(), queued_shared_ns=now)
        base.create_bytes(directory / (batch['label'] + '.commands'), commands.encode('ascii'))
        save()  # Durable attempted append before any write, never retried.
        check()
        owner.append_once(batch['label'], commands)
        pending['queue_outcome'] = 'appended'
        save()

    def complete_batch():
        nonlocal pending
        owner.complete(pending['label'])
        record['batches'].append(dict(pending, completed_host_s=elapsed(), completed_shared_ns=now))
        pending = None

    try:
        process = runtime.launch([str(root / 'rv1106-at32-link/experimental/native-homing-completion/run_homing_fixture.sh'), run_name], env=fixed_environment(root, cache))
        while process.poll() is None:
            check()
            if not (directory / 'console.bin').exists():
                runtime.sleep(.1)
                continue
            raw = base.safe_bytes(directory / 'console.bin', base.MAX_CONSOLE)
            if not raw.startswith(previous_console):
                raise ValueError('Console truncated/rewritten')
            previous_console = raw
            text = raw.decode('utf-8', errors='replace')
            if (directory / 'virtual-time.json').exists():
                now = clock.observe(base.safe_json(directory / 'virtual-time.json'))
            check()
            ready = review.observe(text)
            review_rail_sequence(text, base)
            if rail is not None:
                rail.observe(text, now)
                if rail.axis == 'z' and rail.end is not None and settling_start is None:
                    settling_start = (elapsed(), now)
                    record['settling_start'] = list(settling_start)
                    record['native_z_completion_budget_start'] = list(settling_start)
            for filename, model, cap in [('physical-state.csv', trace, 16 * 1024 * 1024), ('nozzle-thermal-live.csv', nozzle, 16 * 1024 * 1024)]:
                if now is not None and (directory / filename).exists():
                    data = base.safe_bytes(directory / filename, cap)
                    if model is trace:
                        # These exports are not an atomic cross-file snapshot.
                        # Refresh the shared clock after acquiring physical bytes;
                        # retain c2 producer-local age/lead and growth freshness.
                        now = clock.observe(base.safe_json(directory / 'virtual-time.json'))
                        model.consume(data, now, require_fresh=stage_index > 0)
                    else:
                        model.consume(data, now)
            for filename, model in probes.items():
                if stage_index > 0 and not (directory / filename).exists():
                    raise ValueError('Required live probe trace lost')
                if (directory / filename).exists():
                    model.consume(base.safe_bytes(directory / filename, 8 * 1024 * 1024))
            if settling_start is not None and 'z_probe_pulses' not in record:
                record['z_probe_pulses'] = physical.paired_z_pulses(probes, record['z_probe_floors'])
                home_floor = record['requests'][6]['physical_queue_source_s']
                for filename, model in probes.items():
                    if any(not home_floor < float(row['virtual_time_s'])
                           for row in model.rows[record['z_probe_floors'][filename]:]):
                        raise ValueError('Stale/future fresh Z probe evidence')
                    model.arm()
            if stage_index > 0:
                trace.fresh(now)
                if not nozzle.rows or now - nozzle.last_growth_shared_ns > 250_000_000:
                    raise ValueError('Required passive nozzle trace missing/stale')
            startup = re.findall(r'(?m)^COUPLED_STARTUP_COMMANDS_DONE\r?$', text)
            if len(startup) > 1:
                raise ValueError('Repeated startup marker')
            if owner is None and startup and now is not None:
                owner = base.ConsoleOwner(directory / 'console-input.commands')
            if owner is not None:
                owner.check()
            if pending:
                tail = text[pending['offset']:]
                if pending['kind'] == 'shell':
                    result = boundary.p.verify_shell_check(tail, pending['token'])
                    if result is not None:
                        base.create_bytes(directory / (pending['label'] + '.capture.txt'), tail.encode())
                        complete_batch()
                        shell_ok = True
                elif pending['kind'] == 'log':
                    if boundary.p.bounded_region(tail, pending['begin'], pending['end']) is not None:
                        final = pending.get('final') is True
                        complete_batch()
                        if final:
                            record['final_log_verified'] = True
                            record['phase'] = 'homing_completion_captured'
                            stop('Fixed native homing and automatic release observed; normal final export.')
                            break
                else:
                    item = record['requests'][-1]
                    result = boundary.capture(item['stage'], item['token'], tail)
                    if result is not None:
                        check()
                        base.create_bytes(directory / (item['stage'] + '.capture.txt'), tail.encode())
                        base.create_bytes(directory / (item['stage'] + '.response.http2.bin'), bytes.fromhex(result['wire_hex']))
                        item.update(result=result, complete=True, completed_host_s=elapsed(), completed_shared_ns=now)
                        complete_batch()
                        if item['stage'] == 'ready':
                            record['ready_result'] = result
                        if item['stage'] == 'status_z':
                            item['physical_completion_source_s'] = trace.rows[-1]['observation_time_s']
                            status_queue_source_us = item['status_queue_source_us']
                            record['z_probe_pulses'] = physical.paired_z_pulses(probes, record['z_probe_floors'])
                            anchor = {'home_z_queue_source_s': record['requests'][6]['physical_queue_source_s'],
                                      'probe_last_edge_source_s': max(float(m.rows[-1]['virtual_time_s']) for m in probes.values()),
                                      'native_complete_observed_shared_ns': record['rails'][2]['native_completion']['observed_shared_ns'],
                                      'status_z_completed_shared_ns': now,
                                      'status_z_completed_source_s': item['physical_completion_source_s']}
                            for filename, model in probes.items():
                                if any(float(row['virtual_time_s']) <= anchor['home_z_queue_source_s'] for row in model.rows[record['z_probe_floors'][filename]:]):
                                    raise ValueError('Stale pre-request Z probe evidence')
                                if model.armed_count != len(model.rows):
                                    raise ValueError('Probe freeze missing at native Z completion')
                            trace.arm_completion(anchor)
                        if rail is None and settling_start is None:
                            stage_start = None
                        stage_index += 1
                        shell_ok = False
            if pending is None and owner is not None:
                # Continue collecting rail evidence and physical settling before
                # advancing; requests alone never count as physical completion.
                waiting_rail = rail is not None and rail.end is None
                if rail is not None and rail.end is not None:
                    record['rails'].append(rail.summary())
                    rail = None
                    stage_start = None
                waiting_release = stage_index == 8 and not trace.complete()
                waiting_initial_trace = stage_index == 2 and not trace.motion_ready()
                if stage_index == 8 or not ready or waiting_rail or waiting_release or waiting_initial_trace:
                    if now >= next_log_ns:
                        log_count += 1
                        if log_count > cp.LOG_BATCH_LIMIT:
                            raise ValueError('Log poll budget exhausted')
                        token = secrets.token_hex(10)
                        label = 'L' + str(log_count)
                        prefix = 'AMB_' + token + '_' + label
                        append({'kind': 'log', 'label': prefix, 'token': token, 'begin': prefix + '_B', 'end': prefix + '_E', 'final': stage_index == 8 and trace.complete()}, boundary.log_command_batch(token, label))
                        next_log_ns = now + 250_000_000
                elif not shell_ok:
                    token = secrets.token_hex(10)
                    append({'kind': 'shell', 'label': 'shell_' + str(stage_index), 'token': token}, boundary.p.shell_check_command_batch(token))
                else:
                    stage = cp.STAGES[stage_index]
                    trace.fresh(now)
                    if not nozzle.rows:
                        raise ValueError('No cold passive baseline')
                    token = secrets.token_hex(10)
                    record['generation_attempts'].append({'stage': stage, 'host_s': elapsed(), 'shared_ns': now})
                    save()
                    packet, client = boundary.build(stage)
                    commands = boundary.commands(stage, token, client)
                    check()
                    for suffix, data in [('request.bin', packet), ('client.elf', client)]:
                        base.create_bytes(directory / (stage + '.' + suffix), data)
                    if settling_start is None:
                        stage_start = (elapsed(), now)
                    if stage == 'home_x':
                        record['profile'] = boundary.validate_profile(directory)
                        record['initial_trace_window'] = trace.latest_window()
                    if stage == 'home_z':
                        if any(not model.rows or model.rows[-1]['level'] != '0' for model in probes.values()):
                            raise ValueError('Missing/active probe before fresh Z request')
                        record['z_probe_floors'] = {key: len(model.rows) for key, model in probes.items()}
                    if stage.startswith('home_'):
                        rail = Rail(stage[-1], text, now, base)
                        stage_start = (elapsed(), now)
                    item = {'physical_queue_source_s': trace.rows[-1]['observation_time_s'], 'status_queue_source_us': int(nozzle.rows[-1]['time_us']), 'stage': stage, 'token': token, 'shell_verified': True, 'queue_outcome': 'uncertain', 'complete': False, 'queued_host_s': elapsed(), 'queued_shared_ns': now, 'packet_sha256': hashlib.sha256(packet).hexdigest()}
                    record['requests'].append(item)
                    record['request_count'] += 1
                    append({'kind': 'rpc', 'label': stage, 'stage': stage, 'token': token}, commands)
                    item['queue_outcome'] = 'appended'
            save()
            runtime.sleep(.1)
        if record['phase'] != 'homing_completion_captured':
            raise ValueError('Fixture exited before complete release observation')
    except (Exception, KeyboardInterrupt) as error:
        record.update(phase='error', error=type(error).__name__ + ': ' + str(error))
        stop('Homing completion observer stopped; no retry or actuator fallback; final export.')
    finally:
        if process is not None:
            try:
                record['launcher_exit_code'] = process.wait(timeout=CLEANUP_SECONDS)
            except subprocess.TimeoutExpired:
                # Do not claim cleanup and never wait unbounded. The parent
                # owns TERM/KILL and subreaping after this failed result.
                record.update(cleanup_timeout=True, phase='error', success=False)
        if owner is not None:
            try:
                owner.check()
            except Exception as error:
                record.update(phase='error', error=str(error))
            owner.close()
        try:
            if record['phase'] == 'homing_completion_captured' and record.get('launcher_exit_code') == 0:
                final = base.safe_bytes(directory / 'console.bin', base.MAX_CONSOLE)
                if not final.startswith(previous_console):
                    raise ValueError('Final console lost')
                text = final.decode('utf-8', errors='replace')
                review.observe(text, final=True)
                if review_rail_sequence(text, base) != 6:
                    raise ValueError('Final rail sequence incomplete')
                now = clock.observe(base.safe_json(directory / 'virtual-time.json'))
                if now >= SHARED_STOP_NS or elapsed() >= ACTIVE_SECONDS:
                    raise TimeoutError('Final export beyond fixed caps')
                for item in record['requests']:
                    batch = next(b for b in record['batches'] if b['label'] == item['stage'])
                    if boundary.capture(item['stage'], item['token'], text[batch['offset']:]) != item['result']:
                        raise ValueError('Final RPC recapture mismatch')
                for batch in record['batches']:
                    if batch['kind'] == 'shell' and boundary.p.verify_shell_check(text[batch['offset']:], batch['token']) is None:
                        raise ValueError('Final shell check absent')
                    if batch['kind'] == 'log' and boundary.p.bounded_region(text[batch['offset']:], batch['begin'], batch['end']) is None:
                        raise ValueError('Final log capture absent')
                trace.consume(base.safe_bytes(directory / 'physical-state.csv', 16 * 1024 * 1024), now, final=True)
                physical.validate_status(base.safe_json(directory / 'physical-state-status.json'), len(trace.rows), final=True)
                base.final_passive(directory, nozzle, now, status_queue_source_us)
                # Probe/contact final validation is mandatory and implemented
                # by the physical trace module contract, never an optional gate.
                verify_probe_exports(directory, trace, probes, record, base)
                boundary.validate_profile(directory)
                record['model_exports'] = validate_model_exports(directory, base)
                record.update(final_exports_verified=True, final_revalidation_verified=True, phase='verified_homing_completion', success=True, homing_completed=True, natural_release_observed=True)
                record.update(pending_batch=pending, host_elapsed_seconds=elapsed(), last_shared_mcu_ns=now,
                              physical=trace.summary(), probes={key: model.summary() for key, model in probes.items()})
                validate_final_report(record)
            save()
            ready_record = {'scope': 'Genuine PrinterState prerequisite only; not full calibration', 'phase': 'verified_ready' if record.get('success') else 'invalid', 'request_count': 1 if record.get('success') else 0, 'total_run_request_count': record['request_count'], 'result': record.get('ready_result'), 'final_export_requested': record['final_export_requested'], 'launcher_exit_code': record.get('launcher_exit_code')}
            if directory.is_dir():
                base.atomic_json(directory / READY_NAME, ready_record)
        except Exception as error:
            record.update(phase='error', success=False, homing_completed=False, natural_release_observed=False, error=type(error).__name__ + ': ' + str(error))
            save()
            if directory.is_dir():
                base.atomic_json(directory / READY_NAME, {'phase': 'invalid', 'error': str(error)})
    return record


def validate_model_exports(directory, base):
    force = base.safe_json(directory / 'z-force-status.json')
    sensor = base.safe_json(directory / 'z-sensor-status.json')
    if force.get('faulted') is not False or force.get('last_error') or force.get('bound') is not True:
        raise ValueError('Force source faulted/unbound')
    if sensor.get('timed_provider_bound') is not True or any(sensor.get(k, 0) for k in ('provider_failures', 'adapter_errors', 'protocol_errors')) or sensor.get('last_error') or sensor.get('adapter_error'):
        raise ValueError('Sensor provider/protocol fault')
    for name in ('z-force-query.csv', 'z-sensor.csv', 'z-nozzle-gpio.csv'):
        if not base.safe_bytes(directory / name, 64 * 1024 * 1024):
            raise ValueError('Missing sensor evidence: ' + name)
    return {'force': force, 'sensor': sensor, 'full_bit_causality_proven': False, 'warning': 'Historical sensor/bit/query trace capacity limitations retained; complete per-bit causal chain is not claimed.'}


def review_rail_sequence(text, base):
    expected = [(kind, axis) for axis in 'xyz' for kind in ('Begin', 'Complete')]
    found = []
    seen = set()
    for line, stamp, severity, source, message in base.native_entries(text):
        match = re.fullmatch(r'Home Rail (Begin|Complete) - stepper: ([xyz])', message)
        if match and line not in seen:
            seen.add(line)
            found.append(match.groups())
    if found != expected[:len(found)] or len(found) > 6:
        raise ValueError('Unexpected native rail sequence')
    return len(found)


def verify_probe_exports(directory, trace, probes, record, base):
    for filename, model in probes.items():
        model.consume(base.safe_bytes(directory / filename, 8 * 1024 * 1024), final=True)
        if model.armed_count is None or not model.rows or model.rows[-1]['level'] != '0':
            raise ValueError('Probe final baseline missing')
    # Paused final envelopes permit exactly response-only OR the exact ordered
    # interactive getter/response schema. Mixed or trailing material is fatal.
    monitor = base.safe_bytes(directory / 'renode.log', 64 * 1024 * 1024).decode('utf-8', errors='strict')
    health = physical.final_health(monitor, probes)
    contact = base.safe_bytes(directory / 'contact-transitions.csv', 16 * 1024 * 1024)
    contact_release = physical.validate_contacts(contact, trace.anchor, health['contact_rows'], trace.first_clear_source_s)
    record.update(no_extra_probe_pulse=True, trace_health=health, contact_release=contact_release)




def validate_artifacts(directory, report=None):
    """Independent offline replay of the persisted boundary/lifecycle evidence.

    Does not launch/build clients or mutate evidence. Source/profile/resource
    supervisor acceptance remains separate and mandatory.
    """
    directory = Path(directory)
    boundary, base = cp.load(ROOT)
    report = base.safe_json(directory / REPORT_NAME) if report is None else report
    validate_final_report(report)
    boundary.validate_profile(directory)
    validate_model_exports(directory, base)
    console = base.safe_bytes(directory / 'console.bin', base.MAX_CONSOLE).decode('utf-8', errors='replace')
    review = base.NativeReview()
    review.observe(console, final=True)
    if review_rail_sequence(console, base) != 6:
        raise ValueError('Final native rail sequence incomplete')
    for item in report['requests']:
        stage = item['stage']
        if base.safe_bytes(directory / (stage + '.request.bin'), 65536) != boundary.packet(stage):
            raise ValueError('Persisted request mismatch')
        wire = base.safe_bytes(directory / (stage + '.response.http2.bin'), 1024 * 1024)
        if wire.hex() != item['result']['wire_hex']:
            raise ValueError('Persisted wire mismatch')
        batch = next(v for v in report['batches'] if v.get('stage') == stage and v['kind'] == 'rpc')
        if boundary.capture(stage, item['token'], console[batch['offset']:]) != item['result']:
            raise ValueError('Persisted console/RPC mismatch')
    for batch in report['batches']:
        if batch['kind'] == 'shell' and boundary.p.verify_shell_check(console[batch['offset']:], batch['token']) is None:
            raise ValueError('Persisted shell evidence missing')
        if batch['kind'] == 'log' and boundary.p.bounded_region(console[batch['offset']:], batch['begin'], batch['end']) is None:
            raise ValueError('Persisted log evidence missing')
    now = base.Clock().observe(base.safe_json(directory / 'virtual-time.json'))
    if now >= SHARED_STOP_NS:
        raise ValueError('Final source cap exceeded')
    trace = physical.Physical()
    raw = base.safe_bytes(directory / 'physical-state.csv', 16 * 1024 * 1024)
    if not raw.endswith(b'\n'):
        raise ValueError('Partial final physical trace')
    trace.consume(raw, now, final=True)
    physical.validate_status(base.safe_json(directory / 'physical-state-status.json'), len(trace.rows), final=True)
    if any(row not in trace.rows for row in report['initial_trace_window']):
        raise ValueError('Persisted initial motion cadence differs')
    summary = report['physical']
    trace.arm_completion(summary['anchor'])
    if trace.summary() != summary:
        raise ValueError('Persisted physical automatic release differs from report')
    probes = {}
    for filename, label, pin in [('nozzle-z-probe-edges.csv', 'nozzle_PA7_Z', 7), ('main-z-probe-edges.csv', 'main_PB2_Z', 2)]:
        model = physical.Probe(label, pin)
        model.consume(base.safe_bytes(directory / filename, 8 * 1024 * 1024), final=True)
        model.armed_count = report['probes'][filename]['armed_count']
        if model.summary() != report['probes'][filename]:
            raise ValueError('Persisted probe evidence differs')
        probes[filename] = model
    scratch = {}
    verify_probe_exports(directory, trace, probes, scratch, base)
    if scratch['trace_health'] != report['trace_health'] or scratch['contact_release'] != report['contact_release']:
        raise ValueError('Persisted final health differs')
    nozzle = base.PassiveNozzle()
    base.final_passive(directory, nozzle, now, report['requests'][-1]['status_queue_source_us'])
    return True

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-name', required=True)
    parser.add_argument('--seconds', type=int, default=ACTIVE_SECONDS)
    args = parser.parse_args(argv)
    if args.seconds != ACTIVE_SECONDS or not re.fullmatch('[a-zA-Z0-9_-]+', args.run_name):
        raise SystemExit('Fixed budget and valid fresh run name required')
    cache = sys.pycache_prefix
    if (not sys.flags.isolated or not sys.dont_write_bytecode or type(cache) is not str or not Path(cache).is_absolute() or Path(cache).exists() or Path(cache).is_symlink() or Path(cache).name != args.run_name + '-python-cache' or not Path(cache).parent.is_dir() or os.environ.get('PYTHONPYCACHEPREFIX') != cache):
        raise SystemExit('Fresh isolated disabled-bytecode supervisor cache required')
    record = run(ROOT, args.run_name, cache)
    return 0 if record.get('success') else 2

if __name__ == '__main__':
    raise SystemExit(main())
