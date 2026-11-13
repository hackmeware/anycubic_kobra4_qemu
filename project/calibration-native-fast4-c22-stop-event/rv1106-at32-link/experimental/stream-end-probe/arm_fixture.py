"""Offline ARM subset interpreter with mocked Linux syscalls, no sockets.

This tests emitted ELF bytes, not a second Python copy of the frame parser.
It is not QEMU, Linux, or native printer-runtime verification.
"""
import collections
import struct

MASK = 0xffffffff


class WouldBlock(Exception):
    """The synthetic connection remains open without supplying more bytes."""


class Machine:
    def __init__(self, elf, chunks=(), *, eof=False, write_limit=None, send_limit=None,
                 read_eintr=0, write_eintr=0, send_eintr=0, send_error=None, send_error_after=0,
                 connect_result=0, socket_result=7):
        assert elf[:7] == b'\x7fELF\x01\x01\x01'
        _, offset, base, _, filesz, memsz, _, _ = struct.unpack_from('<8I', elf, 52)
        self.mem = bytearray(2 * 1024 * 1024)
        assert filesz == len(elf) and base + memsz < len(self.mem)
        self.mem[base:base + filesz] = elf[offset:offset + filesz]
        self.region = (base, base + memsz)
        self.reg = [0] * 16
        self.reg[13], self.reg[15] = 0x100000, struct.unpack_from('<I', elf, 24)[0]
        self.nzcv = (False, False, False, False)
        self.chunks = collections.deque(bytes(chunk) for chunk in chunks if chunk)
        self.eof = eof
        self.write_limit, self.send_limit = write_limit, send_limit
        self.read_eintr, self.write_eintr, self.send_eintr = read_eintr, write_eintr, send_eintr
        self.send_error, self.connect_result, self.socket_result = send_error, connect_result, socket_result
        self.send_error_after = send_error_after
        self.stdout, self.sent, self.read_sizes = bytearray(), bytearray(), []
        self.exit_code, self.steps, self.connected = None, 0, False
        self.syscalls = []

    def read_mem(self, address, count):
        lo, hi = self.region
        assert (lo <= address <= address + count <= hi) or (0xff000 <= address <= address + count <= 0x100000), hex(address)
        return self.mem[address:address + count]

    def write_mem(self, address, data):
        self.read_mem(address, len(data))
        self.mem[address:address + len(data)] = data

    def value(self, register, pc):
        return pc + 8 if register == 15 else self.reg[register]

    def condition(self, condition):
        n, z, c, v = self.nzcv
        return (z, not z, c, not c, n, not n, v, not v,
                c and not z, not c or z, n == v, n != v,
                not z and n == v, z or n != v, True, False)[condition]

    def syscall(self):
        r = self.reg
        number = r[7]
        self.syscalls.append(number)
        if number == 281:
            assert r[:3] == [2, 1, 0]
            r[0] = self.socket_result & MASK
        elif number == 283:
            assert r[0] == self.socket_result and r[2] == 16
            assert bytes(self.read_mem(r[1], 16)) == b'\x02\x00\xc3\x83\x7f\x00\x00\x01' + bytes(8)
            self.connected = self.connect_result == 0
            r[0] = self.connect_result & MASK
        elif number == 3:
            assert self.connected and r[0] == self.socket_result and r[2] > 0
            self.read_sizes.append(r[2])
            if self.read_eintr:
                self.read_eintr -= 1; r[0] = (-4) & MASK
            elif self.chunks:
                chunk = self.chunks.popleft()
                data, rest = chunk[:r[2]], chunk[r[2]:]
                if rest:
                    self.chunks.appendleft(rest)
                self.write_mem(r[1], data); r[0] = len(data)
            elif self.eof:
                r[0] = 0
            else:
                raise WouldBlock()
        elif number in (4, 289):
            assert r[2] > 0
            if number == 4:
                assert r[0] == 1
                if self.write_eintr:
                    self.write_eintr -= 1; r[0] = (-4) & MASK; return
                limit, output = self.write_limit, self.stdout
            else:
                assert self.connected and r[0] == self.socket_result and r[3] == 0x4000
                if self.send_error is not None and len(self.sent) >= self.send_error_after:
                    r[0] = self.send_error & MASK; return
                if self.send_eintr:
                    self.send_eintr -= 1; r[0] = (-4) & MASK; return
                limit, output = self.send_limit, self.sent
            count = min(r[2], limit) if limit is not None else r[2]
            output.extend(self.read_mem(r[1], count)); r[0] = count
        elif number == 1:
            self.exit_code = r[0]
        else:
            raise AssertionError(f'Unexpected syscall {number}')

    def run(self, max_steps=2_000_000):
        while self.exit_code is None:
            self.steps += 1
            assert self.steps <= max_steps, 'instruction limit'
            pc = self.reg[15]
            instruction = struct.unpack('<I', self.read_mem(pc, 4))[0]
            self.reg[15] = pc + 4
            if not self.condition(instruction >> 28):
                continue
            op = instruction & 0x0fffffff
            if op == 0x012fff1e:  # BX LR
                assert not self.reg[14] & 1
                self.reg[15] = self.reg[14]
            elif op >> 24 == 15:
                self.syscall()
            elif (op >> 25) & 7 == 5:
                distance = op & 0xffffff
                if distance & 0x800000:
                    distance -= 1 << 24
                if op & (1 << 24):
                    self.reg[14] = pc + 4
                self.reg[15] = (pc + 8 + 4 * distance) & MASK
            elif (op >> 25) & 7 == 4:
                # Only STMDB sp! and LDMIA sp! are generated.
                registers = [r for r in range(16) if op & (1 << r)]
                if op & (1 << 20):
                    assert op & 0xffff0000 == 0x08bd0000
                    start = self.reg[13]
                    for index, register in enumerate(registers):
                        self.reg[register] = struct.unpack('<I', self.read_mem(start + 4 * index, 4))[0]
                    self.reg[13] += 4 * len(registers)
                else:
                    assert op & 0xffff0000 == 0x092d0000
                    self.reg[13] -= 4 * len(registers)
                    for index, register in enumerate(registers):
                        self.write_mem(self.reg[13] + 4 * index, struct.pack('<I', self.reg[register]))
            elif (op >> 26) & 3 == 1:
                assert not op & (1 << 25)  # immediate offset only
                assert op & (1 << 24) and op & (1 << 23) and not op & (1 << 21)
                rn, rd = op >> 16 & 15, op >> 12 & 15
                address = self.value(rn, pc) + (op & 0xfff)
                count = 1 if op & (1 << 22) else 4
                if op & (1 << 20):
                    self.reg[rd] = int.from_bytes(self.read_mem(address, count), 'little')
                else:
                    self.write_mem(address, (self.reg[rd] & ((1 << (8 * count)) - 1)).to_bytes(count, 'little'))
            elif (op >> 26) & 3 == 0:
                opcode, rn, rd = op >> 21 & 15, op >> 16 & 15, op >> 12 & 15
                lhs = self.value(rn, pc)
                if op & (1 << 25):
                    assert not op & 0xf00
                    rhs = op & 255
                else:
                    assert not op & 16
                    rhs = self.value(op & 15, pc)
                    shift, kind = op >> 7 & 31, op >> 5 & 3
                    if kind == 0:
                        rhs = rhs << shift & MASK
                    elif kind == 1:
                        rhs >>= shift or 32
                    else:
                        raise AssertionError('unsupported shift')
                if opcode in (2, 10):
                    result = (lhs - rhs) & MASK
                elif opcode == 0:
                    result = lhs & rhs
                elif opcode == 4:
                    result = (lhs + rhs) & MASK
                elif opcode == 12:
                    result = lhs | rhs
                elif opcode == 13:
                    result = rhs
                else:
                    raise AssertionError(f'Unexpected ALU opcode {opcode}')
                if opcode == 10:
                    assert op & (1 << 20)
                    self.nzcv = (bool(result & 0x80000000), result == 0, lhs >= rhs,
                                 bool((lhs ^ rhs) & (lhs ^ result) & 0x80000000))
                else:
                    assert not op & (1 << 20)
                    self.reg[rd] = result
            else:
                raise AssertionError(f'Unexpected instruction {instruction:08x}')
        return self.exit_code
