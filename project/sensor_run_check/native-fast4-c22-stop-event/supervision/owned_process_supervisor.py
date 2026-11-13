"""Linux-only, single-threaded, exact-owned subprocess lifecycle supervision.

Call under the package's exclusive flock. Claims from earlier unresolved runs are
never used as signal targets. A sampled RSS guard is not a kernel memory cap.
SIGKILL/host death cannot be handled; the durable claim then blocks future runs.
"""
import ctypes
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import threading
import time

CATCHABLE = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}

class OwnershipError(RuntimeError):
    pass


def identity(pid):
    # comm may contain spaces and parentheses.
    fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return int(fields[1]), int(fields[19])  # ppid, starttime


def children(pid):
    result = set()
    for task in Path(f'/proc/{pid}/task').iterdir():
        try:
            result.update(map(int, (task / 'children').read_text().split()))
        except ProcessLookupError:
            pass  # ESRCH: the enumerated thread exited.
        except FileNotFoundError:
            try:
                present = task.exists()
            except ProcessLookupError:
                present = False  # The procfs existence probe raced the same exit.
            if present:
                raise OwnershipError('Kernel /proc task children interface unavailable; ownership cannot be proved')
            # A thread may exit during enumeration.
    return result


class OwnedSupervisor:
    def __init__(self, claim, metadata=None):
        self.claim = Path(claim)
        self.metadata = metadata or {}
        self.owned = {}  # pid -> (starttime, pidfd)
        self.proc = None
        self.cancelled = None
        self.cleanup_verified = False
        self.handlers = {}
        self.started = False

    def persist(self, state, *, outcome_verified=False, **extra):
        data = dict(version=1, state=state, supervisor_pid=os.getpid(),
                    metadata=self.metadata, outcome_verified=outcome_verified, **extra)
        temp = self.claim.with_name(self.claim.name + '.tmp')
        with temp.open('w') as f:
            json.dump(data, f, sort_keys=True)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(temp, self.claim)
        fd = os.open(self.claim.parent, os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)

    def __enter__(self):
        if threading.active_count() != 1 or len(list(Path('/proc/self/task').iterdir())) != 1:
            raise OwnershipError('Single-threaded supervisor required')
        if self.claim.is_symlink():
            raise OwnershipError('Symlink claim rejected')
        if os.path.lexists(self.claim):
            try:
                prior = json.loads(self.claim.read_text())
                valid = (prior['version'] == 1 and prior['state'] == 'completed'
                         and prior['cleanup_verified'] is True
                         and prior['outcome_verified'] is True)
                if valid:
                    import hashlib
                    result = Path(prior['result'])
                    valid = result.is_file() and hashlib.sha256(result.read_bytes()).hexdigest() == prior['result_sha256']
            except (OSError, ValueError, KeyError, TypeError):
                valid = False
            if not valid:
                raise OwnershipError('Unresolved/stale/malformed claim: manual review required; no launch or signal')
        if children(os.getpid()):
            raise OwnershipError('Preexisting children: cannot prove exclusive ownership')
        if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
            raise OwnershipError('Linux pidfd support required')
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise OSError(ctypes.get_errno(), 'Cannot establish child subreaper')
        subreaper = ctypes.c_int()
        if libc.prctl(37, ctypes.byref(subreaper), 0, 0, 0) != 0 or subreaper.value != 1:
            raise OwnershipError('Child subreaper state could not be verified')
        probe = os.pidfd_open(os.getpid())
        os.close(probe)
        for sig in CATCHABLE:
            self.handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, self._cancel)
        try:
            self.persist('unresolved', cleanup_verified=False)
            self.started = True
        except BaseException:
            self.restore_handlers()
            raise
        return self

    def _cancel(self, sig, frame):
        self.cancelled = sig

    def restore_handlers(self):
        for sig, handler in self.handlers.items():
            signal.signal(sig, handler)

    def register(self, pid, parent):
        if pid in self.owned:
            return
        before = identity(pid)
        if before[0] != parent:
            raise OwnershipError('Child ancestry changed before ownership establishment')
        fd = os.pidfd_open(pid)
        try:
            after = identity(pid)
            if before != after:
                raise OwnershipError('Child identity changed during pidfd establishment')
        except BaseException:
            os.close(fd)
            raise
        self.owned[pid] = (before[1], fd)

    def alive(self, fd):
        return not select.select([fd], [], [], 0)[0]

    def capture(self):
        # Only self and already-owned processes are traversed, never global /proc.
        todo = [os.getpid()]
        todo.extend(pid for pid, (_, fd) in self.owned.items() if self.alive(fd))
        seen = set()
        while todo:
            parent = todo.pop()
            if parent in seen: continue
            seen.add(parent)
            try:
                if parent != os.getpid():
                    _, expected = identity(parent)
                    if expected != self.owned[parent][0]:
                        raise OwnershipError('Owned process identity mismatch')
                found = children(parent)
            except (FileNotFoundError, ProcessLookupError):
                continue
            for pid in found:
                try:
                    self.register(pid, parent)
                    todo.append(pid)
                except ProcessLookupError:
                    pass
                except FileNotFoundError:
                    pass

    def launch(self, argv, *, preexec_fn=None, **kwargs):
        if self.proc is not None or not self.started:
            raise OwnershipError('Exactly one launch per supervisor')
        oldmask = signal.pthread_sigmask(signal.SIG_BLOCK, CATCHABLE)
        def child_setup():
            signal.pthread_sigmask(signal.SIG_SETMASK, oldmask - CATCHABLE)
            if preexec_fn is not None: preexec_fn()
        try:
            if self.cancelled:
                raise InterruptedError('Cancelled before launch')
            self.proc = subprocess.Popen(argv, preexec_fn=child_setup, **kwargs)
            # Popen has not reaped this child, so its PID cannot be recycled.
            self.register(self.proc.pid, os.getpid())
            self.persist('running', cleanup_verified=False, primary_pid=self.proc.pid)
            return self.proc
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, oldmask)

    def rss(self):
        self.capture()
        total = 0
        for pid, (start, fd) in self.owned.items():
            if not self.alive(fd): continue
            try:
                if identity(pid)[1] != start:
                    raise OwnershipError('Owned RSS process identity mismatch')
                total += int(Path(f'/proc/{pid}/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
            except (FileNotFoundError, ProcessLookupError):
                pass
        return total

    def cleanup(self):
        deadline = time.monotonic() + 3
        signalled = set()
        while True:
            self.capture()
            for pid, (_, fd) in self.owned.items():
                if fd not in signalled and self.alive(fd):
                    try: signal.pidfd_send_signal(fd, signal.SIGKILL)
                    except ProcessLookupError: pass
                    signalled.add(fd)
            # Reap only exact owned children; grandchildren are eventually adopted.
            for pid, (_, fd) in self.owned.items():
                if not self.alive(fd):
                    try:
                        reaped, status = os.waitpid(pid, os.WNOHANG)
                        if reaped and self.proc is not None and pid == self.proc.pid:
                            self.proc.returncode = os.waitstatus_to_exitcode(status)
                    except ChildProcessError:
                        pass
            # No live known processes plus no self-children proves no descendants
            # can subsequently be born or become newly adopted by this subreaper.
            if not any(self.alive(fd) for _, fd in self.owned.values()) and not children(os.getpid()):
                self.cleanup_verified = True
                self.persist('cleaned', cleanup_verified=True)
                return
            if time.monotonic() >= deadline:
                raise OwnershipError('Cleanup deadline: owned descendants unresolved')
            time.sleep(.01)

    def complete(self, result_path):
        """Call only after outcome evaluation and durable result publication."""
        if not self.cleanup_verified:
            raise OwnershipError('Cannot complete without verified process cleanup')
        result = Path(result_path)
        with result.open('rb') as f:
            payload = json.load(f)
            if payload.get('cleanup_verified') is not True:
                raise OwnershipError('Result does not record verified cleanup')
            os.fsync(f.fileno())
        directory = os.open(result.parent, os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
        import hashlib
        self.persist('completed', cleanup_verified=True, outcome_verified=True,
                     result=str(result.resolve()), result_sha256=hashlib.sha256(result.read_bytes()).hexdigest())

    def __exit__(self, typ, value, tb):
        oldmask = signal.pthread_sigmask(signal.SIG_BLOCK, CATCHABLE)
        try:
            try:
                self.cleanup()
            except BaseException as error:
                self.cleanup_verified = False
                self.persist('uncertain', cleanup_verified=False, error=repr(error))
                raise OwnershipError('Cleanup not verified; future launches blocked') from error
            finally:
                for _, fd in self.owned.values(): os.close(fd)
        finally:
            # Consume pending cancellation with our non-raising handler first.
            signal.pthread_sigmask(signal.SIG_SETMASK, oldmask)
            self.restore_handlers()
        return False
