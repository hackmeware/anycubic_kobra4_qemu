#!/usr/bin/env python3
"""Self-contained firmware parser regression tests; no vendor files required."""
import importlib.util
import gzip
import hashlib
import lzma
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'tools/rv1106_image.py'
spec = importlib.util.spec_from_file_location('image', SCRIPT)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
u32 = lambda n: struct.pack('>I', n)
zstr = lambda s: s.encode() + b'\0'


def dtb(tree):
    names = bytearray(); offsets = {}; block = bytearray()
    def pad():
        while len(block) % 4:
            block.append(0)
    def visit(node):
        name, props, children = node
        block.extend(u32(1) + zstr(name)); pad()
        for key, value in props.items():
            if key not in offsets:
                offsets[key] = len(names); names.extend(zstr(key))
            block.extend(u32(3) + u32(len(value)) + u32(offsets[key]) + value); pad()
        for child in children:
            visit(child)
        block.extend(u32(2))
    visit(tree); block.extend(u32(9))
    total = 56 + len(block) + len(names)
    return struct.pack('>10I', 0xd00dfeed, total, 56, 56 + len(block), 40, 17, 16, 0, len(names), len(block)) + bytes(16) + block + names


def fit(mode='inline', compression='none', bad_hash=False, load=m.RAW_BASE):
    raw = b'ARM binary fixture' * 16
    payload = {'none': lambda x: x, 'gzip': gzip.compress, 'lzma': lzma.compress}[compression](raw)
    props = {'type': zstr('standalone'), 'arch': zstr('arm'), 'compression': zstr(compression), 'load': u32(load)}
    props.update({'data': payload} if mode == 'inline' else {'data-size': u32(len(payload)), 'data-' + mode: u32(4096 if mode == 'position' else 0)})
    tree = ('', {}, [('images', {}, [('uboot', props, [('hash-1', {'algo': zstr('sha256'), 'value': bytes(32) if bad_hash else hashlib.sha256(payload).digest()}, [])])]), ('configurations', {'default': zstr('conf')}, [('conf', {'loadables': zstr('uboot')}, [])])])
    blob = dtb(tree)
    if mode == 'position':
        blob += bytes(4096 - len(blob)) + payload
    elif mode == 'offset':
        blob += bytes((-len(blob)) % 4) + payload
    return blob, raw


def elf(machine=40, entry=m.RAW_BASE, address=m.RAW_BASE):
    head = b'\x7fELF\x01\x01\x01' + bytes(9)
    head += struct.pack('<HHIIIIIHHHHHH', 2, machine, 1, entry, 52, 0, 0, 52, 32, 1, 0, 0, 0)
    return head + struct.pack('<8I', 1, 84, address, address, 4, 4, 5, 4) + b'CODE'


class Images(unittest.TestCase):
    def test_inline_and_external(self):
        for mode in ('inline', 'position', 'offset'):
            blob, raw = fit(mode)
            info, result = m.normalize(blob, 'auto', None, 64 << 20)
            self.assertEqual(result, raw); self.assertEqual(info['selected_config'], 'conf')

    def test_compressed_payloads(self):
        for compression in ('gzip', 'lzma'):
            blob, raw = fit(compression=compression)
            self.assertEqual(m.normalize(blob, 'auto', 'conf', 64 << 20)[1], raw)

    def test_rockchip_trailer(self):
        raw = b'payload' * 20
        blob = lzma.compress(raw) + struct.pack('<I', len(raw))
        self.assertEqual(m.unpack_payload(blob, 'lzma'), raw)
        with self.assertRaises(m.ImageError):
            m.unpack_payload(blob[:-1] + b'\xff', 'lzma')

    def test_hash_mismatch(self):
        with self.assertRaisesRegex(m.ImageError, 'hash mismatch'):
            m.inspect(fit(bad_hash=True)[0])

    def test_config_and_load(self):
        for config, load in [('missing', m.RAW_BASE), ('conf', 0x400000)]:
            with self.assertRaises(m.ImageError):
                m.normalize(fit(load=load)[0], 'auto', config, 64 << 20)

    def test_unknown_and_update_refused(self):
        for raw in (b'unknown bytes', b'RKFW' + bytes(100), b'RKAF' + bytes(100)):
            with self.assertRaises(m.ImageError):
                m.normalize(raw, 'auto', None, 64 << 20)
        # Known containers must not become executable through --format raw.
        with self.assertRaises(m.ImageError):
            m.normalize(b'RKFW' + bytes(100), 'raw', None, 64 << 20)
        self.assertEqual(m.normalize(b'CODE', 'raw', None, 64 << 20)[1], b'CODE')

    def test_elf(self):
        self.assertEqual(m.inspect(elf())['format'], 'elf')
        for bad in (elf(machine=183), elf(entry=0), elf(address=0x1fe000), elf(address=64 << 20), elf()[:-1]):
            with self.assertRaises(m.ImageError):
                m.inspect(bad)

    def test_truncations(self):
        blob, _ = fit()
        for n in range(len(blob)):
            with self.assertRaises(m.ImageError):
                m.fdt(blob[:n])

    def test_bad_offsets_and_tokens(self):
        blob, _ = fit()
        for off, value in ((4, len(blob) + 1), (8, 0xffffffff), (56, 1234)):
            bad = bytearray(blob); bad[off:off + 4] = u32(value)
            with self.assertRaises(m.ImageError):
                m.fdt(bad)

    def test_decompression_limit(self):
        previous = m.MAX_OUTPUT
        try:
            m.MAX_OUTPUT = 1024
            for comp, blob in [('gzip', gzip.compress(bytes(2048))), ('lzma', lzma.compress(bytes(2048)))]:
                with self.assertRaises(m.ImageError):
                    m.unpack_payload(blob, comp)
        finally:
            m.MAX_OUTPUT = previous

    def test_dry_run_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            source = pathlib.Path(d) / 'firmware.img'; out = pathlib.Path(d) / 'normalized.bin'
            source.write_bytes(fit()[0])
            cmd = [sys.executable, str(SCRIPT), 'run', str(source), '--output', str(out), '--qemu', '/does/not/exist']
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('-kernel', result.stdout)
            self.assertEqual(out.read_bytes(), fit()[1])
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 2)

    def test_plain_dtb_not_firmware(self):
        blob = dtb(('', {}, []))
        self.assertEqual(m.inspect(blob)['format'], 'dtb')
        with self.assertRaises(m.ImageError):
            m.normalize(blob, 'auto', None, 64 << 20)


if __name__ == '__main__':
    unittest.main()
