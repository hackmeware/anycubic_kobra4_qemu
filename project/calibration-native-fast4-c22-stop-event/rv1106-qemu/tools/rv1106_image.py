#!/usr/bin/env python3
"""Bounded, dependency-free RV1106 firmware inspector and explicit QEMU launcher."""
import argparse
import hashlib
import json
import lzma
import gzip
import pathlib
import shlex
import struct
import subprocess
import sys
import zlib

MAX_INPUT = 256 * 1024 * 1024
MAX_OUTPUT = 128 * 1024 * 1024
RAW_BASE = 0x200000


class ImageError(ValueError):
    pass


def need(ok, message):
    if not ok:
        raise ImageError(message)


def span(data, off, size):
    need(off >= 0 and size >= 0 and off <= len(data) and size <= len(data) - off,
         'Data range outside file/block')
    return data[off:off + size]


def strings(value):
    need(bool(value) and value.endswith(b'\0'), 'Unterminated string property')
    try:
        return value[:-1].decode('ascii').split('\0')
    except UnicodeDecodeError as exc:
        raise ImageError('Non-ASCII string property') from exc


def string(props, key, default=None):
    if key not in props:
        return default
    values = strings(props[key])
    need(len(values) == 1, 'Expected single string: ' + key)
    return values[0]


def number(props, key, default=None):
    if key not in props:
        return default
    need(len(props[key]) in (4, 8), 'Expected one/two-cell integer: ' + key)
    return int.from_bytes(props[key], 'big')


def fdt(data):
    need(len(data) >= 40, 'Truncated FDT header')
    magic, total, os, ot, om, ver, compat, cpu, ns, nb = struct.unpack('>10I', data[:40])
    need(magic == 0xd00dfeed and 17 <= ver and compat <= 17, 'Unsupported FDT header/version')
    need(40 <= total <= len(data), 'FDT totalsize outside file')
    need(os % 4 == 0 and os >= 40 and ot >= 40, 'Invalid FDT offsets')
    block = span(data[:total], os, nb)
    names = span(data[:total], ot, ns)
    need(not (os < ot + ns and ot < os + nb), 'Overlapping FDT blocks')
    nodes, stack, pos = {}, [], 0
    while pos < len(block):
        token = int.from_bytes(span(block, pos, 4), 'big'); pos += 4
        if token == 1:
            end = block.find(b'\0', pos)
            need(end >= 0, 'Unterminated FDT node')
            try:
                name = block[pos:end].decode('ascii')
            except UnicodeDecodeError as exc:
                raise ImageError('Non-ASCII FDT node') from exc
            need('/' not in name and name not in ('.', '..'), 'Invalid node name')
            need(bool(stack) or (not name and not nodes), 'Invalid FDT root')
            need(len(stack) < 128, 'FDT depth limit exceeded')
            stack.append(name); path = '/'.join(stack)
            need(path not in nodes, 'Duplicate FDT node')
            nodes[path] = {}; pos = (end + 4) & ~3
        elif token == 2:
            need(bool(stack), 'Unexpected FDT end-node'); stack.pop()
        elif token == 3:
            need(bool(stack), 'FDT property outside node')
            size, noff = struct.unpack('>II', span(block, pos, 8)); pos += 8
            need(noff < len(names), 'Invalid FDT property name offset')
            end = names.find(b'\0', noff)
            need(end >= 0, 'Unterminated FDT property name')
            try:
                key = names[noff:end].decode('ascii')
            except UnicodeDecodeError as exc:
                raise ImageError('Non-ASCII FDT property name') from exc
            props = nodes['/'.join(stack)]
            need(key not in props, 'Duplicate FDT property')
            props[key] = span(block, pos, size); pos = (pos + size + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            need(not stack and '' in nodes, 'Unbalanced FDT tree')
            return nodes, total
        else:
            raise ImageError('Unknown FDT token')
    raise ImageError('Missing FDT end token')


def unpack_payload(payload, compression):
    if compression == 'none':
        need(len(payload) <= MAX_OUTPUT, 'Payload output limit exceeded')
        return payload
    if compression == 'lzma':
        obj = lzma.LZMADecompressor(memlimit=MAX_OUTPUT)
        try:
            result = obj.decompress(payload, max_length=MAX_OUTPUT + 1)
        except lzma.LZMAError as exc:
            raise ImageError('Invalid LZMA payload: ' + str(exc)) from exc
    elif compression == 'gzip':
        obj = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            result = obj.decompress(payload, MAX_OUTPUT + 1)
        except zlib.error as exc:
            raise ImageError('Invalid gzip payload') from exc
    else:
        raise ImageError('Unsupported compression: ' + compression)
    need(len(result) <= MAX_OUTPUT and obj.eof, 'Truncated or oversized compressed payload')
    # Rockchip appends a little-endian decompressed-length trailer to LZMA.
    need(not obj.unused_data or (compression == 'lzma' and
         obj.unused_data == struct.pack('<I', len(result))),
         'Unexpected trailing/concatenated compressed payload data')
    return result


def digest(data, algo):
    if algo == 'crc32':
        return struct.pack('>I', zlib.crc32(data) & 0xffffffff)
    need(algo in ('sha1', 'sha256', 'sha384', 'sha512'), 'Unsupported hash: ' + algo)
    return hashlib.new(algo, data).digest()


def fit_image(data, nodes, total, name):
    need(name and '/' not in name and name not in ('.', '..'), 'Invalid FIT image reference')
    path = '/images/' + name
    need(path in nodes, 'Missing FIT image: ' + name)
    p = nodes[path]
    if 'data' in p:
        need(not any(k in p for k in ('data-position', 'data-offset', 'data-size')), 'Ambiguous inline/external FIT data')
        stored = p['data']
    else:
        need(('data-position' in p) != ('data-offset' in p), 'FIT needs exactly one external data location')
        off = number(p, 'data-position') if 'data-position' in p else ((total + 3) & ~3) + number(p, 'data-offset')
        size = number(p, 'data-size')
        need(size is not None, 'FIT external data has no size')
        stored = span(data, off, size)
    hashes = []
    for child, hp in nodes.items():
        if child.startswith(path + '/') and '/' not in child[len(path) + 1:] and child.rsplit('/', 1)[-1].startswith('hash'):
            algo = string(hp, 'algo')
            need(algo is not None and 'value' in hp, 'Incomplete FIT hash')
            need(digest(stored, algo) == hp['value'], 'FIT stored hash mismatch: ' + name)
            hashes.append(algo)
    output = unpack_payload(stored, string(p, 'compression', 'none'))
    # Rockchip's digest node describes the decompressed data, unlike standard hash nodes.
    dp = nodes.get(path + '/digest')
    if dp:
        algo = string(dp, 'algo')
        need(algo is not None and 'value' in dp, 'Incomplete Rockchip digest')
        need(digest(output, algo) == dp['value'], 'FIT decompressed digest mismatch: ' + name)
    info = dict(name=name, type=string(p, 'type'), arch=string(p, 'arch'),
                compression=string(p, 'compression', 'none'), load=number(p, 'load'),
                entry=number(p, 'entry'), stored_size=len(stored), size=len(output),
                sha256=hashlib.sha256(output).hexdigest(), verified_hashes=hashes)
    return info, output


def elf_info(data, ram):
    need(len(data) >= 52 and data[:7] == b'\x7fELF\x01\x01\x01', 'Expected little-endian ELF32')
    typ, machine, version, entry, phoff, shoff, flags, ehsize, phsize, phnum, *_ = struct.unpack('<HHIIIIIHHHHHH', data[16:52])
    need(typ == 2 and machine == 40 and version == 1 and ehsize == 52, 'Expected ARM ET_EXEC ELF32')
    need(phsize == 32 and phnum > 0, 'Invalid ELF program headers')
    span(data, phoff, phsize * phnum)
    segments = []
    for i in range(phnum):
        typ, off, va, pa, fs, ms, fl, al = struct.unpack('<8I', span(data, phoff + i * phsize, phsize))
        if typ != 1:
            continue
        need(fs <= ms and pa + ms <= ram, 'ELF segment outside DRAM or filesz > memsz')
        span(data, off, fs)
        need(not (pa < 0x1fe000 + 268 and pa + ms > 0x1fe000), 'ELF overlaps preloader ATAGS')
        need(not any(pa < s['address'] + s['size'] and pa + ms > s['address'] for s in segments), 'Overlapping ELF segments')
        segments.append(dict(address=pa, virtual_address=va, size=ms, flags=fl))
    need(segments and any(s['address'] <= (entry & ~1) < s['address'] + s['size'] and s['flags'] & 1 for s in segments), 'ELF entry not in executable physical segment')
    return dict(entry=entry, segments=segments)


def inspect(data, fmt='auto', ram=64 * 1024 * 1024):
    need(bool(data), 'Empty input')
    info = dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    if data[:4] == b'\xd0\x0d\xfe\xed':
        nodes, total = fdt(data)
        info['format'] = 'fit' if '/images' in nodes and '/configurations' in nodes else 'dtb'
        if info['format'] == 'fit':
            info['default_config'] = string(nodes['/configurations'], 'default')
            info['configs'] = {p.split('/')[-1]: {k: strings(v) for k, v in props.items() if k in ('firmware', 'kernel', 'loadables', 'fdt', 'ramdisk')} for p, props in nodes.items() if p.startswith('/configurations/') and p.count('/') == 2}
            info['images'] = []
            for p in nodes:
                if p.startswith('/images/') and p.count('/') == 2:
                    item, _ = fit_image(data, nodes, total, p.split('/')[-1]); info['images'].append(item)
            info['signatures'] = [p for p in nodes if p.split('/')[-1].startswith('signature')]
            info['signature_status'] = 'not verified; hashes detect corruption, not authenticity'
    elif data[:4] == b'\x7fELF':
        info.update(format='elf', **elf_info(data, ram))
    elif data[:4] in (b'RKFW', b'RKAF') or data[:8] == b'ANDROID!':
        info.update(format='container', warning='Not executable firmware; unpack with format-specific tooling after review')
    elif fmt == 'raw':
        need(len(data) <= ram - RAW_BASE, 'Raw image exceeds DRAM')
        info.update(format='raw', load=RAW_BASE, entry=RAW_BASE, warning='Explicit raw interpretation; identity not verified')
    else:
        info.update(format='unknown', warning='No safe format identification; use --format raw only for reviewed U-Boot binaries')
    need(fmt in ('auto', 'raw') or fmt == info['format'], 'Input does not match requested format')
    return info


def normalize(data, fmt, config, ram):
    info = inspect(data, fmt, ram)
    if info['format'] in ('raw', 'elf'):
        return info, data
    need(info['format'] == 'fit', 'Refusing to run/extract unknown, DTB, or update container as firmware')
    nodes, total = fdt(data)
    config = config or info['default_config']
    need(config in info['configs'], 'Select a valid FIT configuration with --config')
    refs = info['configs'][config]
    primary = refs.get('firmware', refs.get('loadables', []))
    need(len(primary) == 1 and 'kernel' not in refs and 'ramdisk' not in refs,
         'Only a single U-Boot firmware/loadable configuration is supported')
    need(not ('firmware' in refs and 'loadables' in refs and refs['loadables'] != primary), 'Additional FIT loadables are unsupported')
    image, output = fit_image(data, nodes, total, primary[0])
    need(image['arch'] == 'arm' and image['type'] in ('standalone', 'firmware'), 'Expected ARM U-Boot firmware')
    need(image['load'] == RAW_BASE and image['entry'] in (None, RAW_BASE), 'FIT load/entry must be 0x200000 for this machine')
    need(not output.startswith(b'\x7fELF'), 'ELF inside FIT is unsupported; extract/review separately')
    if 'fdt' in refs:
        need(len(refs['fdt']) == 1, 'Expected one FIT device tree')
        treeinfo, tree = fit_image(data, nodes, total, refs['fdt'][0])
        need(treeinfo['type'] == 'flat_dt' and treeinfo['load'] is None, 'Only appended U-Boot FDT is supported')
        fdt(tree)
        output += tree
    need(0 < len(output) <= ram - RAW_BASE, 'Normalized firmware outside DRAM')
    info.update(selected_config=config, normalized_size=len(output), normalized_sha256=hashlib.sha256(output).hexdigest())
    return info, output


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('inspect', 'extract', 'run'))
    p.add_argument('image', type=pathlib.Path)
    p.add_argument('--format', choices=('auto', 'raw', 'elf', 'fit'), default='auto')
    p.add_argument('--config')
    p.add_argument('--ram-mib', type=int, choices=(64, 128, 256), default=64)
    p.add_argument('--output', type=pathlib.Path, help='New output path (never overwrite)')
    p.add_argument('--qemu', default='qemu-system-arm')
    p.add_argument('--execute', action='store_true', help='Actually start QEMU; run prints command otherwise')
    p.add_argument('--timeout', type=float, default=30, help='Execution deadline in seconds')
    a = p.parse_args()
    try:
        need(0 < a.image.stat().st_size <= MAX_INPUT, 'Input is empty or exceeds 256 MiB')
        with a.image.open('rb') as f:
            data = f.read(MAX_INPUT + 1)
        need(len(data) <= MAX_INPUT, 'Input exceeds 256 MiB')
        ram = a.ram_mib * 1024 * 1024
        if a.action == 'inspect':
            need(not a.execute, '--execute requires run')
            print(json.dumps(inspect(data, a.format, ram), indent=2)); return
        info, output = normalize(data, a.format, a.config, ram)
        need(not a.execute or a.action == 'run', '--execute requires run')
        if a.action == 'extract' or info['format'] == 'fit':
            need(a.output is not None, 'Specify --output for normalized firmware')
        if a.output:
            with a.output.open('xb') as f:
                f.write(output)
            target = a.output.resolve()
        else:
            target = a.image.resolve()
        print(json.dumps(info, indent=2), flush=True)
        if a.action == 'run':
            cmd = [a.qemu, '-M', 'rv1106', '-m', str(a.ram_mib) + 'M', '-display', 'none', '-monitor', 'none', '-serial', 'stdio', '-nic', 'none', '-kernel', str(target)]
            print(shlex.join(cmd), flush=True)
            if a.execute:
                need(a.timeout > 0, 'Timeout must be positive')
                try:
                    result = subprocess.run(cmd, timeout=a.timeout)
                    sys.exit(result.returncode)
                except subprocess.TimeoutExpired:
                    print('QEMU stopped at the requested deadline.', file=sys.stderr)
                    sys.exit(124)
    except (ImageError, OSError) as exc:
        p.exit(2, 'error: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
