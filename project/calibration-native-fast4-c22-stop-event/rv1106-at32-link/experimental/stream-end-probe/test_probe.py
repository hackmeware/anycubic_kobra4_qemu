"""Offline tests only: no network, firmware, emulator, or generated ELF execution."""
import hashlib
import pathlib
import random
import subprocess
import sys
import tempfile
import unittest

import make_probe as probe
from arm_fixture import Machine, WouldBlock

ROOT = pathlib.Path(__file__).resolve().parent
PACKET = probe.PREFACE + probe.frame(4, 0, 0) + probe.frame(1, 4, 1, b'fixture') + probe.frame(0, 1, 1, bytes(5))
ELF = probe.build(PACKET)
END = probe.frame(1, 5, 1, b'\0\x0bgrpc-status\x010')


def run(wire, **kwargs):
    chunks = wire if isinstance(wire, list) else [wire]
    machine = Machine(ELF, chunks, **kwargs)
    try:
        machine.run()
    except WouldBlock:
        pass
    return machine


def control_frames(machine):
    assert machine.sent[:len(PACKET)] == PACKET
    data = bytes(machine.sent[len(PACKET):])
    result = []
    while data:
        length = int.from_bytes(data[:3], 'big')
        assert len(data) >= 9 + length
        result.append(data[:9 + length]); data = data[9 + length:]
    return result


class TransportTests(unittest.TestCase):
    def assert_capture(self, machine, wire, code=probe.END_STREAM):
        self.assertEqual(machine.exit_code, code)
        self.assertEqual(machine.stdout, wire)

    def test_complete_response_still_open(self):
        wire = probe.frame(4, 0, 0) + probe.frame(1, 4, 1, b'\x88') + probe.frame(0, 0, 1, bytes(5)) + END
        m = run(wire)
        self.assert_capture(m, wire)
        self.assertEqual(control_frames(m), [probe.frame(4, 1, 0), probe.frame(8, 0, 0, (5).to_bytes(4, 'big')), probe.frame(8, 0, 1, (5).to_bytes(4, 'big'))])

    def test_every_fragment_boundary(self):
        wire = probe.frame(4, 0, 0, b'\0\x04\0\0\xff\xff') + probe.frame(6, 0, 0, b'abcdefgh') + probe.frame(0, 0, 1, bytes(5)) + END
        for split in range(len(wire) + 1):
            with self.subTest(split=split):
                self.assert_capture(run([wire[:split], wire[split:]]), wire)
        self.assert_capture(run([bytes([x]) for x in wire]), wire)

    def test_random_fragmentation_and_coalescing(self):
        wire = probe.frame(4, 0, 0) + probe.frame(6, 0, 0, b'abcdefgh') + probe.frame(0, 0, 1, bytes(257)) + END
        rng = random.Random(919)
        for _ in range(50):
            chunks, pos = [], 0
            while pos < len(wire):
                count = rng.randint(1, 47); chunks.append(wire[pos:pos + count]); pos += count
            self.assert_capture(run(chunks), wire)

    def test_nonzero_status_is_captured_not_interpreted(self):
        wire = probe.frame(1, 5, 1, b'\0\x0bgrpc-status\x011\0\x0cgrpc-message\x07failure')
        self.assert_capture(run(wire), wire)
        # Transport EOF marker cannot be mistaken for an acceptance assertion.
        self.assertNotIn(b'accepted', ELF)
        self.assertNotIn(b'success', ELF)
        self.assertNotIn(b'grpc-status', ELF)

    def test_end_stream_header_requires_complete_continuation(self):
        header = probe.frame(1, 1, 1, b'\0\x0bgrpc-')
        middle = probe.frame(9, 0, 1, b'status')
        end = probe.frame(9, 4, 1, b'\x011')
        self.assert_capture(run(header + middle + end), header + middle + end)
        for partial in [header, header + middle, header + middle + end[:-1]]:
            with self.subTest(partial=partial):
                m = run(partial); self.assertIsNone(m.exit_code); self.assertEqual(m.stdout, partial)
                self.assert_capture(run(partial, eof=True), partial, probe.EOF)

    def test_terminal_frame_fully_read(self):
        for terminal in [END, probe.frame(0, 1, 1, bytes(5)), probe.frame(3, 0, 1, b'\0\0\0\x08')]:
            for length in range(len(terminal)):
                with self.subTest(terminal=terminal, length=length):
                    part = terminal[:length]
                    m = run(part); self.assertIsNone(m.exit_code); self.assertEqual(m.stdout, part)
                    self.assert_capture(run(part, eof=True), part, probe.EOF)

    def test_terminal_data_needs_no_further_socket_write(self):
        wire = probe.frame(0, 1, 1, bytes(5))
        m = run(wire)
        self.assert_capture(m, wire)
        self.assertEqual(control_frames(m), [])

    def test_reset_captures_error_code(self):
        wire = probe.frame(3, 0, 1, b'\0\0\0\x08')
        self.assert_capture(run([wire[:10], wire[10:]]), wire, probe.RESET)

    def test_connection_close_and_incomplete_frames(self):
        for wire in [b'', b'\0', bytes(8), probe.frame(1, 4, 1, b'x'), probe.frame(0, 0, 1, bytes(8))[:-3]]:
            with self.subTest(wire=wire):
                self.assert_capture(run(wire, eof=True), wire, probe.EOF)
                self.assertIsNone(run(wire).exit_code)

    def test_only_stream_one_ends_capture(self):
        wire = probe.frame(1, 5, 3, b'other') + probe.frame(3, 0, 3, bytes(4)) + END
        self.assert_capture(run(wire), wire)

    def test_no_overread_after_stream_end(self):
        suffix = probe.frame(6, 0, 0, b'abcdefgh')
        m = run(END + suffix)
        self.assert_capture(m, END)
        self.assertEqual(b''.join(m.chunks), suffix)

    def test_settings_ping_window_update_and_unknown(self):
        settings = b'\0\x01\0\0\x10\0' + b'\0\x04\0\0\xff\xff' + b'\0\x05\0\0\x40\0'
        wire = (probe.frame(4, 0, 0, settings) + probe.frame(4, 1, 0) + probe.frame(6, 0, 0, b'abcdefgh') +
                probe.frame(6, 1, 0, b'12345678') + probe.frame(8, 0, 0, b'\0\0\0\x01') +
                probe.frame(8, 0, 1, b'\x80\0\0\x01') + probe.frame(99, 255, 7, b'ignored') + END)
        m = run(wire); self.assert_capture(m, wire)
        self.assertEqual(control_frames(m), [probe.frame(4, 1, 0), probe.frame(6, 1, 0, b'abcdefgh')])

    def test_no_early_ack_for_fragmented_control_frames(self):
        for wire in [probe.frame(4, 0, 0, b'\0\x04\0\0\xff\xff'), probe.frame(6, 0, 0, b'abcdefgh')]:
            for length in range(len(wire)):
                with self.subTest(wire=wire, length=length):
                    m = run(wire[:length]); self.assertEqual(control_frames(m), [])
                    self.assertEqual(m.stdout, wire[:length]); self.assertIsNone(m.exit_code)

    def test_goaway_is_not_completion(self):
        wire = probe.frame(7, 0, 0, bytes(8))
        self.assertIsNone(run(wire).exit_code)
        self.assert_capture(run(wire, eof=True), wire, probe.EOF)
        self.assert_capture(run(wire + END), wire + END)

    def test_padding_priority_and_flow_control(self):
        wire = probe.frame(1, 0x2c, 1, b'\x02\0\0\0\0\x10header\0\0') + probe.frame(0, 8, 1, b'\x02abc\0\0') + END
        m = run(wire); self.assert_capture(m, wire)
        self.assertEqual(control_frames(m), [probe.frame(8, 0, 0, (6).to_bytes(4, 'big')), probe.frame(8, 0, 1, (6).to_bytes(4, 'big'))])

    def test_max_frame_and_larger_than_window_response(self):
        chunk = probe.frame(0, 0, 1, bytes(probe.MAX_FRAME))
        wire = chunk * 5 + END
        m = run(wire); self.assert_capture(m, wire)
        self.assertEqual(len(control_frames(m)), 10)
        self.assertTrue(all(size <= probe.MAX_FRAME for size in m.read_sizes))

    def test_oversize_header_rejected_without_allocation_or_payload_read(self):
        header = (probe.MAX_FRAME + 1).to_bytes(3, 'big') + b'\0\x01\0\0\0\x01'
        m = run(header + b'not read')
        self.assert_capture(m, header, probe.MALFORMED)
        self.assertEqual(b''.join(m.chunks), b'not read')

    def test_malformed_frames(self):
        cases = [probe.frame(4, 1, 0, b'x'), probe.frame(4, 0, 1), probe.frame(4, 0, 0, b'x'),
                 probe.frame(4, 0, 0, b'\0\x02\0\0\0\0'), probe.frame(4, 0, 0, b'\0\x04\x80\0\0\0'),
                 probe.frame(4, 0, 0, b'\0\x05\0\0\x3f\xff'), probe.frame(4, 0, 0, b'\0\x05\x01\0\0\0'),
                 probe.frame(6, 0, 0, bytes(7)), probe.frame(6, 0, 1, bytes(8)),
                 probe.frame(8, 0, 0, bytes(3)), probe.frame(8, 0, 0, bytes(4)), probe.frame(8, 0, 1, b'\x80\0\0\0'),
                 probe.frame(3, 0, 1, bytes(3)), probe.frame(3, 0, 0, bytes(4)),
                 probe.frame(0, 1, 0), probe.frame(0, 9, 1), probe.frame(0, 9, 1, b'\x01'),
                 probe.frame(1, 5, 0), probe.frame(1, 0x25, 1, bytes(4)), probe.frame(1, 0x25, 1, b'\0\0\0\x01\0'),
                 probe.frame(2, 0, 1, bytes(4)), probe.frame(2, 0, 0, bytes(5)), probe.frame(2, 0, 1, b'\0\0\0\x01\0'),
                 probe.frame(7, 0, 1, bytes(8)), probe.frame(7, 0, 0, bytes(7)),
                 probe.frame(9, 4, 1, b'no header'), probe.frame(5, 4, 1, bytes(4)),
                 probe.frame(1, 1, 1, b'x') + probe.frame(9, 4, 3, b'y'),
                 probe.frame(1, 1, 1, b'x') + probe.frame(6, 0, 0, bytes(8))]
        for wire in cases:
            with self.subTest(wire=wire):
                m = run(wire); self.assert_capture(m, wire, probe.MALFORMED)
                self.assertEqual(control_frames(m), [])

    def test_seeded_malformed_frames_never_overrun(self):
        rng = random.Random(4621)
        for _ in range(300):
            kind = rng.randrange(12)
            flags = rng.randrange(256)
            stream = rng.randrange(4)
            payload = rng.randbytes(rng.randrange(50))
            wire = probe.frame(kind, flags, stream, payload)
            m = run(wire, eof=True)
            self.assertIn(m.exit_code, [probe.END_STREAM, probe.RESET, probe.EOF, probe.MALFORMED])
            self.assertEqual(m.stdout, wire)

    def test_capture_budget(self):
        item = probe.frame(99, 0, 0, bytes(probe.MAX_FRAME))
        wire = item * (probe.MAX_CAPTURE // len(item) + 1)
        m = run(wire)
        self.assertEqual(m.exit_code, probe.CAPTURE_LIMIT)
        self.assertLessEqual(len(m.stdout), probe.MAX_CAPTURE)
        self.assertTrue(bytes(wire).startswith(m.stdout))

    def test_partial_writes_and_eintr(self):
        wire = probe.frame(4, 0, 0) + probe.frame(6, 0, 0, b'abcdefgh') + END
        m = run(wire, write_limit=1, send_limit=2, read_eintr=3, write_eintr=3, send_eintr=3)
        self.assert_capture(m, wire)
        self.assertEqual(control_frames(m), [probe.frame(4, 1, 0), probe.frame(6, 1, 0, b'abcdefgh')])

    def test_control_send_error_still_drains_queued_response(self):
        for control in [probe.frame(4, 0, 0), probe.frame(6, 0, 0, b'abcdefgh'), probe.frame(0, 0, 1, b'x')]:
            for terminal in [END, probe.frame(3, 0, 1, bytes(4)), b'']:
                with self.subTest(control=control, terminal=terminal):
                    wire = control + terminal
                    m = run(wire, eof=True, send_error=-32, send_error_after=len(PACKET))
                    self.assert_capture(m, wire, probe.IO_ERROR)
                    self.assertEqual(m.sent, PACKET)
                    self.assertEqual(m.syscalls.count(289), 2)
        wire = probe.frame(4, 0, 0) + probe.frame(6, 0, 0, b'abcdefgh') + probe.frame(0, 0, 1, b'x') + END
        m = run(wire, send_error=-32, send_error_after=len(PACKET))
        self.assert_capture(m, wire, probe.IO_ERROR)
        self.assertEqual(m.syscalls.count(289), 2)
        m = run(wire[:-1], send_error=-32, send_error_after=len(PACKET))
        self.assertIsNone(m.exit_code)
        self.assertEqual(m.stdout, wire[:-1])

    def test_partial_control_send_error_and_stdout_failure(self):
        control = probe.frame(4, 0, 0)
        wire = control + END
        m = run(wire, send_limit=1, send_error=-32, send_error_after=len(PACKET) + 4)
        self.assert_capture(m, wire, probe.IO_ERROR)
        self.assertEqual(m.sent, PACKET + probe.frame(4, 1, 0)[:4])
        m = run(END, write_limit=0)
        self.assertEqual(m.exit_code, probe.IO_ERROR)
        self.assertEqual(m.stdout, b'')

    def test_socket_connect_and_send_failures(self):
        for options in [{'socket_result': -1}, {'connect_result': -111}, {'send_error': -32}, {'send_limit': 0}]:
            with self.subTest(options=options):
                m = run(b'', **options); self.assertEqual(m.exit_code, probe.IO_ERROR); self.assertEqual(m.stdout, b'')


class GeneratorTests(unittest.TestCase):
    def invoke(self, args, candidate, path):
        script = ROOT / 'make_probe.py' if candidate else probe.LEGACY
        result = subprocess.run([sys.executable, str(script), *args, '--output', str(path)], capture_output=True)
        return result, path.read_bytes() if path.exists() else None, path.with_suffix('.commands').read_bytes() if path.with_suffix('.commands').exists() else None

    def test_default_legacy_identity_and_opt_in_request_identity(self):
        for args in [[], ['--script', 'M105\nM104 S0', '--timeout-seconds', '9'], ['--method', 'PrinterState'],
                     ['--method', 'StartPrint'], ['--method', 'StartPrint', '--file-name', 'test.gcode'],
                     ['--method', 'Homing', '--homing-axis', 'X'], ['--method', 'Homing', '--homing-axis', 'Y'],
                     ['--method', 'ExtruderPreheating', '--temperature-c', '0'],
                     ['--method', 'ExtruderPreheating', '--temperature-c', '35']]:
            with self.subTest(args=args), tempfile.TemporaryDirectory() as temp:
                directory = pathlib.Path(temp)
                legacy = self.invoke(args, False, directory / 'old')
                default = self.invoke(args, True, directory / 'default')
                self.assertEqual((default[0].returncode, default[0].stdout, default[0].stderr, default[1:]),
                                 (legacy[0].returncode, legacy[0].stdout, legacy[0].stderr, legacy[1:]))
                explicit = self.invoke(['--response-mode', 'timeout', *args], True, directory / 'explicit')
                self.assertEqual(explicit[1:], legacy[1:])
                candidate = self.invoke(['--response-mode', 'stream-end', *args], True, directory / 'candidate')
                self.assertEqual(candidate[0].returncode, 0, candidate[0].stderr)
                packet = probe.extract_packet(legacy[1])
                self.assertEqual(probe.extract_packet(candidate[1]), packet)
                m = Machine(candidate[1], [END]); self.assertEqual(m.run(), probe.END_STREAM)
                self.assertEqual(m.sent, packet)
                timeout_line = next(x for x in legacy[2].splitlines() if x.startswith(b'timeout'))
                self.assertIn(timeout_line, candidate[2])
                self.assertIn(b'GRPC_PROBE_TRANSPORT_EXIT=$?', candidate[2])

    def test_invalid_request_keeps_production_restrictions(self):
        for args in [['--method', 'Homing'], ['--method', 'Homing', '--homing-axis', 'Z'],
                     ['--method', 'ExtruderPreheating', '--temperature-c', '36'],
                     ['--method', 'PrinterState', '--temperature-c', '2'], ['--timeout-seconds', '0']]:
            with self.subTest(args=args), tempfile.TemporaryDirectory() as temp:
                directory = pathlib.Path(temp)
                result, elf, commands = self.invoke(['--response-mode', 'stream-end', *args], True, directory / 'probe')
                self.assertNotEqual(result.returncode, 0); self.assertIsNone(elf); self.assertIsNone(commands)

    def test_opt_in_help_preserves_legacy_help_without_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = pathlib.Path(temp)
            legacy = self.invoke(['--help'], False, directory / 'old')
            candidate = self.invoke(['--response-mode', 'stream-end', '--help'], True, directory / 'new')
            self.assertEqual(candidate[0].returncode, legacy[0].returncode)
            self.assertEqual(candidate[0].stdout, legacy[0].stdout)
            self.assertEqual(candidate[1:], (None, None))

    def test_production_script_matches_supported_checkpoint(self):
        expected = (ROOT / 'production-script.sha256').read_text().split()[0]
        self.assertEqual(hashlib.sha256(probe.LEGACY.read_bytes()).hexdigest(), expected)


if __name__ == '__main__':
    unittest.main()
