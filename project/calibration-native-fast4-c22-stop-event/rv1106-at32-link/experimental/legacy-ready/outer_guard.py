#!/usr/bin/env python3
"""Fixed 900-second Ready-only entrypoint into the unchanged outer guard.

This does not widen the older guard's CLI. Its subreaper, pidfd cleanup and
4 GiB RSS / 2 GiB available-memory enforcement are reused without modification.
"""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import sys

WALL_SECONDS = 900
BASE_GUARD = Path(__file__).resolve().parent.parent / 'bootstrap-boundaries/outer_guard.py'
BASE_GUARD_SHA256 = 'd2f1eb705e1b11311223c3584d578ced1963d2e11de2148306315952a81c1348'


def load_base_guard():
    if hashlib.sha256(BASE_GUARD.read_bytes()).hexdigest() != BASE_GUARD_SHA256:
        raise ValueError('The reviewed outer guard changed; no child launched')
    spec = importlib.util.spec_from_file_location('legacy_ready_base_outer_guard', BASE_GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('--wall-seconds', type=int, choices=(WALL_SECONDS,), default=WALL_SECONDS,
                        help='Only the fixed 900-second Ready-only preset is accepted')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('Command required after --')
    return load_base_guard().supervise(command, args.record, WALL_SECONDS)


if __name__ == '__main__':
    raise SystemExit(main())
