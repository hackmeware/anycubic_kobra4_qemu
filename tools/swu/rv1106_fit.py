#!/usr/bin/env python3
"""Bounded RV1106 FIT parsing functions retained from the existing project; no launcher."""
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


