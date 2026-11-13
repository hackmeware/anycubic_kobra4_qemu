#!/usr/bin/env python3
"""Bound a trusted, non-daemonizing native observer, including startup/cleanup.

All budgets are HOST wall seconds. --total-seconds includes grace, TERM and KILL
reserves; it is not the firmware's virtual-time budget. Child stdout/stderr are
inherited (no pipe that a grandchild can keep open). Only the new child's process
group is signalled. A process that deliberately leaves that group is outside this
contract; run only trusted foreground launchers. No physical success is inferred.

Example: ... --stop-request RUN/stop-request --native-report RUN/ready-observation.json
  --evidence supervision.json --total-seconds 60 --grace-seconds 10
  --term-seconds 2 --kill-seconds 2 -- python3 run_native_ready_observation.py NAME

Deadlines bound waits, not OS scheduling or blocked filesystem/kernel operations.
External SIGKILL cannot be handled: the initial evidence remains unsuccessful.
"""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
import time

MAX_REPORT = 1024 * 1024


def read_json_file(path):
    """Read bounded regular JSON without following links or waiting on a FIFO."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Native report is not a regular file')
        data = stream.read(MAX_REPORT + 1)
    if len(data) > MAX_REPORT:
        raise ValueError('Native report exceeds size limit')
    return json.loads(data)


def read_ready_report(path):
    """Validate the final shape actually emitted by run_native_ready_observation."""
    report = read_json_file(path)
    if not isinstance(report, dict):
        raise ValueError('Native report is not an object')
    for key in ('error', 'stop_request_error', 'record_write_error'):
        if key in report:
            raise ValueError('Native report contains ' + key)
    if report.get('phase') != 'verified_ready' or report.get('final_export_requested') is not True:
        raise ValueError('Native readiness/final export was not verified')
    for key, expected in [('request_count', 1), ('launcher_exit_code', 0)]:
        if type(report.get(key)) is not int or report[key] != expected:
            raise ValueError('Invalid native ' + key)
    result = report.get('result')
    if not isinstance(result, dict):
        raise ValueError('Missing ready result')
    for key in ('client_exit_status', 'transport_exit_status'):
        if type(result.get(key)) is not int or result[key] != 0:
            raise ValueError('Invalid ready ' + key)
    response = result.get('api_response')
    if not isinstance(response, dict) or response.get('state') != 'ready':
        raise ValueError('Missing ready API state')
    if result.get('physical_completion_proven') is not False:
        raise ValueError('Unexpected physical-completion claim')
    return report


def group_absent(pgid):
    """An exited leader is insufficient. Zombies/permission errors are not absence."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    return False


def atomic_save(path, report):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def supervise(command, *, stop_request, native_report, evidence, total_seconds,
              grace_seconds=10., term_seconds=2., kill_seconds=2., poll_seconds=.05,
              virtual_time_file=None, max_virtual_time_ns=None):
    start = time.monotonic()
    record = {'schema_version': 1, 'success': False, 'physical_completion_proven': False,
              'command': list(command), 'stages': [], 'forced_signals': [], 'errors': [],
              'child_exit_code': None, 'process_group_cleanup_confirmed': False,
              'native_report_valid': False, 'elapsed_seconds': 0.}
    process = None
    evidence_created = False
    paths = [Path(p).absolute() for p in (stop_request, native_report, evidence)]
    stop_request, native_report, evidence = paths
    total_end = start + total_seconds
    term_start = total_end - term_seconds - kill_seconds
    active_end = term_start - grace_seconds

    def event(stage, **detail):
        record['stages'].append(dict(stage=stage, elapsed_seconds=time.monotonic() - start, **detail))

    def error(exc):
        message = type(exc).__name__ + ': ' + str(exc)
        if message not in record['errors']:
            record['errors'].append(message)

    def save():
        record['elapsed_seconds'] = time.monotonic() - start
        atomic_save(evidence, record)

    def stopped():
        record['process_group_cleanup_confirmed'] = False
        record['child_exit_code'] = process.poll()
        absent = group_absent(process.pid)
        record['process_group_cleanup_confirmed'] = absent and record['child_exit_code'] is not None
        return record['process_group_cleanup_confirmed']

    def wait_until(deadline):
        while True:
            try:
                if stopped():
                    return True
            except Exception as exc:
                error(exc)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(poll_seconds, remaining))

    def request_stop():
        # Do not create the native run directory: the launcher must create it.
        if stop_request.exists():
            event('stop_request_already_present')
            return True
        try:
            with stop_request.open('x') as stream:
                stream.write('Outer supervisor requests bounded graceful final export.\n')
            event('stop_requested')
            return True
        except FileNotFoundError:
            return False
        except FileExistsError:
            event('stop_request_already_present')
            return True

    def force(sig):
        # Record the attempt before sending: all forced paths fail closed.
        record['forced_signals'].append(signal.Signals(sig).name)
        event('force_signal', signal=signal.Signals(sig).name)
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except OSError as exc:
            error(exc)

    previous = {}
    def interrupted(signum, frame):
        raise InterruptedError('Supervisor received ' + signal.Signals(signum).name)

    try:
        if len(set(paths)) != 3:
            raise ValueError('Three distinct paths required')
        if evidence.exists() or evidence.is_symlink():
            raise ValueError('Evidence must be a fresh path')
        # Durable unsuccessful evidence exists even for a rejected preflight.
        with evidence.open('x') as stream:
            evidence_created = True
            json.dump(record, stream); stream.flush(); os.fsync(stream.fileno())
        budgets = [total_seconds, grace_seconds, term_seconds, kill_seconds, poll_seconds]
        if not all(math.isfinite(x) and x > 0 for x in budgets):
            raise ValueError('Budgets must be finite positive numbers')
        if total_seconds <= grace_seconds + term_seconds + kill_seconds:
            raise ValueError('Total budget must exceed all cleanup reserves')
        if not command or len(set(paths)) != 3:
            raise ValueError('Explicit command and three distinct paths required')
        if any(p.exists() or p.is_symlink() for p in (stop_request, native_report)):
            raise ValueError('Stop request, native report and evidence must be fresh paths')
        if (virtual_time_file is None) != (max_virtual_time_ns is None):
            raise ValueError('Virtual-time file and threshold must be supplied together')
        if max_virtual_time_ns is not None and (type(max_virtual_time_ns) is not int or max_virtual_time_ns < 0):
            raise ValueError('Virtual-time threshold must be a nonnegative integer')
        record['budgets_seconds'] = dict(total=total_seconds, graceful=grace_seconds, term=term_seconds, kill=kill_seconds)
        record['virtual_time_threshold_ns'] = max_virtual_time_ns
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, interrupted)
        if time.monotonic() >= active_end:
            raise TimeoutError('Startup exhausted active wall budget')
        process = subprocess.Popen(command, start_new_session=True)
        record['child_pid'] = process.pid
        record['process_group_id'] = process.pid
        event('started'); save()
        while not stopped() and time.monotonic() < active_end:
            if virtual_time_file is not None and Path(virtual_time_file).exists():
                sample = read_json_file(virtual_time_file)
                if not isinstance(sample, dict):
                    raise ValueError('Virtual-time sample is not an object')
                now = sample.get('virtual_time_ns')
                if type(now) is not int or now < 0:
                    raise ValueError('Invalid virtual-time sample')
                record['last_virtual_time_ns'] = now
                if now >= max_virtual_time_ns:
                    event('virtual_time_threshold_observed', virtual_time_ns=now)
                    break
            time.sleep(min(poll_seconds, max(0, active_end - time.monotonic())))
        event('active_phase_ended', wall_budget_reached=time.monotonic() >= active_end)
    except (Exception, KeyboardInterrupt) as exc:
        error(exc)
    finally:
        # Repeated cancellation must not interrupt the bounded cleanup sequence.
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        if process is not None:
            try:
                if not stopped():
                    event('graceful_cleanup')
                    grace_end = min(term_start, time.monotonic() + grace_seconds)
                    requested = request_stop()
                    while not stopped() and time.monotonic() < grace_end:
                        if not requested:
                            requested = request_stop()
                        time.sleep(min(poll_seconds, max(0, grace_end - time.monotonic())))
                    if not requested:
                        error(RuntimeError('Stop-request directory never became available'))
            except (Exception, KeyboardInterrupt) as exc:
                error(exc)
            # Independent guarded stages: even stop-file or status errors must not
            # skip group TERM/KILL. Unknown cleanup is treated as still running.
            for sig, reserve in ((signal.SIGTERM, term_seconds), (signal.SIGKILL, kill_seconds)):
                limit = total_end - kill_seconds if sig == signal.SIGTERM else total_end
                deadline = min(limit, time.monotonic() + reserve)
                known_stopped = False
                try:
                    known_stopped = stopped()
                except (Exception, KeyboardInterrupt) as exc:
                    error(exc)
                if known_stopped:
                    break
                force(sig)
                try:
                    wait_until(deadline)
                except (Exception, KeyboardInterrupt) as exc:
                    error(exc)
            try:
                if not stopped():
                    error(RuntimeError('Process-group cleanup unconfirmed at deadline'))
            except Exception as exc:
                error(exc)
            try:
                read_ready_report(native_report)
                record['native_report_valid'] = True
            except Exception as exc:
                error(exc)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if time.monotonic() > total_end:
            error(TimeoutError('Total host wall budget exhausted'))
        record['success'] = (process is not None and not record['errors'] and
                             not record['forced_signals'] and record['child_exit_code'] == 0 and
                             record['process_group_cleanup_confirmed'] and record['native_report_valid'])
        event('finished')
        try:
            # Never overwrite pre-existing evidence rejected in preflight.
            if evidence_created:
                save()
        except Exception as exc:
            error(exc); record['success'] = False
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('stop-request', 'native-report', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--total-seconds', type=float, required=True)
    parser.add_argument('--grace-seconds', type=float, default=10.)
    parser.add_argument('--term-seconds', type=float, default=2.)
    parser.add_argument('--kill-seconds', type=float, default=2.)
    parser.add_argument('--virtual-time-file', type=Path)
    parser.add_argument('--max-virtual-time-ns', type=int)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = vars(parser.parse_args(argv))
    command = args.pop('command')
    if command[:1] == ['--']:
        command = command[1:]
    report = supervise(command, **args)
    print(json.dumps(report, indent=2))
    return 0 if report['success'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
