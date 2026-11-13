#!/usr/bin/env python3
"""Isolated, two-message GetStatus snapshot transport, never unary completion.

Derived from the unchanged stream-end ARM builder, with an independent entry
point. Import/build never executes generated code or starts native firmware.
"""
import importlib.util
import pathlib
import struct

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
spec = importlib.util.spec_from_file_location('snapshot_unary_base', ROOT / 'rv1106-at32-link/experimental/stream-end-probe/make_probe.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
Arm, frame, extract_packet = base.Arm, base.frame, base.extract_packet
MAX_FRAME, MAX_CAPTURE, MAX_MESSAGE = base.MAX_FRAME, base.MAX_CAPTURE, 65536
RESET, EOF, MALFORMED, IO_ERROR, CAPTURE_LIMIT = base.RESET, base.EOF, base.MALFORMED, base.IO_ERROR, base.CAPTURE_LIMIT
UNEXPECTED_END, SNAPSHOT_CANCELLED = 7, 20

def request_packet():
    """Exact recovered read-only schema; no arbitrary method or target interface."""
    def string(value):
        return bytes([len(value)]) + value
    headers = (b'\x83\x86\x04' + string(b'/applink.AppLinkService/GetStatus') +
               b'\x01' + string(b'127.0.0.1:50051') + b'\x0f\x10' + string(b'application/grpc') +
               b'\x00' + string(b'te') + string(b'trailers'))
    return base.PREFACE + frame(4, 0, 0) + frame(1, 4, 1, headers) + frame(0, 1, 1, bytes(5))


def build_snapshot(packet):
    """GetStatus only. Exit20 means two framed messages, local CANCEL+close.

    HTTP/HPACK and protobuf semantics are separately verified by snapshot_response;
    exit20 alone is never native RPC completion or a valid temperature sample.
    """
    if packet != request_packet():
        raise ValueError('Snapshot transport is restricted to the exact empty GetStatus request')
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
    fail_unless_reg(9, 1)
    a.const(0, 'headers_seen'); a.load(0, 0); fail_unless_reg(0, 1)
    a.imm(0, 0, 8, 1); a.cmpi(0, 0); a.branch('ended', 1)
    a.branch('check_padding', link=True)
    # Parse just the gRPC envelope/count across arbitrary DATA fragments. Raw
    # frame bytes are already captured. Refuse a third/partial extra message
    # within the final frame rather than silently slicing it off.
    a.label('grpc_bytes')
    a.const(0, 'grpc_header_count'); a.load(3, 0)
    a.cmpi(3, 5); a.branch('grpc_body', 0)
    a.cmpi(2, 0); a.branch('data_flow', 0)
    a.load(0, 1, byte=True)
    a.cmpi(3, 0); a.branch('grpc_header_byte', 1)
    a.cmpi(0, 0); a.branch('malformed', 1)
    a.label('grpc_header_byte')
    a.const(12, 'grpc_header'); a.op(4, 12, 12, 3); a.store(0, 12, byte=True)
    a.imm(4, 3, 3, 1); a.const(0, 'grpc_header_count'); a.store(3, 0)
    a.imm(4, 1, 1, 1); a.imm(2, 2, 2, 1)
    a.cmpi(3, 5); a.branch('grpc_bytes', 1)
    a.push(1, 2)
    a.const(1, 'grpc_header'); a.be(3, 1, 1, 4)
    a.const(0, MAX_MESSAGE); a.cmp(3, 0); a.branch('capture_limit', 8)
    a.const(0, 'grpc_remaining'); a.store(3, 0)
    a.pop(1, 2)
    a.label('grpc_body')
    a.const(0, 'grpc_remaining'); a.load(3, 0)
    a.cmp(2, 3); a.branch('grpc_partial_body', 3)
    a.op(2, 2, 2, 3); a.op(4, 1, 1, 3)
    a.const(0, 'messages_done'); a.load(3, 0); a.imm(4, 3, 3, 1); a.store(3, 0)
    a.cmpi(3, 2); a.branch('grpc_snapshot_done', 0)
    a.const(0, 'grpc_header_count'); a.const(3, 0); a.store(3, 0)
    a.branch('grpc_bytes')
    a.label('grpc_snapshot_done')
    a.cmpi(2, 0); a.branch('malformed', 1)
    a.branch('snapshot_captured')
    a.label('grpc_partial_body')
    a.op(2, 3, 3, 2); a.store(3, 0)
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
    fail_unless_reg(9, 1)
    a.const(0, 'headers_seen'); a.load(0, 0); fail_unless_reg(0, 0)
    a.branch('check_padding', link=True)  # r2 = unpadded payload length, r1 = start
    a.imm(0, 0, 8, 32); a.cmpi(0, 0); a.branch('headers_flags', 0)
    a.cmpi(2, 5); a.branch('malformed', 3)
    a.be(3, 1, 0, 4); a.const(0, 0x7fffffff); a.op(0, 3, 3, 0)
    a.cmp(3, 9); a.branch('malformed', 0)
    a.label('headers_flags')
    a.imm(0, 0, 8, 4); a.cmpi(0, 0); a.branch('headers_complete', 1)
    a.reg(10, 9); a.const(11, 0)
    a.cmpi(9, 1); a.branch('next_frame', 1)
    a.imm(0, 11, 8, 1); a.branch('next_frame')

    a.label('continuation')
    a.imm(0, 0, 8, 4); a.cmpi(0, 0); a.branch('next_frame', 0)
    a.const(10, 0); a.cmpi(11, 0); a.branch('ended', 1)
    a.const(0, 'headers_seen'); a.const(3, 1); a.store(3, 0)
    a.branch('next_frame')

    a.label('headers_complete')
    a.const(0, 'headers_seen'); a.const(3, 1); a.store(3, 0)
    a.branch('maybe_end')

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
    a.branch('malformed')  # Refuse a closing/failed stream as a fresh snapshot.

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

    a.label('snapshot_captured')
    a.const(0, 'control_failed'); a.load(0, 0); a.cmpi(0, 0); a.branch('io_error', 1)
    # RFC7540 RST_STREAM(CANCEL=8), then explicit local shutdown+close. These
    # syscalls cannot prove that the remote application already observed cancel.
    send('cancel', 13, control=False)
    a.reg(0, 4); a.const(1, 2); a.syscall(293)
    a.cmpi(0, 0); a.branch('io_error', 1)
    a.reg(0, 4); a.syscall(6)
    a.cmpi(0, 0); a.branch('io_error', 1)
    a.const(0, SNAPSHOT_CANCELLED); a.syscall(1)

    for label, code in [('ended', UNEXPECTED_END), ('reset_exit', RESET), ('eof', EOF),
                        ('malformed', MALFORMED), ('io_error', IO_ERROR), ('capture_limit', CAPTURE_LIMIT)]:
        a.label(label)
        if code in (UNEXPECTED_END, RESET, EOF):
            a.const(1, 'control_failed'); a.load(1, 1)
            a.cmpi(1, 0); a.branch('io_error', 1)
        a.const(0, code); a.syscall(1)
    address = struct.pack('<H', 2) + (50051).to_bytes(2, 'big') + bytes([127, 0, 0, 1]) + bytes(8)
    # Keep all word-loaded mutable fields first and aligned.
    return a.finish([('budget', struct.pack('<I', MAX_CAPTURE)),
                     ('control_failed', bytes(4)), ('headers_seen', bytes(4)),
                     ('grpc_header_count', bytes(4)), ('grpc_remaining', bytes(4)), ('messages_done', bytes(4)),
                     ('addr', address),
                     ('packet', packet), ('ack', frame(4, 1, 0)),
                     ('pong', frame(6, 1, 0, bytes(8))),
                     ('window', frame(8, 0, 0, bytes(4))), ('cancel', frame(3, 0, 1, (8).to_bytes(4, 'big'))),
                     ('grpc_header', bytes(5)), ('header', bytes(9))], MAX_FRAME)



def snapshot_protobufs(data, decode_headers):
    """Validate exactly two captured streaming messages, NOT terminal RPC status.

    Must be paired with emitted client's exit20: successful local RST_STREAM
    CANCEL, shutdown and close. This parser cannot prove remote cancellation.
    """
    if not isinstance(data, bytes) or len(data) > MAX_CAPTURE:
        raise ValueError('Invalid or oversized snapshot capture')
    position, continuation, headers_done = 0, False, False
    block, body, expected, messages = bytearray(), bytearray(), None, []
    while position < len(data):
        if len(messages) == 2:
            raise ValueError('Additional frame after two complete snapshot messages')
        if len(data) - position < 9:
            raise ValueError('Truncated snapshot frame')
        size = int.from_bytes(data[position:position + 3], 'big')
        kind, flags = data[position + 3:position + 5]
        stream = int.from_bytes(data[position + 5:position + 9], 'big') & 0x7fffffff
        position += 9
        payload = data[position:position + size]
        position += size
        if size > MAX_FRAME or len(payload) != size:
            raise ValueError('Oversized/truncated snapshot frame payload')
        if continuation and (kind != 9 or stream != 1):
            raise ValueError('Interrupted response header block')
        if kind in (0, 1, 9):
            if stream != 1:
                raise ValueError('Unexpected snapshot response stream')
            if flags & 1:
                raise ValueError('Unexpected server END_STREAM; not a canceled snapshot')
            if kind in (0, 1) and flags & 8:
                if not payload or payload[0] >= len(payload):
                    raise ValueError('Invalid snapshot padding')
                payload = payload[1:len(payload) - payload[0]]
            if kind == 0:
                if not headers_done:
                    raise ValueError('Snapshot DATA before response headers')
                body.extend(payload)
                while len(body) >= 5:
                    if body[0] != 0:
                        raise ValueError('Compressed snapshot message unsupported')
                    expected = 5 + int.from_bytes(body[1:5], 'big')
                    if expected > MAX_MESSAGE + 5:
                        raise ValueError('Snapshot message too large')
                    if len(body) < expected:
                        break
                    messages.append(bytes(body[5:expected]))
                    del body[:expected]
                    if len(messages) == 2:
                        if body:
                            raise ValueError('Additional full/partial message after selected second sample')
                        break
            else:
                if kind == 1:
                    if headers_done or continuation:
                        raise ValueError('Duplicate response headers or server trailers')
                    if flags & 32:
                        if len(payload) < 5 or int.from_bytes(payload[:4], 'big') & 0x7fffffff == stream:
                            raise ValueError('Invalid HEADERS priority')
                        payload = payload[5:]
                elif not continuation:
                    raise ValueError('Unexpected CONTINUATION')
                block.extend(payload)
                if len(block) > MAX_MESSAGE:
                    raise ValueError('Response header block too large')
                continuation = not bool(flags & 4)
                if not continuation:
                    headers = decode_headers(bytes(block))
                    if [v for k, v in headers if k == b':status'] != [b'200']:
                        raise ValueError('Missing/non200/ambiguous snapshot HTTP status')
                    if [v for k, v in headers if k == b'content-type'] != [b'application/grpc']:
                        raise ValueError('Missing/non-gRPC/ambiguous content-type')
                    if any(k in (b'grpc-status', b'grpc-message') for k, v in headers):
                        raise ValueError('Server trailers/error cannot be a streaming snapshot')
                    if any(k.startswith(b':') and k != b':status' for k, v in headers):
                        raise ValueError('Unexpected response pseudoheader')
                    headers_done = True
        elif kind == 3:
            raise ValueError('Server reset snapshot stream')
        elif kind == 4:
            if stream or size % 6 or flags & 1 and size:
                raise ValueError('Malformed SETTINGS')
            for offset in range(0, size, 6):
                key = int.from_bytes(payload[offset:offset + 2], 'big')
                value = int.from_bytes(payload[offset + 2:offset + 6], 'big')
                if key == 2 or key == 4 and value > 0x7fffffff or key == 5 and not 16384 <= value <= 16777215:
                    raise ValueError('Invalid server SETTINGS value')
        elif kind == 6:
            if stream or size != 8:
                raise ValueError('Malformed PING')
        elif kind == 8:
            if stream not in (0, 1) or size != 4 or not int.from_bytes(payload, 'big') & 0x7fffffff:
                raise ValueError('Malformed WINDOW_UPDATE')
        elif kind == 7:
            raise ValueError('GOAWAY is not a valid fresh snapshot')
        elif kind == 2:
            if stream != 1 or size != 5 or int.from_bytes(payload[:4], 'big') & 0x7fffffff == stream:
                raise ValueError('Malformed PRIORITY')
        elif kind == 5:
            raise ValueError('Server push unsupported')
        # Unknown HTTP/2 extension frames have no snapshot semantics.
    if continuation or not headers_done or len(messages) != 2 or body:
        raise ValueError('Missing/incomplete two-message snapshot')
    return messages
