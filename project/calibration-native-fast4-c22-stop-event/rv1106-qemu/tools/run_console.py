#!/usr/bin/env python3
"""Run RV1106 firmware with an optional, explicitly requested diagnostic console."""
import argparse
import hashlib
import json
import os
import pathlib
import re
import select
import signal
import subprocess
import sys
import tempfile
import time

KNOWN_SHA256 = 'a2621d3b343666d4044502cc3f522a1ef15555c3920417607099e77e57378ce1'
RAM = 256 * 1024 * 1024


class DebugError(RuntimeError):
    pass


class Pipe:
    def __init__(self, path):
        self.path = str(path)
        for ext in ('.in', '.out'):
            os.mkfifo(self.path + ext, 0o600)
        self.writer = os.open(self.path + '.in', os.O_RDWR | os.O_NONBLOCK)
        self.reader = os.open(self.path + '.out', os.O_RDWR | os.O_NONBLOCK)
        self.buffer = b''

    def close(self):
        os.close(self.writer)
        os.close(self.reader)

    def send(self, line):
        data = line.encode() + b'\n'
        if os.write(self.writer, data) != len(data):
            raise DebugError('Short control-pipe write')

    def read(self, timeout=5):
        end = time.monotonic() + timeout
        while b'\n' not in self.buffer:
            remaining = end - time.monotonic()
            if remaining <= 0 or not select.select([self.reader], [], [], remaining)[0]:
                raise DebugError('QEMU control channel timed out')
            self.buffer += os.read(self.reader, 65536)
            if len(self.buffer) > 1024 * 1024:
                raise DebugError('QEMU control response exceeds limit')
        line, self.buffer = self.buffer.split(b'\n', 1)
        return line.decode()


class QMP:
    def __init__(self, pipe):
        self.pipe = pipe
        self.sequence = 0
        greeting = json.loads(pipe.read())
        if 'QMP' not in greeting:
            raise DebugError('Missing QMP greeting')
        self.command('qmp_capabilities')

    def command(self, name, arguments=None):
        self.sequence += 1
        request = dict(execute=name, id=self.sequence)
        if arguments is not None:
            request['arguments'] = arguments
        self.pipe.send(json.dumps(request))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            response = json.loads(self.pipe.read(max(.001, deadline - time.monotonic())))
            if response.get('id') == self.sequence:
                if 'error' in response:
                    raise DebugError('QMP error: ' + str(response['error']))
                return response.get('return')
        raise DebugError('QMP response timed out')


def read_flags(qtest, address):
    qtest.send('readl 0x%x' % address)
    response = qtest.read().strip().split()
    if len(response) != 2 or response[0] != 'OK':
        raise DebugError('Unexpected qtest read response')
    value = int(response[1], 16)
    if not 0 <= value <= 0xffffffff:
        raise DebugError('Invalid flags word')
    return value


def enable_console(qmp, qtest):
    qmp.command('stop')
    try:
        regs = qmp.command('human-monitor-command', {'command-line': 'info registers'})
        match = re.search(r'\bR09=([0-9a-fA-F]{8})\b', regs or '')
        if not match:
            raise DebugError('Could not identify ARM R09/global-data pointer')
        gd = int(match.group(1), 16)
        if gd % 4 or not 0x200000 <= gd <= RAM - 8:
            raise DebugError('R09 is not an aligned relocated DRAM pointer')
        address = gd + 4
        flags = read_flags(qtest, address)
        # U-Boot 2017.09 GD_FLG_RELOC and GD_FLG_DEVINIT must be established.
        if flags & 0x81 != 0x81:
            raise DebugError('U-Boot has not reached initialized, relocated state')
        if flags & 0x40:
            updated = flags & ~0x40
            qtest.send('writel 0x%x 0x%x' % (address, updated))
            if qtest.read().strip() != 'OK':
                raise DebugError('qtest flag write was not acknowledged')
            if read_flags(qtest, address) != updated:
                raise DebugError('Runtime console flag readback failed')
            print('\nDiagnostic console enabled: RAM gd->flags at 0x%x changed '
                  '0x%08x -> 0x%08x (only bit 0x40 cleared). Firmware file unchanged.\n'
                  'Press Ctrl-C then Enter to interrupt autoboot if needed.' %
                  (address, flags, updated), file=sys.stderr, flush=True)
        else:
            print('\nDiagnostic check: console-disable flag already clear; no RAM change.',
                  file=sys.stderr, flush=True)
    finally:
        qmp.command('cont')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=pathlib.Path, help='Normalized raw U-Boot or ARM ELF (not a FIT/update container)')
    parser.add_argument('--qemu', default='qemu-system-arm')
    parser.add_argument('--enable-console-debug', action='store_true',
                        help='Clear known U-Boot runtime console-disable bit; only the validated image SHA is permitted')
    args = parser.parse_args()
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    image = args.image.resolve()
    if not image.is_file():
        parser.error('Firmware image is not a file')
    # Reuse strict format/range validation. Raw requires this launcher\'s explicit
    # normalized-image contract; use rv1106_image.py to inspect arbitrary input.
    import rv1106_image
    if not 0 < image.stat().st_size <= rv1106_image.MAX_INPUT:
        parser.error('Empty or oversized firmware')
    data = image.read_bytes()
    try:
        info = rv1106_image.inspect(data, 'raw', RAM)
        if info['format'] not in ('raw', 'elf'):
            raise DebugError('Extract/normalize FIT or update-container input first')
        if args.enable_console_debug and hashlib.sha256(data).hexdigest() != KNOWN_SHA256:
            raise DebugError('Diagnostic patch refused: image SHA-256 is not the validated original image')
    except (rv1106_image.ImageError, DebugError) as exc:
        parser.error(str(exc))
    cmd = [args.qemu, '-M', 'rv1106', '-m', '256M', '-display', 'none',
           '-monitor', 'none', '-serial', 'stdio', '-nic', 'none', '-kernel', str(image)]
    if not args.enable_console_debug:
        # Normal mode applies no debugger and no firmware/runtime modifications.
        return subprocess.call(cmd)
    print('WARNING: explicit diagnostic mode will change the known firmware\'s '
          'runtime console flag in guest RAM. It does not modify the image file.',
          file=sys.stderr, flush=True)
    process = None
    pipes = []
    with tempfile.TemporaryDirectory(prefix='rv1106-console-') as tmp:
        try:
            qmp_pipe, qtest_pipe = Pipe(pathlib.Path(tmp) / 'qmp'), Pipe(pathlib.Path(tmp) / 'qtest')
            pipes.extend((qmp_pipe, qtest_pipe))
            cmd += ['-qmp', 'pipe:' + qmp_pipe.path, '-qtest', 'pipe:' + qtest_pipe.path,
                    '-qtest-log', os.devnull]
            process = subprocess.Popen(cmd)
            qmp = QMP(qmp_pipe)
            time.sleep(1)
            if process.poll() is not None:
                raise DebugError('QEMU exited before diagnostic console setup')
            enable_console(qmp, qtest_pipe)
            return process.wait()
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
            for pipe in pipes:
                pipe.close()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (DebugError, OSError, ValueError) as exc:
        print('error: ' + str(exc), file=sys.stderr)
        sys.exit(2)
