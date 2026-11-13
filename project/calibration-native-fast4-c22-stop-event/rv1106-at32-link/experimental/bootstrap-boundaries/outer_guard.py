#!/usr/bin/env python3
"""Linux subreaper guard for a comparator and all descendants, including setsid children."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

RSS_LIMIT = 4 * 1024**3
AVAILABLE_FLOOR = 2 * 1024**3


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def process_info(pid):
    try:
        text = Path(f'/proc/{pid}/stat').read_text()
        fields = text[text.rfind(')')+2:].split()
        return {'pid': int(pid), 'state': fields[0], 'ppid': int(fields[1]),
                'pgid': int(fields[2]), 'session': int(fields[3]),
                'starttime': int(fields[19]),
                'rss_bytes': int(fields[21]) * os.sysconf('SC_PAGE_SIZE')}
    except (OSError, ValueError, IndexError):
        return None


def proc_snapshot():
    result = {}
    for entry in Path('/proc').iterdir():
        if entry.name.isdigit():
            info = process_info(entry.name)
            if info: result[info['pid']] = info
    return result


def descendants(snapshot, root):
    found = {root}
    while True:
        new = {pid for pid, row in snapshot.items() if row['ppid'] in found}
        if new <= found: break
        found |= new
    return [row for pid, row in snapshot.items() if pid in found and pid != root]


def available_memory():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1])*1024
    raise RuntimeError('MemAvailable missing; cannot enforce memory floor')


def enable_subreaper():
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'PR_SET_CHILD_SUBREAPER failed')
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise RuntimeError('pidfd APIs required for PID-reuse-safe cleanup')


def reap_children(process, reaped):
    if process is not None:
        process.poll()
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        if pid == 0:
            break
        if process is not None and pid == process.pid:
            # Comparator may exit after poll() but before waitpid(-1). Preserve
            # its actual status rather than letting Popen infer zero on ECHILD.
            process.returncode = os.waitstatus_to_exitcode(status)
        reaped.append({'pid': pid, 'wait_status': status})


def supervise(command, record_path, seconds):
    # The wrapper must be a dedicated process; do not call in a shared worker.
    record_path = record_path.resolve()
    record_path.parent.mkdir(parents=True, exist_ok=True)
    with record_path.open('x') as stream:
        stream.write('{}\n')
    start = time.monotonic()
    deadline = start+seconds
    operational_deadline = deadline-2
    record = {'schema': 1, 'passed': False, 'status': 'incomplete',
              'command': command, 'wall_budget_s': seconds,
              'rss_limit_bytes': RSS_LIMIT, 'available_floor_bytes': AVAILABLE_FLOOR,
              'signals': [], 'tracked_processes': [], 'whole_groups_absent': False,
              'all_descendants_absent': False, 'comparator_exit_code': None,
              'peak_group_rss_bytes': 0, 'minimum_available_bytes': None}
    atomic_json(record_path, record)
    tracked = {}
    groups = set()
    process = None
    failure = None
    reaped = []
    termination_request = {}
    previous_handlers = {}
    def request_stop(signum, frame):
        termination_request['signal'] = signum
    for signum in (signal.SIGTERM, signal.SIGINT):
        previous_handlers[signum] = signal.signal(signum, request_stop)

    def observe():
        snapshot = proc_snapshot()
        rows = descendants(snapshot, os.getpid())
        for row in rows:
            key = (row['pid'], row['starttime'])
            tracked[key] = row
            groups.add(row['pgid'])
        # Include detached known identities, even if ancestry races a scan.
        for key, row in tracked.items():
            current = snapshot.get(row['pid'])
            if current and current['starttime'] == key[1] and current not in rows:
                rows.append(current)
        return snapshot, rows

    def reap():
        reap_children(process, reaped)

    def kill_identity(row, reason):
        key = (row['pid'], row['starttime'])
        entry = {'pid': row['pid'], 'starttime': row['starttime'], 'pgid': row['pgid'],
                 'signal': 'SIGKILL', 'reason': reason, 'outcome': 'pending'}
        record['signals'].append(entry)
        fd = None
        try:
            fd = os.pidfd_open(row['pid'])
            current = process_info(row['pid'])
            if not current or (current['pid'], current['starttime']) != key:
                entry['outcome'] = 'identity_absent_or_changed'
                return
            signal.pidfd_send_signal(fd, signal.SIGKILL)
            entry['outcome'] = 'sent'
        except ProcessLookupError:
            entry['outcome'] = 'process_absent'
        except OSError as exc:
            # One failed signal must never prevent cleanup of other identities,
            # later retries, or the final fail-closed evidence record.
            entry['outcome'] = 'error'
            entry['error'] = repr(exc)
        finally:
            if fd is not None:
                try: os.close(fd)
                except OSError as exc: entry['close_error'] = repr(exc)

    try:
        enable_subreaper()
        if available_memory() < AVAILABLE_FLOOR:
            raise RuntimeError('MemAvailable below 2GiB before launch')
        with record_path.with_suffix(record_path.suffix+'.log').open('xb') as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            while True:
                snapshot, rows = observe()
                rss = sum(row['rss_bytes'] for row in rows)
                available = available_memory()
                record['peak_group_rss_bytes'] = max(record['peak_group_rss_bytes'], rss)
                prior = record['minimum_available_bytes']
                record['minimum_available_bytes'] = available if prior is None else min(prior, available)
                code = process.poll()
                reap()
                if termination_request:
                    failure = 'outer guard received '+signal.Signals(termination_request['signal']).name; break
                if rss > RSS_LIMIT:
                    failure = 'descendant RSS exceeds 4GiB'; break
                if available < AVAILABLE_FLOOR:
                    failure = 'MemAvailable below 2GiB'; break
                if time.monotonic() >= operational_deadline:
                    failure = 'overall wall deadline'; break
                if code is not None:
                    # A final post-reap scan is required. Exiting the comparator
                    # must not hide a child that changed process group/session.
                    _, remaining = observe()
                    if code != 0: failure = 'comparator exited nonzero'
                    elif remaining: failure = 'comparator exited with surviving descendants'
                    break
                time.sleep(min(.02, max(0, operational_deadline-time.monotonic())))
    except BaseException as exc:
        failure = repr(exc)
    finally:
        # Repeated scans find reparented/double-forked descendants after parent
        # death. Signal identities through pidfds, never a recycled numeric PID.
        while True:
            # At least one observe/kill pass even if earlier work overran.
            reap()
            _, remaining = observe()
            if not remaining: break
            for row in remaining:
                if row['state'] != 'Z': kill_identity(row, failure or 'cleanup surviving descendant')
            if time.monotonic() >= deadline:
                break
            time.sleep(min(.01, max(0, deadline-time.monotonic())))
        reap()
        snapshot, remaining = observe()
        group_members = [row for row in snapshot.values() if row['pgid'] in groups]
        record.update(status='failed' if failure else 'finished', failure=failure,
                      comparator_exit_code=process.poll() if process else None,
                      all_descendants_absent=not remaining,
                      whole_groups_absent=not group_members,
                      surviving_processes=remaining, surviving_group_members=group_members,
                      tracked_processes=list(tracked.values()), tracked_groups=sorted(groups),
                      reaped_adopted_children=reaped, elapsed_wall_s=time.monotonic()-start)
        record['passed'] = (failure is None and record['comparator_exit_code'] == 0
                            and not record['signals'] and not remaining and not group_members)
        if not record['passed']: record['status'] = 'failed'
        atomic_json(record_path, record)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    return 0 if record['passed'] else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--record', type=Path, required=True)
    ap.add_argument('--wall-seconds', type=float, required=True)
    ap.add_argument('command', nargs=argparse.REMAINDER)
    args = ap.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command: ap.error('Command required after --')
    if not 3 <= args.wall_seconds <= 180: ap.error('wall-seconds must be 3..180')
    return supervise(command, args.record, args.wall_seconds)

if __name__ == '__main__': sys.exit(main())
