"""Explicit Linux PID-namespace backend. Not a sandbox for hostile payloads.

Only PID1 enumerates its isolated /proc. The host verifies that proc mount once,
while PID1 has no children, before sending the execution acknowledgement.
RSS is a sampled aggregate, NOT a kernel memory limit. Caller holds exclusive
package flock and performs the exact manifest and original 22 GiB disk / 2 GiB memory admission gates.
"""
import array
import ctypes
import json
import math
import os
from pathlib import Path
import resource
import select
import signal
import socket
import subprocess
import sys
import threading
import time
from owned_process_supervisor import OwnedSupervisor, OwnershipError, CATCHABLE, identity

RSS_LIMIT = 4 * 1024**3
INTERVAL = .025
HEARTBEAT_TIMEOUT = 10.0


def pdeath(expected):
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0):
        raise OSError(ctypes.get_errno(), 'PR_SET_PDEATHSIG')
    if os.getppid() != expected:
        os._exit(125)


def send(sock, data, fds=()):
    ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', fds))] if fds else []
    sock.sendmsg([json.dumps(data).encode()], ancillary)


def receive(sock):
    try:
        data, ancillary, flags, _ = sock.recvmsg(65536, socket.CMSG_SPACE(8 * 4))
    except OSError as error:
        raise OwnershipError('Control channel receive failed') from error
    fds = []
    for level, typ, raw in ancillary:
        if level == socket.SOL_SOCKET and typ == socket.SCM_RIGHTS:
            a = array.array('i'); a.frombytes(raw[:len(raw) - len(raw) % a.itemsize]); fds.extend(a)
    try:
        if not data or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
            raise OwnershipError('Control channel closed or truncated')
        try:
            packet = json.loads(data)
            if not isinstance(packet, dict): raise ValueError('packet is not an object')
        except (ValueError, UnicodeError) as error:
            raise OwnershipError('Malformed control packet') from error
        return packet, fds
    except BaseException:
        for fd in fds: os.close(fd)
        raise


def init_main(fd):
    """Trusted, private namespace PID1; any exception exits and kills its tree."""
    if os.getpid() != 1:
        raise OwnershipError('Monitor must be namespace PID1')
    sock = socket.socket(fileno=fd)
    sock.settimeout(3)
    initfd = os.pidfd_open(1)
    procfd = os.open('/proc', os.O_RDONLY | os.O_DIRECTORY)
    if sorted(n for n in os.listdir(procfd) if n.isdecimal()) != ['1']:
        raise OwnershipError('Proc mount not private and empty')
    send(sock, {'type': 'hello', 'namespace': os.readlink('/proc/1/ns/pid')}, [initfd, procfd])
    os.close(initfd); os.close(procfd)
    config, fds = receive(sock)
    for extra in fds: os.close(extra)
    if config.get('type') != 'execute' or fds:
        raise OwnershipError('Missing execution acknowledgement')
    def limits():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CPU, (86480, 86481))
        os.nice(19)
    payload = subprocess.Popen(config['argv'], preexec_fn=limits, close_fds=True,
                               start_new_session=True)
    sock.setblocking(False)
    started = time.monotonic()
    peak = 0
    sequence = 0
    while True:
        # Parent disappearance or any control message stops PID1 immediately.
        if select.select([sock], [], [], 0)[0]:
            os._exit(124)
        total = 0
        for name in os.listdir('/proc'):
            if not name.isdecimal(): continue
            try:
                total += int(Path('/proc', name, 'statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
            except (FileNotFoundError, ProcessLookupError):
                pass  # ENOENT/ESRCH: a process exited during this isolated snapshot.
        peak = max(total, peak)
        code = payload.poll()
        reason = 'rss' if peak >= RSS_LIMIT else ('wall' if time.monotonic() - started >= 86490 else None)
        sequence += 1
        send(sock, {'type': 'sample', 'sequence': sequence, 'generated': time.monotonic(), 'rss': total, 'peak': peak, 'code': code, 'reason': reason})
        if reason:
            os._exit(124)
        # Reap adopted detached descendants, never steal primary wait status.
        if code is not None:
            while True:
                try:
                    if os.waitpid(-1, os.WNOHANG)[0] == 0: break
                except ChildProcessError: break
        time.sleep(INTERVAL)


class PayloadStatus:
    def __init__(self, owner): self.owner = owner
    @property
    def returncode(self): return self.owner.payload_code
    def poll(self):
        self.owner.rss()
        return self.returncode


class NamespaceSupervisor(OwnedSupervisor):
    def __init__(self, claim, metadata=None):
        super().__init__(claim, metadata)
        self.control = None
        self.initfd = None
        self.wrapperfd = None
        self.verified = False
        self.last_sample = None
        self.sequence = 0
        self.peak = 0
        self.payload_code = None
        self.stop_reason = None
        self.launch_attempted = False

    def __enter__(self):
        # Share the durable outcome gate, without the old /task/children backend.
        if threading.active_count() != 1 or len(os.listdir('/proc/self/task')) != 1:
            raise OwnershipError('Single-threaded supervisor required')
        if self.claim.is_symlink(): raise OwnershipError('Symlink claim rejected')
        if os.path.lexists(self.claim):
            try:
                import hashlib
                prior = json.loads(self.claim.read_text())
                result = Path(prior['result'])
                valid = (prior['version'] == 1 and prior['state'] == 'completed'
                         and prior['cleanup_verified'] is True and prior['outcome_verified'] is True
                         and hashlib.sha256(result.read_bytes()).hexdigest() == prior['result_sha256'])
            except (OSError, ValueError, KeyError, TypeError): valid = False
            if not valid: raise OwnershipError('Unresolved/stale/malformed claim: manual review required; no launch or signal')
        for sig in CATCHABLE:
            self.handlers[sig] = signal.getsignal(sig); signal.signal(sig, self._cancel)
        try:
            self.persist('unresolved', cleanup_verified=False, backend='pid-namespace')
            self.started = True
        except BaseException:
            self.restore_handlers(); raise
        return self

    def launch(self, argv, *, preexec_fn=None, **kwargs):
        if not self.started or self.launch_attempted: raise OwnershipError('Exactly one launch')
        if self.cancelled: raise InterruptedError('Cancelled before launch')
        if preexec_fn is not None:
            raise OwnershipError('Namespace backend supplies fixed CPU/core/nice limits; no arbitrary preexec')
        self.launch_attempted = True
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.control = parent
        expected = os.getpid()
        kwargs.pop('start_new_session', None)
        try:
            self.proc = subprocess.Popen(['/usr/bin/unshare', '--user', '--map-root-user', '--pid', '--fork',
                '--kill-child=SIGKILL', '--mount-proc', sys.executable, '-B', str(Path(__file__).resolve()),
                '--init', str(child.fileno())], pass_fds=(child.fileno(),),
                preexec_fn=lambda: pdeath(expected), **kwargs)
            self.wrapperfd = os.pidfd_open(self.proc.pid)
        finally:
            child.close()
        parent.settimeout(3)
        hello, fds = receive(parent)
        try:
            if len(fds) != 2 or hello.get('type') != 'hello': raise OwnershipError('Invalid PID1 handshake')
            initfd, procfd = fds
            info = Path(f'/proc/self/fdinfo/{initfd}').read_text().splitlines()
            nspid = list(map(int, next(x for x in info if x.startswith('NSpid:')).split()[1:]))
            if len(nspid) < 2 or nspid[-1] != 1 or nspid[0] <= 1: raise OwnershipError('Not distinct namespace PID1')
            if identity(nspid[0])[0] != self.proc.pid:
                raise OwnershipError('PID1 is not the exact wrapper child')
            exact = os.readlink(f'/proc/{nspid[0]}/ns/pid')
            if exact == os.readlink('/proc/self/ns/pid') or exact != hello['namespace']:
                raise OwnershipError('Namespace identity mismatch')
            if os.readlink('1/ns/pid', dir_fd=procfd) != exact:
                raise OwnershipError('Proc mount namespace mismatch')
            if sorted(n for n in os.listdir(procfd) if n.isdecimal()) != ['1']:
                raise OwnershipError('Proc mount is not isolated and empty')
            if not self.alive(initfd): raise OwnershipError('PID1 died during verification')
            self.initfd = initfd; fds.remove(initfd)
            self.verified = True
            self.persist('running', cleanup_verified=False, backend='pid-namespace', namespace=exact,
                         primary_pid=self.proc.pid, init_pid=nspid[0])
            if self.cancelled: raise InterruptedError('Cancelled before acknowledgement')
            send(parent, {'type': 'execute', 'argv': list(argv)})
            self.last_sample = time.monotonic()
            parent.setblocking(False)
            return PayloadStatus(self)
        finally:
            for fd in fds: os.close(fd)

    def rss(self):
        while self.control and select.select([self.control], [], [], 0)[0]:
            packet, fds = receive(self.control)
            for fd in fds: os.close(fd)
            if fds or packet.get('type') != 'sample': raise OwnershipError('Malformed monitor sample')
            generated, sequence = packet.get('generated'), packet.get('sequence')
            now = time.monotonic()
            if (type(generated) not in (int, float) or not math.isfinite(generated)
                    or generated > now or now - generated > HEARTBEAT_TIMEOUT
                    or (self.sequence and generated < self.last_sample)
                    or type(sequence) is not int or sequence != self.sequence + 1):
                raise OwnershipError('Namespace monitor sample stale or out of order: ' + repr({'generated': generated, 'received_host_monotonic': now, 'sequence': sequence, 'previous_sequence': self.sequence, 'previous_sample': self.last_sample, 'timeout_s': HEARTBEAT_TIMEOUT}))
            rss, peak, code, reason = (packet.get(k) for k in ('rss', 'peak', 'code', 'reason'))
            if (type(rss) is not int or type(peak) is not int or rss < 0
                    or peak < rss or peak < self.peak
                    or (code is not None and (type(code) is not int or not -64 <= code <= 255))
                    or (self.payload_code is not None and code != self.payload_code)
                    or reason not in (None, 'rss', 'wall')
                    or (reason == 'rss' and peak < RSS_LIMIT)):
                raise OwnershipError('Malformed monitor sample fields')
            self.peak = peak
            self.payload_code = packet['code']
            self.stop_reason = packet['reason']
            self.last_sample = generated
            self.sequence = sequence
            if self.stop_reason: raise OwnershipError('Namespace guard stopped: ' + self.stop_reason)
        if self.last_sample is None or time.monotonic() - self.last_sample > HEARTBEAT_TIMEOUT:
            raise OwnershipError('Namespace monitor heartbeat stale: ' + json.dumps({'last_sample_age_s': None if self.last_sample is None else time.monotonic()-self.last_sample, 'last_sequence': self.sequence, 'peak_rss_bytes': self.peak, 'pid1_alive': self.initfd is not None and self.alive(self.initfd), 'timeout_s': HEARTBEAT_TIMEOUT},sort_keys=True))
        if self.initfd is None or not self.alive(self.initfd):
            raise OwnershipError('Namespace monitor died')
        return self.peak

    def cleanup(self):
        # Only exact pidfds and the exact Popen wrapper are ever targeted/reaped.
        if self.initfd is not None and self.alive(self.initfd):
            try: signal.pidfd_send_signal(self.initfd, signal.SIGKILL)
            except ProcessLookupError: pass
        if self.wrapperfd is not None and self.alive(self.wrapperfd):
            try: signal.pidfd_send_signal(self.wrapperfd, signal.SIGKILL)
            except ProcessLookupError: pass
        if self.proc is not None: self.proc.wait(timeout=3)
        if self.launch_attempted:
            if not self.verified or self.initfd is None:
                raise OwnershipError('No verified init identity: namespace cleanup uncertain')
            if not select.select([self.initfd], [], [], 3)[0]:
                raise OwnershipError('Namespace init exit unverified')
            if self.proc is None or self.proc.returncode is None:
                raise OwnershipError('Wrapper reaping unverified')
        self.cleanup_verified = True
        self.persist('cleaned', cleanup_verified=True, backend='pid-namespace')

    def __exit__(self, typ, value, tb):
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, CATCHABLE)
        try:
            try: self.cleanup()
            except BaseException as error:
                self.cleanup_verified = False
                self.persist('uncertain', cleanup_verified=False, error=repr(error)); raise
            finally:
                if self.control: self.control.close()
                for fd in (self.initfd, self.wrapperfd):
                    if fd is not None: os.close(fd)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, mask)
            self.restore_handlers()
        return False


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--init': raise SystemExit('Internal monitor only')
    init_main(int(sys.argv[2]))
