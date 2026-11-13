"""Acknowledge existing final monitor batches using public echo responses only.

No firmware execution, memory reads, time advances, or new getters are added.
The caller owns one absolute cleanup deadline; writes and reads share it.
"""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import re
import stat
import time
import uuid

from renode_bootstrap import bounded_send

ANSI = re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]')
ECHO = re.compile(rb'echo "([A-Za-z0-9_]+)"')
ERROR = re.compile(rb'There was an error|No such command or device:|Unhandled exception|'
                   rb'\[(?:ERROR|FATAL)\]|\bDisposed\.')
MAX_LOG_BYTES = 1024 * 1024


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise RuntimeError('Final export deadline expired; completion unconfirmed')
    return value


def verify_command_file(path,identity,digest,size):
    """Detect replacement/rewrite; file is retained on every outcome, no retry."""
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as source:
        info=os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or (info.st_dev,info.st_ino)!=identity or info.st_size!=size
                or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o400):
            raise RuntimeError('Final command file replaced or truncated')
        raw=source.read(size+1)
    if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=digest:
        raise RuntimeError('Final command file changed')

def acknowledge_batch(board, commands, peers, lock, log_dir, shared, deadline, *, transport='stdin'):
    """Return evidence only after fresh BEGIN, every echo envelope, and END.

Only append bytes in this board's existing Renode log are read. Command input
echoes do not count as responses. Marker completion proves ordered monitor
processing, not the semantic correctness of every exported getter value.
"""
    remaining(deadline)
    if transport not in ('stdin','include-file'):
        raise ValueError('Unknown final export transport')
    if transport=='include-file' and not shared:
        raise ValueError('Include-file final export requires the single shared monitor')
    if board not in ('main', 'nozzle', 'motor'):
        raise ValueError('Unknown final export board')
    process = peers.get(board)
    if process is None or process.poll() is not None:
        raise RuntimeError('Final export peer unavailable: ' + board)
    path = log_dir / ('renode.log' if shared or board == 'main' else board + '-renode.log')
    token = ('FINAL_EXPORT_' + board + '_' + uuid.uuid4().hex).encode('ascii')
    begin, end = token + b'_BEGIN', token + b'_END'
    envelopes = [match[1] for line in commands.splitlines()
                 if (match := ECHO.fullmatch(line)) is not None]
    expected = [begin, *envelopes, end]
    if len(set(expected)) != len(expected):
        raise ValueError('Duplicate final export envelope marker')
    payload = b'echo "' + begin + b'"\n' + commands + b'\n'
    if shared:
        payload = ('mach set "' + board + '"\n').encode() + payload + b'mach set "main"\n'
    payload += b'echo "' + end + b'"\n'
    transport_path=None
    transport_identity=None
    transport_sha256=None
    sent_payload=payload
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream, ExitStack() as retained_files:
        initial = os.fstat(stream.fileno())
        if not stat.S_ISREG(initial.st_mode):
            raise ValueError('Final export log is not a regular file')
        identity = (initial.st_dev, initial.st_ino)
        stream.seek(initial.st_size)
        if transport=='include-file':
            # The private run directory is the same namespace/path visible to
            # the shared Renode process. Save the exact original payload once;
            # only its transport changes, never its order, commands or markers.
            folder=Path(log_dir)
            if (not folder.is_absolute() or folder.is_symlink() or folder.resolve()!=folder or
                    not folder.is_dir() or re.fullmatch(r'/[A-Za-z0-9_./-]+',str(folder)) is None):
                raise ValueError('Unsafe include-file final export directory')
            parent_info=folder.stat(follow_symlinks=False)
            if parent_info.st_uid!=os.getuid() or stat.S_IMODE(parent_info.st_mode)&0o022:
                raise ValueError('Include-file final export directory must be owned and not writable by others')
            if len(payload)>MAX_LOG_BYTES:
                raise ValueError('Final export command file exceeds fixed 1 MiB bound')
            batch_folder=folder/'final-export-batches'
            batch_folder.mkdir(mode=0o700,exist_ok=True)
            directory_info=batch_folder.stat(follow_symlinks=False)
            if (not stat.S_ISDIR(directory_info.st_mode) or batch_folder.resolve()!=batch_folder or
                    directory_info.st_uid!=os.getuid() or stat.S_IMODE(directory_info.st_mode)!=0o700):
                raise ValueError('Final export batch directory is not private and owned')
            transport_path=batch_folder/(token.decode()+'.commands')
            remaining(deadline)
            created=os.open(transport_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            # Keep the creating descriptor open through acknowledgement/failure,
            # so unlink+recreate cannot reuse its inode and evade identity checks.
            retained_files.callback(os.close,created)
            with os.fdopen(created,'wb',closefd=False) as commands_file:
                commands_file.write(payload);commands_file.flush()
                os.fchmod(commands_file.fileno(),0o400)
                info=os.fstat(commands_file.fileno());transport_identity=(info.st_dev,info.st_ino)
            transport_sha256=hashlib.sha256(payload).hexdigest()
            verify_command_file(transport_path,transport_identity,transport_sha256,len(payload))
            remaining(deadline)
            sent_payload=('include @'+str(transport_path)+'\n').encode('ascii')
        bounded_send(process, lock, sent_payload, timeout=remaining(deadline))
        pending, observed, read_bytes = b'', [], 0
        while True:
            remaining(deadline)
            if process.poll() is not None:
                raise RuntimeError('Final export peer exited before acknowledgement: ' + board)
            info = os.stat(path, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != identity
                    or info.st_size < stream.tell()):
                raise RuntimeError('Final export log replaced or truncated')
            data = stream.read(65536)
            read_bytes += len(data)
            if read_bytes > MAX_LOG_BYTES:
                raise RuntimeError('Final export log append limit exceeded')
            pending += data
            lines = pending.split(b'\n')
            pending = lines.pop()
            for raw in lines:
                line = ANSI.sub(b'', raw).strip(b'\r')
                if ERROR.search(line):
                    raise RuntimeError('Final export monitor error: ' + line.decode(errors='replace'))
                if line in expected:
                    if len(observed) == len(expected) or line != expected[len(observed)]:
                        raise RuntimeError('Final export envelope missing, repeated, or out of order')
                    observed.append(line)
            remaining(deadline)
            if len(observed) == len(expected):
                if transport_path is not None:
                    verify_command_file(transport_path,transport_identity,transport_sha256,len(payload))
                    remaining(deadline)
                return {'transport':transport,'stdin_bytes':len(sent_payload),'command_payload_bytes':len(payload),
                        **({'command_file':str(transport_path.relative_to(log_dir)),'command_file_sha256':transport_sha256}
                           if transport_path is not None else {}),'board': board, 'log': path.name, 'status': 'complete',
                        'begin_marker': begin.decode(), 'end_marker': end.decode(),
                        'log_start_offset': initial.st_size, 'log_end_offset': stream.tell(),
                        'envelope_responses': len(envelopes)}
            if not data:
                time.sleep(min(.01, remaining(deadline)))
