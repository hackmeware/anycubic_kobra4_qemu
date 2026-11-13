#!/usr/bin/env python3
"""Bounded streaming GPIO evidence. No emulator launch; never accepts truncation.

A checkpoint is a complete-line prefix at the opened file size, not a final
recording or a cross-file atomic snapshot. Final audit requires an immutable
stopped-writer receipt and reads every byte/row with bounded memory.
"""
import argparse
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import stat

HEADER = (b'# PASSIVE GPIO EDGE TRACE v1; source-local virtual timestamps; no SyncTime or signal writes\n'
          b'virtual_time_s,sequence,kind,label,pin,level\n')
MAX_ROWS = 10_000_000
MAX_BYTES = 1024**3
MAX_LINE = 256
BOARDS = ('main', 'nozzle', 'motor')
NAMES = tuple(f'{b}-gpio{p}-edges.csv' for b in BOARDS for p in 'ABCDE')
STAMP = re.compile(r'[0-9]+(?:\.[0-9]+)?(?:[Ee][+-]?[0-9]{1,3})?\Z')


def require(condition, why):
    if not condition:
        raise ValueError(why)


def bound(value, low, high, name):
    require(type(value) is int and low <= value <= high, 'Invalid ' + name)
    return value


def limits(rows, size):
    return (bound(rows, 1, MAX_ROWS, 'row budget'), bound(size, 4096, MAX_BYTES, 'byte budget'))


@contextmanager
def regular(path, maximum):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode), 'Nonregular evidence')
        require(before.st_size <= maximum, 'Evidence exceeds byte budget')
        yield stream, before


def read_json(path, maximum=65536):
    with regular(path, maximum) as (stream, before):
        data = stream.read(maximum + 1)
        require(len(data) == before.st_size, 'JSON size changed while reading')
        require(os.fstat(stream.fileno()).st_mtime_ns == before.st_mtime_ns, 'JSON changed while reading')
    return json.loads(data)


def validate_plan(plan):
    require(set(plan) == {'schema','ports','checkpoint_copies','total_gpio_disk_bytes',
                         'max_wall_seconds','max_process_rss_bytes'}, 'Unexpected/missing budget fields')
    require(plan['schema'] == 1 and type(plan['schema']) is int, 'Plan schema')
    require(set(plan['ports']) == set(NAMES), 'Plan must cover exactly all 15 source ports')
    total = 0
    for entry in plan['ports'].values():
        require(set(entry) == {'maximum_rows','maximum_bytes'}, 'Port budget fields')
        rows, size = limits(entry['maximum_rows'], entry['maximum_bytes'])
        require(rows > 16, 'Plan must leave capacity after 16 initial rows')
        total += size
    copies = bound(plan['checkpoint_copies'], 0, 32, 'checkpoint count')
    disk = bound(plan['total_gpio_disk_bytes'], 4096, 32*1024**3, 'total GPIO disk budget')
    require(total * (copies + 1) + 15 * 65536 * (copies + 1) + 65536 <= disk, 'Disk budget cannot contain all files/copies/receipts')
    bound(plan['max_wall_seconds'], 1, 7*24*3600, 'wall duration')
    bound(plan['max_process_rss_bytes'], 64*1024**2, 64*1024**3, 'process RSS')
    return plan


def checkpoint(source, target, maximum_bytes):
    """Copy all complete lines at open, in <=256-byte buffers; no size clipping."""
    limits(1, maximum_bytes)
    digest = hashlib.sha256()
    copied = 0
    tail = 0
    with regular(source, maximum_bytes) as (stream, before):
        with Path(target).open('xb') as output:
            remaining = before.st_size
            while remaining:
                line = stream.readline(min(MAX_LINE + 1, remaining))
                require(bool(line), 'Source shrank during checkpoint')
                remaining -= len(line)
                require(len(line) <= MAX_LINE, 'Oversize GPIO line')
                if not line.endswith(b'\n'):
                    require(remaining == 0, 'Broken line within checkpoint')
                    tail = len(line)
                    break
                output.write(line)
                digest.update(line)
                copied += len(line)
            output.flush()
            os.fsync(output.fileno())
        after = os.fstat(stream.fileno())
        current = os.stat(source, follow_symlinks=False)
        require(after.st_size >= before.st_size, 'Source truncated during checkpoint')
        require((current.st_dev,current.st_ino) == (before.st_dev,before.st_ino), 'Source replaced during checkpoint')
    return {'kind':'GPIO complete-line prefix at open','final':False,'atomic_cross_file':False,
            'bytes_at_open':before.st_size,'captured_bytes':copied,'bytes_after':after.st_size,
            'incomplete_line_tail_bytes_omitted':tail,'sha256':digest.hexdigest()}


def audit(source, receipt, maximum_rows, maximum_bytes, expected_labels):
    """Full stopped file validation, O(number of signals + MAX_LINE) memory."""
    limits(maximum_rows, maximum_bytes)
    require(0 < len(expected_labels) <= 16, 'Signal count')
    require(all(re.fullmatch(r'[A-Za-z0-9_]{1,64}', k) and type(v) is int and 0 <= v <= 15
                for k,v in expected_labels.items()), 'Signal identity')
    status = read_json(receipt) if not isinstance(receipt, dict) else receipt
    require(set(status) == {'schema','enabled','rows_written','edge_count','dropped_rows','bytes_written',
                           'maximum_rows','maximum_bytes','capacity_reached','last_error'}, 'Final receipt fields')
    require(type(status['schema']) is int and status['schema'] == 1, 'Receipt schema')
    for key in ('rows_written','edge_count','dropped_rows','bytes_written','maximum_rows','maximum_bytes'):
        bound(status[key], 0, 2**63-1, key)
    require(status['enabled'] is False and status['capacity_reached'] is False and
            status['dropped_rows'] == 0 and status['last_error'] == '', 'Incomplete/failed recording receipt')
    require(status['maximum_rows'] == maximum_rows and status['maximum_bytes'] == maximum_bytes, 'Receipt budget mismatch')
    digest = hashlib.sha256()
    count = edges = size = 0
    states = {}
    previous = Decimal(0)
    first = last = None
    with regular(source, maximum_bytes) as (stream, before):
        header = stream.read(len(HEADER))
        require(header == HEADER, 'Unexpected GPIO header')
        digest.update(header)
        size += len(header)
        for line in iter(lambda: stream.readline(MAX_LINE + 1), b''):
            require(len(line) <= MAX_LINE and line.endswith(b'\n'), 'Oversize/incomplete GPIO row')
            digest.update(line)
            size += len(line)
            require(size <= maximum_bytes, 'Growing/oversize GPIO file')
            fields = line[:-1].decode('ascii').split(',')
            require(len(fields) == 6, 'GPIO field count')
            stamp, seq, kind, label, pin, level = fields
            require(STAMP.fullmatch(stamp) is not None, 'Invalid timestamp')
            try: now = Decimal(stamp)
            except InvalidOperation as exc: raise ValueError('Invalid timestamp') from exc
            require(now.is_finite() and 0 <= now <= Decimal('1e12') and now >= previous, 'Time reversal/range')
            require(seq == str(count), 'Missing/reordered/duplicated sequence')
            require(label in expected_labels and pin == str(expected_labels[label]) and level in ('0','1'), 'Signal identity/level')
            if count < len(expected_labels):
                require(kind == 'initial' and label not in states, 'Missing/duplicate initial state')
            else:
                require(kind == 'edge' and label in states and states[label] != level, 'Missing/duplicate edge state')
                edges += 1
            states[label] = level
            count += 1
            require(count < maximum_rows, 'Recording reached row capacity')
            previous = now
            if first is None: first = stamp
            last = stamp
        after = os.fstat(stream.fileno())
        current = os.stat(source, follow_symlinks=False)
        require((before.st_size,before.st_mtime_ns) == (after.st_size,after.st_mtime_ns) and
                (current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns) ==
                (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns), 'Final source mutated/replaced')
    require(set(states) == set(expected_labels), 'Missing initial signals')
    require(count == status['rows_written'] and edges == status['edge_count'] and
            size == status['bytes_written'] and size == before.st_size and size < maximum_bytes, 'Final counter/byte mismatch')
    return {'complete':True,'rows':count,'edges':edges,'bytes':size,'first_source_s':first,
            'last_source_s':last,'sha256':digest.hexdigest(),'maximum_rows':maximum_rows,'maximum_bytes':maximum_bytes}


def audit_run(directory, plan):
    validate_plan(plan)
    results = {}
    for name in NAMES:
        board,port = name.split('-')[:2]
        labels = {f'{board}_P{port[-1]}{pin}':pin for pin in range(16)}
        item = plan['ports'][name]
        results[name] = audit(directory/name, directory/(name+'.status.json'),
                              item['maximum_rows'], item['maximum_bytes'], labels)
    return {'schema':1,'all_gpio_complete':True,'files':results,
            'pid_complete_claimed':False,'other_capture_streams_validated':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('plan', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit_run(args.run, read_json(args.plan)), indent=2))

if __name__ == '__main__': main()
