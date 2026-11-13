#!/usr/bin/env python3
"""Isolated opt-in transport-completion probe. Never runs a generated probe.

No RPC schema changes: obtain the exact packet from the production generator.
Default mode invokes that generator without changing its output.
"""
import argparse
import pathlib
import struct
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
LEGACY = HERE.parents[1] / 'scripts' / 'make_grpc_probe.py'
PREFACE = b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'
BASE, CODE = 0x10000, 0x10100
MAX_FRAME, MAX_CAPTURE = 16384, 1024 * 1024
# These are transport outcomes, NEVER RPC acceptance or physical completion.
END_STREAM, RESET, EOF, MALFORMED, IO_ERROR, CAPTURE_LIMIT = 0, 2, 3, 4, 5, 6


class Arm:
    """Small ARM-state encoder. All branch/literal ranges are checked."""
    def __init__(self):
        self.words, self.labels, self.fixups, self.literals = [], {}, [], []

    def emit(self, value):
        self.words.append(value)

    def label(self, name):
        assert name not in self.labels
        self.labels[name] = CODE + 4 * len(self.words)

    def const(self, rd, value):
        if isinstance(value, int) and 0 <= value <= 255:
            self.emit(0xe3a00000 | rd << 12 | value)
        else:
            self.literals.append((len(self.words), rd, value))
            self.emit(0)

    def reg(self, rd, rm):
        self.emit(0xe1a00000 | rd << 12 | rm)

    def op(self, opcode, rd, rn, rm, shift=0):
        self.emit(0xe0000000 | opcode << 21 | rn << 16 | rd << 12 | shift << 7 | rm)

    def cmp(self, rn, rm):
        self.emit(0xe1500000 | rn << 16 | rm)

    def cmpi(self, rn, value):
        assert 0 <= value <= 255
        self.emit(0xe3500000 | rn << 16 | value)

    def imm(self, opcode, rd, rn, value):
        assert 0 <= value <= 255
        self.emit(0xe2000000 | opcode << 21 | rn << 16 | rd << 12 | value)

    def load(self, rd, rn, offset=0, byte=False):
        assert 0 <= offset < 4096
        self.emit((0xe5d00000 if byte else 0xe5900000) | rn << 16 | rd << 12 | offset)

    def store(self, rd, rn, offset=0, byte=False):
        assert 0 <= offset < 4096
        self.emit((0xe5c00000 if byte else 0xe5800000) | rn << 16 | rd << 12 | offset)

    def branch(self, name, cond=14, link=False):
        self.fixups.append((len(self.words), name, cond, link))
        self.emit(0)

    def push(self, *registers):
        self.emit(0xe92d0000 | sum(1 << r for r in registers))

    def pop(self, *registers):
        self.emit(0xe8bd0000 | sum(1 << r for r in registers))

    def syscall(self, number):
        self.const(7, number)
        self.emit(0xef000000)

    def be(self, rd, pointer, offset, count):
        self.const(rd, 0)
        for i in range(count):
            self.load(0, pointer, offset + i, byte=True)
            self.op(13, rd, 0, rd, shift=8)  # mov rd, rd, lsl #8
            self.op(12, rd, rd, 0)           # orr rd, rd, r0

    def finish(self, blobs, bss_size):
        data_start = CODE + 4 * (len(self.words) + len(self.literals))
        data = bytearray()
        for name, blob in blobs:
            self.labels[name] = data_start + len(data)
            data.extend(blob)
        self.labels['payload'] = data_start + len(data)
        literals = []
        for pos, rd, value in self.literals:
            location = CODE + 4 * (len(self.words) + len(literals))
            delta = location - (CODE + 4 * pos + 8)
            if not 0 <= delta < 4096:
                raise ValueError('ARM literal out of range')
            self.words[pos] = 0xe59f0000 | rd << 12 | delta
            literals.append(self.labels[value] if isinstance(value, str) else value)
        for pos, name, cond, link in self.fixups:
            displacement = (self.labels[name] - (CODE + 4 * pos + 8)) // 4
            assert -(1 << 23) <= displacement < (1 << 23)
            self.words[pos] = cond << 28 | 0x0a000000 | int(link) << 24 | displacement & 0xffffff
        body = struct.pack('<' + 'I' * (len(self.words) + len(literals)), *(self.words + literals)) + data
        size = 256 + len(body)
        header = b'\x7fELF' + bytes([1, 1, 1]) + bytes(9) + struct.pack(
            '<HHIIIIIHHHHHH', 2, 40, 1, CODE, 52, 0, 0x5000200, 52, 32, 1, 0, 0, 0)
        program = struct.pack('<8I', 1, 0, BASE, BASE, size, size + bss_size, 7, 4096)
        return header + program + bytes(256 - len(header) - len(program)) + body


def frame(kind, flags, stream, payload=b''):
    return len(payload).to_bytes(3, 'big') + bytes([kind, flags]) + stream.to_bytes(4, 'big') + payload


def build(packet):
    a = Arm()
    # Conditions: EQ=0 NE=1 CS=2 CC=3 HI=8 LS=9 GE=10 LT=11 GT=12 LE=13.
    def fail_unless_reg(register, value):
        a.cmpi(register, value)
        a.branch('malformed', 1)

    def send(label, length, *, control=True):
        done = 'send_control_done_' + str(len(a.words))
        if control:
            a.const(0, 'control_failed'); a.load(0, 0)
            a.cmpi(0, 0); a.branch(done, 1)
        a.reg(0, 4); a.const(1, label); a.const(2, length)
        a.const(3, 289); a.branch('write_all', link=True)
        a.cmpi(0, 0)
        if control:
            a.branch(done, 0)
            a.const(1, 'control_failed'); a.const(0, 1); a.store(0, 1)
            a.label(done)
        else:
            a.branch('io_error', 1)

    # Socket address is fixed guest loopback; no target or port CLI exists.
    a.const(0, 2); a.const(1, 1); a.const(2, 0); a.syscall(281)
    a.cmpi(0, 0); a.branch('io_error', 11); a.reg(4, 0)
    a.const(1, 'addr'); a.const(2, 16); a.syscall(283)
    a.cmpi(0, 0); a.branch('io_error', 11)
    send('packet', len(packet), control=False)
    a.const(10, 0); a.const(11, 0)  # continuation stream, deferred END_STREAM
    a.label('next_frame')
    a.const(1, 'header'); a.const(2, 9); a.branch('read_exact', link=True)
    a.const(1, 'header'); a.be(5, 1, 0, 3)
    a.const(0, MAX_FRAME); a.cmp(5, 0); a.branch('malformed', 8)
    a.load(6, 1, 3, byte=True); a.load(8, 1, 4, byte=True)
    a.be(9, 1, 5, 4); a.const(0, 0x7fffffff); a.op(0, 9, 9, 0)
    a.const(1, 'payload'); a.reg(2, 5); a.branch('read_exact', link=True)
    # A HEADERS block must finish before any intervening frame of any type.
    a.cmpi(10, 0); a.branch('no_continuation', 0)
    fail_unless_reg(6, 9); a.cmp(9, 10); a.branch('malformed', 1)
    a.branch('continuation')
    a.label('no_continuation')
    for kind, label in [(0, 'data'), (1, 'headers'), (2, 'priority'), (3, 'reset'),
                        (4, 'settings'), (5, 'malformed'), (6, 'ping'),
                        (7, 'goaway'), (8, 'window_update'), (9, 'malformed')]:
        a.cmpi(6, kind); a.branch(label, 0)
    a.branch('next_frame')  # HTTP/2 unknown extension frame: ignore.

    a.label('data')
    a.cmpi(9, 0); a.branch('malformed', 0)
    a.branch('check_padding', link=True)
    # A terminal DATA frame needs no replenishment. Exit before another send
    # can fail after the complete response has already been captured.
    a.cmpi(9, 1); a.branch('data_flow', 1)
    a.imm(0, 0, 8, 1); a.cmpi(0, 0); a.branch('ended', 1)
    a.label('data_flow')
    # Replenish both inbound flow-control windows by the full DATA frame size,
    # including padding. This client has no unsent request data after startup.
    a.cmpi(5, 0); a.branch('data_done', 0)
    a.const(1, 'window'); a.const(0, 0); a.store(0, 1, 5, byte=True)
    a.store(0, 1, 6, byte=True); a.store(0, 1, 7, byte=True); a.store(0, 1, 8, byte=True)
    # MAX_FRAME < 65536, so the high increment bytes remain zero.
    a.reg(0, 5); a.emit(0xe1a00420)  # mov r0, r0, lsr #8
    a.store(0, 1, 11, byte=True); a.store(5, 1, 12, byte=True)
    send('window', 13)
    a.const(1, 'window'); a.reg(0, 9)
    for offset, shift in [(5, 24), (6, 16), (7, 8), (8, 0)]:
        if shift:
            a.emit(0xe1a00020 | shift << 7 | 9)  # mov r0, r9, lsr #shift
        else:
            a.reg(0, 9)
        a.store(0, 1, offset, byte=True)
    send('window', 13)
    a.label('data_done')
    a.branch('maybe_end')

    a.label('headers')
    a.cmpi(9, 0); a.branch('malformed', 0)
    a.branch('check_padding', link=True)  # r2 = unpadded payload length, r1 = start
    a.imm(0, 0, 8, 32); a.cmpi(0, 0); a.branch('headers_flags', 0)
    a.cmpi(2, 5); a.branch('malformed', 3)
    a.be(3, 1, 0, 4); a.const(0, 0x7fffffff); a.op(0, 3, 3, 0)
    a.cmp(3, 9); a.branch('malformed', 0)
    a.label('headers_flags')
    a.imm(0, 0, 8, 4); a.cmpi(0, 0); a.branch('maybe_end', 1)
    a.reg(10, 9); a.const(11, 0)
    a.cmpi(9, 1); a.branch('next_frame', 1)
    a.imm(0, 11, 8, 1); a.branch('next_frame')

    a.label('continuation')
    a.imm(0, 0, 8, 4); a.cmpi(0, 0); a.branch('next_frame', 0)
    a.const(10, 0); a.cmpi(11, 0); a.branch('ended', 1)
    a.branch('next_frame')

    a.label('maybe_end')
    a.cmpi(9, 1); a.branch('next_frame', 1)
    a.imm(0, 0, 8, 1); a.cmpi(0, 0); a.branch('ended', 1)
    a.branch('next_frame')

    a.label('priority')
    fail_unless_reg(5, 5); a.cmpi(9, 0); a.branch('malformed', 0)
    a.const(1, 'payload'); a.be(3, 1, 0, 4)
    a.const(0, 0x7fffffff); a.op(0, 3, 3, 0); a.cmp(3, 9)
    a.branch('malformed', 0); a.branch('next_frame')

    a.label('reset')
    fail_unless_reg(5, 4); a.cmpi(9, 0); a.branch('malformed', 0)
    a.cmpi(9, 1); a.branch('reset_exit', 0); a.branch('next_frame')

    a.label('settings')
    fail_unless_reg(9, 0)
    a.imm(0, 0, 8, 1); a.cmpi(0, 0); a.branch('settings_values', 0)
    fail_unless_reg(5, 0); a.branch('next_frame')
    a.label('settings_values')
    a.reg(2, 5); a.const(1, 'payload')
    a.label('settings_loop')
    a.cmpi(2, 0); a.branch('settings_ack', 0)
    a.cmpi(2, 6); a.branch('malformed', 3)
    a.be(3, 1, 0, 2)
    a.cmpi(3, 2); a.branch('malformed', 0)  # Server MUST NOT send ENABLE_PUSH.
    a.cmpi(3, 4); a.branch('setting_window', 0)
    a.cmpi(3, 5); a.branch('setting_frame', 0)
    a.branch('setting_next')
    a.label('setting_window')
    a.load(0, 1, 2, byte=True); a.cmpi(0, 128); a.branch('malformed', 2)
    a.branch('setting_next')
    a.label('setting_frame')
    a.be(3, 1, 2, 4); a.const(0, 16384); a.cmp(3, 0); a.branch('malformed', 3)
    a.const(0, 16777215); a.cmp(3, 0); a.branch('malformed', 8)
    a.label('setting_next')
    a.imm(4, 1, 1, 6); a.imm(2, 2, 2, 6); a.branch('settings_loop')
    a.label('settings_ack'); send('ack', 9); a.branch('next_frame')

    a.label('ping')
    fail_unless_reg(9, 0); fail_unless_reg(5, 8)
    a.imm(0, 0, 8, 1); a.cmpi(0, 0); a.branch('next_frame', 1)
    # Compose the exact payload into an independent 17-byte reply buffer.
    a.const(1, 'payload'); a.const(2, 'pong')
    for i in range(8):
        a.load(0, 1, i, byte=True); a.store(0, 2, 9 + i, byte=True)
    send('pong', 17); a.branch('next_frame')

    a.label('window_update')
    fail_unless_reg(5, 4)
    a.const(1, 'payload'); a.be(3, 1, 0, 4)
    a.const(0, 0x7fffffff); a.op(0, 3, 3, 0)
    a.cmpi(3, 0); a.branch('malformed', 0); a.branch('next_frame')

    a.label('goaway')
    fail_unless_reg(9, 0); a.cmpi(5, 8); a.branch('malformed', 3)
    a.branch('next_frame')  # GOAWAY alone is not stream completion.

    a.label('check_padding')
    a.const(1, 'payload'); a.reg(2, 5)
    a.imm(0, 0, 8, 8); a.cmpi(0, 0); a.branch('padding_done', 0)
    a.cmpi(5, 0); a.branch('malformed', 0)
    a.load(0, 1, 0, byte=True); a.cmp(0, 5); a.branch('malformed', 2)
    a.imm(4, 1, 1, 1); a.op(2, 2, 5, 0); a.imm(2, 2, 2, 1)
    a.label('padding_done'); a.emit(0xe12fff1e)  # bx lr

    a.label('read_exact')
    a.push(5, 6, 8, 14)
    # Bound output volume in addition to resident frame storage.
    a.const(0, 'budget'); a.load(3, 0); a.cmp(2, 3); a.branch('capture_limit', 8)
    a.op(2, 3, 3, 2); a.store(3, 0)
    a.reg(5, 1); a.reg(6, 2)
    a.label('read_loop')
    a.cmpi(6, 0); a.branch('read_done', 0)
    a.reg(0, 4); a.reg(1, 5); a.reg(2, 6); a.syscall(3)
    a.const(12, 0xfffffffc); a.cmp(0, 12); a.branch('read_loop', 0)
    a.cmpi(0, 0); a.branch('io_error', 11); a.branch('eof', 0)
    a.reg(8, 0)
    a.const(0, 1); a.reg(1, 5); a.reg(2, 8); a.const(3, 4)
    a.branch('write_all', link=True)
    a.cmpi(0, 0); a.branch('io_error', 1)
    a.op(4, 5, 5, 8); a.op(2, 6, 6, 8); a.branch('read_loop')
    a.label('read_done'); a.pop(5, 6, 8, 15)

    a.label('write_all')
    a.push(5, 6, 8, 9, 14)
    a.reg(5, 0); a.reg(6, 1); a.reg(8, 2); a.reg(9, 3)
    a.label('write_loop')
    a.cmpi(8, 0); a.branch('write_done', 0)
    a.reg(0, 5); a.reg(1, 6); a.reg(2, 8); a.const(3, 0x4000)  # MSG_NOSIGNAL
    a.reg(7, 9); a.emit(0xef000000)
    a.const(12, 0xfffffffc); a.cmp(0, 12); a.branch('write_loop', 0)
    a.cmpi(0, 0); a.branch('write_failed', 13)
    a.op(4, 6, 6, 0); a.op(2, 8, 8, 0); a.branch('write_loop')
    a.label('write_done'); a.const(0, 0); a.pop(5, 6, 8, 9, 15)
    a.label('write_failed'); a.const(0, 1); a.pop(5, 6, 8, 9, 15)

    for label, code in [('ended', END_STREAM), ('reset_exit', RESET), ('eof', EOF),
                        ('malformed', MALFORMED), ('io_error', IO_ERROR), ('capture_limit', CAPTURE_LIMIT)]:
        a.label(label)
        if code in (END_STREAM, RESET, EOF):
            a.const(1, 'control_failed'); a.load(1, 1)
            a.cmpi(1, 0); a.branch('io_error', 1)
        a.const(0, code); a.syscall(1)
    address = struct.pack('<H', 2) + (50051).to_bytes(2, 'big') + bytes([127, 0, 0, 1]) + bytes(8)
    # Put the only word-loaded mutable field first for ARM alignment.
    return a.finish([('budget', struct.pack('<I', MAX_CAPTURE)),
                     ('control_failed', bytes(4)), ('addr', address),
                     ('packet', packet), ('ack', frame(4, 1, 0)),
                     ('pong', frame(6, 1, 0, bytes(8))),
                     ('window', frame(8, 0, 0, bytes(4))), ('header', bytes(9))], MAX_FRAME)


def extract_packet(elf):
    start = elf.index(PREFACE)
    pos = start + len(PREFACE)
    for expected_type, expected_flags, expected_stream in [(4, 0, 0), (1, 4, 1), (0, 1, 1)]:
        size = int.from_bytes(elf[pos:pos + 3], 'big')
        if (elf[pos + 3], elf[pos + 4], int.from_bytes(elf[pos + 5:pos + 9], 'big')) != (expected_type, expected_flags, expected_stream):
            raise ValueError('Unexpected production request packet layout')
        pos += 9 + size
        if pos > len(elf):
            raise ValueError('Incomplete production request packet')
    return elf[start:pos]


def commands(elf, timeout):
    lines = []
    for off in range(0, len(elf), 64):
        lines.append("printf '" + ''.join('\\%03o' % b for b in elf[off:off + 64]) + "' " + ('>' if off == 0 else '>>') + ' /tmp/grpc-probe')
    lines += ['chmod +x /tmp/grpc-probe', f'timeout -t {timeout} /tmp/grpc-probe > /tmp/grpc-probe.out',
              'GRPC_PROBE_TRANSPORT_EXIT=$?', 'od -v -b /tmp/grpc-probe.out',
              'echo GRPC_PROBE_TRANSPORT_EXIT=$GRPC_PROBE_TRANSPORT_EXIT', 'echo GRPC_PROBE_DONE']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument('--response-mode', choices=['timeout', 'stream-end'], default='timeout')
    parser.add_argument('--output', type=pathlib.Path)
    args, legacy_args = parser.parse_known_args()
    if args.output is None:
        return subprocess.call([sys.executable, str(LEGACY), *legacy_args])
    if args.response_mode == 'timeout':
        return subprocess.call([sys.executable, str(LEGACY), *legacy_args, '--output', str(args.output)])
    with tempfile.TemporaryDirectory(prefix='stream-end-probe-') as directory:
        legacy_path = pathlib.Path(directory) / 'probe'
        result = subprocess.run([sys.executable, str(LEGACY), *legacy_args, '--output', str(legacy_path)], capture_output=True)
        if result.returncode or not legacy_path.exists():
            sys.stdout.buffer.write(result.stdout); sys.stderr.buffer.write(result.stderr)
            return result.returncode
        # Preserve the production timeout and all request-validation restrictions.
        legacy_commands = legacy_path.with_suffix('.commands').read_text()
        timeout = next(line.split()[2] for line in legacy_commands.splitlines() if line.startswith('timeout -t '))
        elf = build(extract_packet(legacy_path.read_bytes()))
        args.output.write_bytes(elf)
        args.output.with_suffix('.commands').write_text(commands(elf, timeout))
        print(len(elf), 'bytes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
