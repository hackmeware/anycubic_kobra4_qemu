#!/usr/bin/env python3
"""Host-only owner lease; never advances clocks or sends guest commands.

A missing, stale, malformed or cancelled lease asks the unchanged outer guard
for SIGTERM cleanup. Heartbeat/checkpoint is evidence, not a resumable VM.
"""
import json
import os
from pathlib import Path
import signal
import stat
import threading
import time

LEASE_SECONDS = 120.0
HEARTBEAT_SECONDS = 2.0
POLL_SECONDS = 0.2


def read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError('Owner evidence must be a regular file')
        data = f.read(16385)
    if len(data) > 16384:
        raise ValueError('Owner evidence exceeds bound')
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError('Owner evidence must be an object')
    return result


def write(path, value):
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, allow_nan=False); f.write('\n'); f.flush(); os.fsync(f.fileno())
    tmp.replace(path)


def renew(directory):
    directory = Path(directory)
    # Cancellation is permanent for this one attempt.
    if (directory / 'owner-cancel').exists():
        raise ValueError('Owner has cancelled this attempt')
    heartbeat = read(directory / 'owner-heartbeat.json')
    if heartbeat.get('status') != 'active':
        raise ValueError('Owner is not active')
    old = read(directory / 'owner-lease.json')
    now = time.monotonic_ns()
    if type(old.get('renewed_monotonic_ns')) is not int or not 0 <= now - old['renewed_monotonic_ns'] <= int(LEASE_SECONDS * 1e9):
        raise ValueError('Lease expired; no revival is permitted')
    value = {'schema': 1, 'renewed_monotonic_ns': now, 'sequence': old['sequence'] + 1}
    write(directory / 'owner-lease.json', value)
    return value


class Lease:
    def __init__(self, directory, stop_request, *, seconds=LEASE_SECONDS):
        self.directory = Path(directory)
        self.stop_request = Path(stop_request)
        self.seconds = seconds
        self.stop = threading.Event()
        self.reason = None
        self.signal_sent = False
        self.started = time.monotonic()
        self.initial_handler = signal.getsignal(signal.SIGTERM)
        for name in ('owner-lease.json', 'owner-heartbeat.json', 'owner-cancel'):
            p = self.directory / name
            if p.exists() or p.is_symlink():
                raise ValueError('Fresh owner control paths required')
        write(self.directory / 'owner-lease.json', {'schema': 1, 'renewed_monotonic_ns': time.monotonic_ns(), 'sequence': 0})
        self.publish('active')
        self.thread = threading.Thread(target=self.loop, name='owner-lease-heartbeat', daemon=True)

    def publish(self, status):
        write(self.directory / 'owner-heartbeat.json', {
            'schema': 1, 'status': status, 'owner_pid': os.getpid(),
            'monotonic_ns': time.monotonic_ns(), 'elapsed_seconds': time.monotonic() - self.started,
            'lease_seconds': self.seconds, 'stop_reason': self.reason,
            'guard_cleanup_signal_sent': self.signal_sent, 'resumable_vm_snapshot': False})

    def loop(self):
        last = 0.0
        while not self.stop.is_set():
            try:
                if (self.directory / 'owner-cancel').exists():
                    self.reason = self.reason or 'owner_cancelled'
                lease = read(self.directory / 'owner-lease.json')
                stamp = lease.get('renewed_monotonic_ns')
                age = time.monotonic_ns() - stamp if type(stamp) is int else -1
                if not 0 <= age <= int(self.seconds * 1e9):
                    self.reason = self.reason or 'owner_lease_expired_or_invalid'
            except Exception as exc:
                self.reason = self.reason or 'owner_lease_unavailable:' + type(exc).__name__
            if self.reason and not self.signal_sent:
                try:
                    with self.stop_request.open('x') as f:
                        f.write('Owner lease requests stop; no continuation.\n')
                except (FileNotFoundError, FileExistsError):
                    pass
                except OSError:
                    pass  # Outer cleanup signal remains authoritative.
                # Never signal before the unchanged guard installs its handler.
                if signal.getsignal(signal.SIGTERM) != self.initial_handler:
                    os.kill(os.getpid(), signal.SIGTERM)
                    self.signal_sent = True
            now = time.monotonic()
            if now - last >= HEARTBEAT_SECONDS:
                try:
                    self.publish('active')
                except Exception as exc:
                    self.reason = self.reason or 'owner_heartbeat_failure:' + type(exc).__name__
                last = now
            self.stop.wait(POLL_SECONDS)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, kind, value, trace):
        self.stop.set()
        self.thread.join(timeout=2)
        self.publish('finished' if not self.reason and kind is None else 'stopped')
