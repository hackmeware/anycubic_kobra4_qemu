#!/usr/bin/env python3
"""Bound the unchanged Legacy observer and record host-only progress evidence.

Run this under legacy-ready/outer_guard.py with its fixed 900-second budget.
No monitor commands, virtual steps, snapshot operations or readiness synthesis
are added here. Progress checkpoints are evidence, not resumable VM snapshots.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import threading
import time

TOTAL_SECONDS = 880
GRACE_SECONDS = 8
TERM_SECONDS = 2
KILL_SECONDS = 2
ACTIVE_SECONDS = TOTAL_SECONDS - GRACE_SECONDS - TERM_SECONDS - KILL_SECONDS
OUTER_SECONDS = 900
VIRTUAL_THRESHOLD_NS = 15_000_000_000
PROGRESS_INTERVAL_SECONDS = 1.0
RSS_LIMIT_BYTES = 4 * 1024**3
AVAILABLE_FLOOR_BYTES = 2 * 1024**3
DISK_FLOOR_BYTES = 512 * 1024**2
TAIL_BYTES = 2048
JSON_LIMIT_BYTES = 1024 * 1024
HOST_PYTHON_DIR = '/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin'
LOG_NAMES = ('launcher.log', 'renode.log', 'qemu.log', 'console.bin')
Z_PARAMETERS = ('BED_RELATIVE_MM', 'OPPOSITE_STOP_RELATIVE_MM', 'BED_SIDE',
                'STIFFNESS_N_PER_MM', 'DAMPING_NS_PER_MM', 'BASELINE_COUNTS',
                'COUNTS_PER_N', 'SIGNAL_POLARITY', 'HISTORY_CAPACITY', 'QUERY_TRACE_ROWS')


def safe_json(path):
    """Never follow a link or block on a FIFO while reading optional evidence."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Evidence is not a regular file')
        data = stream.read(JSON_LIMIT_BYTES + 1)
    if len(data) > JSON_LIMIT_BYTES:
        raise ValueError('Evidence exceeds the JSON size limit')
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError('Evidence is not a JSON object')
    return value


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def fresh(path):
    return not path.exists() and not path.is_symlink()


def available_memory():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1]) * 1024
    raise RuntimeError('MemAvailable is unavailable')


def group_members(pgid):
    """Observe only; the outer subreaper owns orphan and detached-child tracking."""
    if type(pgid) is not int or pgid <= 0:
        return []
    rows = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            raw = (entry / 'stat').read_text()
            fields = raw[raw.rfind(')') + 2:].split()
            if int(fields[2]) == pgid:
                with (entry / 'cmdline').open('rb') as command:
                    arguments = command.read(4096).split(b'\0')
                rows.append({'pid': int(entry.name), 'ppid': int(fields[1]),
                             'pgid': int(fields[2]), 'session': int(fields[3]),
                             'state': fields[0], 'starttime_ticks': int(fields[19]),
                             'qemu_baseline_process': any(arg.endswith(b'/qemu-baseline') for arg in arguments[:4]),
                             'rss_bytes': int(fields[21]) * os.sysconf('SC_PAGE_SIZE')})
        except (OSError, ValueError, IndexError):
            # Processes may disappear between the directory scan and stat read.
            continue
    return sorted(rows, key=lambda row: row['pid'])


def log_tail(path, previous=None):
    result = {'status': 'missing', 'size_bytes': None, 'tail': ''}
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('Log is not a regular file')
            stream.seek(max(0, info.st_size - TAIL_BYTES))
            data = stream.read(TAIL_BYTES)
        identity = [info.st_dev, info.st_ino]
        result.update(status='observed', size_bytes=info.st_size,
                      identity=identity, mtime_ns=info.st_mtime_ns,
                      tail=data.decode('utf-8', errors='replace'),
                      tail_is_complete_file=info.st_size <= TAIL_BYTES,
                      truncated_since_previous=False, replaced_since_previous=False)
        if previous and previous.get('status') == 'observed':
            replaced = identity != previous.get('identity')
            result['replaced_since_previous'] = replaced
            result['truncated_since_previous'] = not replaced and info.st_size < previous['size_bytes']
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        result.update(status='unavailable', error=str(exc))
    return result


def virtual_progress(path, step_ack=False):
    """A missing bootstrap export means unknown time, never zero or host time."""
    try:
        sample = safe_json(path)
        now = sample.get('virtual_time_ns')
        if type(now) is not int or now < 0:
            raise ValueError('Invalid virtual_time_ns')
        if step_ack and (type(sample.get('step_id')) is not int or sample['step_id'] < 0
                         or type(sample.get('schema')) is not int or sample['schema'] != 1
                         or sample.get('source') != 'renode-shared-mcu-step'
                         or sample.get('enabled') is not True or sample.get('paused') is not True
                         or sample.get('time_went_backwards') is not False
                         or not isinstance(sample.get('epoch'), str) or not sample['epoch']):
            raise ValueError('Invalid paused Renode step acknowledgement')
        answer = {'status': 'observed', 'virtual_time_ns': now,
                  'threshold_reached': now >= VIRTUAL_THRESHOLD_NS}
        for key in ('epoch', 'sequence', 'step_id', 'time_went_backwards'):
            if key in sample and isinstance(sample[key], (str, int, bool, type(None))):
                answer[key] = sample[key]
        return answer
    except FileNotFoundError:
        return {'status': 'missing', 'virtual_time_ns': None}
    except (OSError, ValueError) as exc:
        return {'status': 'unavailable', 'virtual_time_ns': None, 'error': str(exc)}


def environment(profile):
    return {'GLOBAL_QUANTUM_US': '1', 'NOZZLE_TMC_MODEL': 'autobaud',
            'HEADLESS_READY_ONLY': '1', 'THERMAL_PROFILE': 'none', 'Z_PROBE_PROFILE': 'none',
            'NATIVE_NOZZLE_HEATER': '0', 'CLOCK_CLIENT': 'scalar', 'ICOUNT_SHIFT': '0',
            'RENODE_BOOTSTRAP': 'legacy', 'PYTHONDONTWRITEBYTECODE': '1',
            'QEMU_BINARY': str(profile / 'rv1106-at32-link/experimental/clock-snapshot/runtime/run-baseline')}


def plan(profile, evidence, name):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('Invalid run name')
    profile, evidence = profile.resolve(), evidence.resolve()
    run = profile / 'runs' / name
    paths = {key: evidence / (name + suffix) for key, suffix in (
        ('configuration', '-configuration.json'), ('progress', '-progress.jsonl'),
        ('latest', '-latest.json'), ('supervision', '-supervision.json'),
        ('audit', '-post-audit.json'))}
    command = ['python3', '-B', str(profile / 'rv1106-at32-link/scripts/run_native_ready_observation.py'),
               name, '--seconds', str(ACTIVE_SECONDS)]
    configuration = {
        'schema_version': 1, 'profile': str(profile), 'run_name': name, 'run_directory': str(run),
        'evidence_directory': str(evidence), 'command': command, 'environment': environment(profile),
        'host_environment': {'PATH': HOST_PYTHON_DIR + ':/usr/bin:/bin', 'HOME': str(profile / 'at32-runtime/home'),
                             'LANG': 'C.UTF-8'},
        'budgets_seconds': {'total': TOTAL_SECONDS, 'stop_at': ACTIVE_SECONDS,
                           'graceful': GRACE_SECONDS, 'term': TERM_SECONDS,
                           'kill': KILL_SECONDS, 'planned_outer': OUTER_SECONDS},
        'virtual_threshold_ns': VIRTUAL_THRESHOLD_NS, 'virtual_threshold_is_strict_stepping_cap': False,
        'progress_interval_seconds': PROGRESS_INTERVAL_SECONDS,
        'resource_stop_min_available_bytes': AVAILABLE_FLOOR_BYTES,
        'resource_stop_max_group_rss_bytes': RSS_LIMIT_BYTES,
        'preflight_min_free_disk_bytes': DISK_FLOOR_BYTES,
        'bootstrap_seconds': 1, 'bootstrap_unchanged': True,
        'checkpoint_kind': 'Host progress evidence only; not a resumable VM snapshot',
        'outer_guard_required': True, 'orphan_tracking_owner': 'outer_guard.py',
        'progress_writes_monitor_commands': False, 'progress_adds_virtual_steps': False,
        'firmware_changes': False, 'heating_commands': False, 'homing_commands': False,
        'print_commands': False, 'physical_completion_proven': False,
        'rss_note': 'Sampled summed process-group RSS may double-count shared mappings and miss peaks.',
        'artifacts': {key: str(path) for key, path in paths.items()},
    }
    return configuration, run, paths


def preflight(configuration, run, paths):
    profile = Path(configuration['profile'])
    evidence = Path(configuration['evidence_directory'])
    if not evidence.is_dir() or not (profile / 'runs').is_dir():
        raise ValueError('Existing evidence and profile/runs directories are required')
    if not os.access(Path(HOST_PYTHON_DIR) / 'python3', os.X_OK):
        raise ValueError('The expected Python 3.12 runtime is unavailable; no child launched')
    experiment = profile / 'rv1106-at32-link/experimental/legacy-ready'
    if evidence == experiment or experiment in evidence.parents:
        raise ValueError('Run evidence must be outside the source experiment directory')
    candidates = [run, *paths.values(), *(path.with_name(path.name + '.tmp')
                                         for key, path in paths.items() if key != 'progress')]
    if any(not fresh(path) for path in candidates):
        raise ValueError('Fresh run and evidence paths are required')
    if os.environ.get('PASSIVE_CONTACT_TRACE', '0') != '0':
        raise ValueError('Unexpected PASSIVE_CONTACT_TRACE override; no child launched')
    if any(key in os.environ for key in ('BASH_ENV', 'ENV', 'PYTHONPATH', 'PYTHONHOME',
                                         'LD_PRELOAD', 'LD_LIBRARY_PATH', 'LD_AUDIT')):
        raise ValueError('Unexpected shell, Python or loader override; use the documented clean launch')
    if any('Z_' + key in os.environ for key in Z_PARAMETERS):
        raise ValueError('Unexpected Z profile parameters; no child launched')
    required = ('rv1106-at32-link/scripts/run_native_ready_observation.py',
                'rv1106-at32-link/scripts/bounded_native_supervisor.py',
                'rv1106-at32-link/scripts/run_native_event_fixture.sh',
                'rv1106-at32-link/scripts/run_link.py',
                'rv1106-at32-link/experimental/bootstrap-boundaries/outer_guard.py',
                'rv1106-at32-link/experimental/legacy-ready/outer_guard.py',
                'rv1106-at32-link/experimental/clock-snapshot/runtime/run-baseline',
                'rv1106-at32-link/experimental/clock-snapshot/runtime/bin/qemu-baseline',
                'at32-runtime/renode_1.17.0-portable/renode',
                'rv1106-linux-display-128diag/linux-test.elf',
                'inputs/mcu.bin', 'inputs/motor.bin', 'inputs/nozzle.bin', 'inputs/offline-emmc.img')
    for relative in required:
        path = profile / relative
        if not path.is_file() or path.stat().st_size == 0 or not os.access(path, os.R_OK):
            raise ValueError('Missing or unreadable required input: ' + str(path))
    available = available_memory()
    disk = {str(directory): shutil.disk_usage(directory).free for directory in (evidence, run.parent)}
    if available < AVAILABLE_FLOOR_BYTES:
        raise ValueError('MemAvailable below 2 GiB; no child launched')
    if any(value < DISK_FLOOR_BYTES for value in disk.values()):
        raise ValueError('Free disk below 512 MiB; no child launched')
    configuration['preflight'] = {'available_memory_bytes': available, 'free_disk_bytes': disk}
    # Hash small controlling sources, not the 512 MiB disk, inside the outer budget.
    controls = required[:7]
    configuration['controlling_source_sha256'] = {
        relative: hashlib.sha256((profile / relative).read_bytes()).hexdigest() for relative in controls}
    configuration['runner_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def load_supervisor(profile):
    source = profile / 'rv1106-at32-link/scripts/bounded_native_supervisor.py'
    spec = importlib.util.spec_from_file_location('legacy_progress_supervisor', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Recorder:
    """One host sampler and one append-only evidence writer; bounded retained state."""
    def __init__(self, run, paths):
        self.run, self.paths = run, paths
        self.stream = paths['progress'].open('x')
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, name='legacy-host-progress', daemon=True)
        self.started = time.monotonic()
        self.count = 0
        self.last_sample_time = None
        self.maximum_interval = 0.0
        self.maximum_rss = 0
        self.minimum_available = None
        self.errors = []
        self.resource_guard_triggered = False
        self.pending_stop = False
        self.previous_logs = {}
        self.last_row = None
        self.milestones = {}
        self.maximum_observed_virtual_time_ns = None

    def request_stop(self):
        try:
            with (self.run / 'stop-request').open('x') as stream:
                stream.write('Host progress sampler requests stop; no continuation.\n')
            return 'created'
        except FileExistsError:
            return 'already_present'
        except FileNotFoundError:
            return 'pending_run_directory'

    def sample(self, final=False):
        now = time.monotonic()
        gap = None if self.last_sample_time is None else now - self.last_sample_time
        if gap is not None:
            self.maximum_interval = max(self.maximum_interval, gap)
        self.last_sample_time = now
        try:
            supervision = safe_json(self.paths['supervision'])
        except FileNotFoundError:
            supervision = {}
        pgid = supervision.get('process_group_id')
        rows = group_members(pgid)
        rss, available = sum(row['rss_bytes'] for row in rows), available_memory()
        self.maximum_rss = max(self.maximum_rss, rss)
        self.minimum_available = available if self.minimum_available is None else min(self.minimum_available, available)
        if rss > RSS_LIMIT_BYTES or available < AVAILABLE_FLOOR_BYTES:
            self.resource_guard_triggered = self.pending_stop = True
        logs = {name: log_tail(self.run / name, self.previous_logs.get(name)) for name in LOG_NAMES}
        self.previous_logs = logs
        virtual = virtual_progress(self.run / 'virtual-time.json')
        step = virtual_progress(self.run / 'renode-step.json', step_ack=True)
        virtual_ns = virtual.get('virtual_time_ns')
        if virtual_ns is not None:
            self.maximum_observed_virtual_time_ns = max(self.maximum_observed_virtual_time_ns or 0, virtual_ns)
        observations = {
            'virtual_time_export_observed': virtual['status'] == 'observed',
            'legacy_full_bootstrap_ack_observed': step['status'] == 'observed' and step['virtual_time_ns'] >= 1_000_000_000,
            'post_bootstrap_step_ack_observed': step['status'] == 'observed' and step['virtual_time_ns'] > 1_000_000_000 and step['step_id'] > 0,
            'qemu_baseline_process_observed': any(member['qemu_baseline_process'] for member in rows),
            'nonempty_console_observed': (logs['console.bin'].get('size_bytes') or 0) > 0,
        }
        for name, observed in observations.items():
            if observed and name not in self.milestones:
                self.milestones[name] = {'first_elapsed_seconds': now - self.started}
        stages = supervision.get('stages')
        row = {'schema_version': 1, 'sequence': self.count, 'final_sample': final,
               'elapsed_seconds': now - self.started, 'host_unix_time_ns': time.time_ns(),
               'interval_since_previous_seconds': gap, 'process_group_id': pgid,
               'members': rows, 'group_rss_bytes': rss, 'available_memory_bytes': available,
               'last_supervisor_stage': stages[-1] if isinstance(stages, list) and stages else None,
               'virtual_time': virtual, 'renode_step': step, 'milestones': dict(self.milestones),
               'logs': logs, 'resource_guard_triggered': self.resource_guard_triggered,
               'resumable_vm_snapshot': False, 'physical_completion_proven': False}
        if self.pending_stop:
            row['stop_request'] = self.request_stop()
        self.write(row)

    def write(self, row):
        self.stream.write(json.dumps(row, allow_nan=False) + '\n')
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.count += 1
        self.last_row = row
        # Keep the latest summary small; detailed tails and process rows stay in JSONL.
        latest = {key: value for key, value in row.items() if key not in ('logs', 'members')}
        latest.update(status='active', success=False, sample_count=self.count,
                      success_scope='Strict readiness and inner cleanup only; outer guard must be checked separately',
                      outer_guard_verification_pending=True,
                      progress_file=str(self.paths['progress']),
                      checkpoint_kind='Evidence only; not a resumable VM snapshot',
                      logs={key: {k: v for k, v in value.items() if k != 'tail'}
                            for key, value in row.get('logs', {}).items()},
                      process_count=len(row.get('members', [])), sampling_errors=list(self.errors))
        atomic_json(self.paths['latest'], latest)

    def attempt_sample(self, final=False):
        try:
            self.sample(final=final)
        except Exception as exc:
            message = type(exc).__name__ + ': ' + str(exc)
            if message not in self.errors:
                self.errors.append(message)
            self.pending_stop = True
            row = {'schema_version': 1, 'sequence': self.count, 'final_sample': final,
                   'elapsed_seconds': time.monotonic() - self.started,
                   'sampling_error': message, 'resumable_vm_snapshot': False}
            try:
                row['stop_request'] = self.request_stop()
            except OSError as stop_error:
                row['stop_request_error'] = str(stop_error)
            try:
                self.write(row)
            except Exception as write_error:
                message = 'Progress persistence failed: ' + str(write_error)
                if message not in self.errors:
                    self.errors.append(message)

    def loop(self):
        while not self.stop.is_set():
            begin = time.monotonic()
            self.attempt_sample()
            self.stop.wait(max(0, PROGRESS_INTERVAL_SECONDS - (time.monotonic() - begin)))
        self.attempt_sample(final=True)

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=2)
        finished = not self.thread.is_alive()
        if finished:
            self.stream.close()
        return finished


def audit_group(pgid):
    result = {'members': group_members(pgid), 'group_absent_confirmed': False,
              'group_probe_error': None, 'scope': 'Same PID namespace and process group only; outer guard audits all descendants'}
    if type(pgid) is int and pgid > 0:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            result['group_absent_confirmed'] = True
        except OSError as exc:
            result['group_probe_error'] = str(exc)
    return result


def execute(configuration, run, paths):
    preflight(configuration, run, paths)
    with paths['configuration'].open('x') as stream:
        json.dump(configuration, stream, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    supervisor = load_supervisor(Path(configuration['profile']))
    recorder = Recorder(run, paths)
    result = {'success': False, 'errors': ['Supervisor did not return a result']}
    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(configuration['host_environment'])
    os.environ.update(configuration['environment'])
    sampler_started = False
    try:
        recorder.thread.start()
        sampler_started = True
        result = supervisor.supervise(
            configuration['command'], stop_request=run / 'stop-request',
            native_report=run / 'ready-observation.json', evidence=paths['supervision'],
            total_seconds=TOTAL_SECONDS, grace_seconds=GRACE_SECONDS,
            term_seconds=TERM_SECONDS, kill_seconds=KILL_SECONDS,
            virtual_time_file=run / 'virtual-time.json', max_virtual_time_ns=VIRTUAL_THRESHOLD_NS)
    except (Exception, KeyboardInterrupt) as exc:
        result = {'success': False, 'errors': [type(exc).__name__ + ': ' + str(exc)]}
    finally:
        if sampler_started:
            finished = recorder.finish()
        else:
            recorder.stream.close()
            finished = False
        os.environ.clear()
        os.environ.update(previous)
    audit = audit_group(result.get('process_group_id'))
    audit.update(sample_count=recorder.count, sampling_finished=finished,
                 maximum_sampled_group_rss_bytes=recorder.maximum_rss,
                 minimum_sampled_available_memory_bytes=recorder.minimum_available,
                 maximum_sample_interval_seconds=recorder.maximum_interval,
                 progress_interval_over_two_seconds=recorder.maximum_interval > 2,
                 resource_guard_triggered=recorder.resource_guard_triggered,
                 milestones=recorder.milestones,
                 maximum_observed_virtual_time_ns=recorder.maximum_observed_virtual_time_ns,
                 sampling_errors=recorder.errors, resumable_vm_snapshot=False)
    success = (result.get('success') is True and result.get('native_report_valid') is True
               and result.get('child_exit_code') == 0 and not result.get('forced_signals')
               and audit['group_absent_confirmed'] and not audit['members'] and finished
               and recorder.count > 0 and not recorder.errors and not recorder.resource_guard_triggered
               and recorder.maximum_interval <= 2)
    report = {'success': success, 'physical_completion_proven': False,
              'success_scope': 'Strict readiness and inner cleanup only; outer guard must be checked separately',
              'outer_guard_verification_pending': True,
              'resumable_vm_snapshot': False, 'supervision': result, 'post_audit': audit}
    atomic_json(paths['audit'], report)
    if finished:
        latest = safe_json(paths['latest'])
        latest.update(status='finished' if success else 'failed', success=success,
                      success_scope=report['success_scope'], outer_guard_verification_pending=True,
                      post_audit_file=str(paths['audit']), supervision_file=str(paths['supervision']))
        atomic_json(paths['latest'], latest)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--plan', action='store_true', help='Print fixed configuration without writes or child launches')
    args = parser.parse_args(argv)
    try:
        configuration, run, paths = plan(args.profile, args.evidence_dir, args.name)
        if args.plan:
            print(json.dumps(configuration, indent=2))
            return 0
        report = execute(configuration, run, paths)
    except (Exception, KeyboardInterrupt) as exc:
        print(json.dumps({'success': False, 'error': type(exc).__name__ + ': ' + str(exc),
                          'physical_completion_proven': False}), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report['success'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
