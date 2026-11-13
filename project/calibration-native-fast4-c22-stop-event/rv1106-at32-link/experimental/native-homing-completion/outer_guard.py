#!/usr/bin/env python3
"""Fixed 4800-second entrypoint for the isolated homing_completion observer.

No arbitrary command, source profile, environment or budget override is accepted.
All target-launching code remains blocked until the reviewed source pins are set.
The unchanged pinned guard owns subreaper, pidfd and descendant cleanup.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import stat
import types

HERE = Path(__file__).resolve().parent
PROFILE = HERE.parents[2]
RUNNER = HERE / 'runner.py'
OBSERVER = HERE / 'observer.py'
PROTOCOL = HERE / 'protocol.py'
MANIFEST = HERE / 'execution-manifest.json'
BASE_GUARD = HERE.parent / 'bootstrap-boundaries/outer_guard.py'
BASE_GUARD_SHA256 = 'd2f1eb705e1b11311223c3584d578ced1963d2e11de2148306315952a81c1348'
# Explicit preflight blockers, never guessed hashes. Parent freezes after review.
RUNNER_SHA256 = '8968030f1f72e8295f5e704a1a062a6a6ccaeb533964e4e62e7256edf5126bd3'
OBSERVER_SHA256 = 'f559bc324775f03e4610a7488538ef00a66191edcd86a2d42f4ad91945147e75'
PROTOCOL_SHA256 = '5dd5eb50d6e95ce8d8a3cdde13efd4b8d08f27e45a1cadc09b4500857ecab7d6'
MANIFEST_SHA256 = '31229edd5a5fe7ea41ee39afcf43fbfa9f097bbaebaa9c40630dfbf08cd2c21c'
WALL_SECONDS = 4800
HOST_PYTHON = '/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3'


def verified_import(path, digest, module_name):
    """Compile exactly pinned source bytes, ignoring all preexisting pyc files."""
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('Source hash pin pending review; no child launched: ' + str(path))
    if path.is_symlink() or not path.is_file():
        raise ValueError('Required source is missing or symlinked: ' + str(path))
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Required source is not regular: ' + str(path))
        source = stream.read(1024 * 1024 + 1)
    if len(source) > 1024 * 1024 or hashlib.sha256(source).hexdigest() != digest:
        raise ValueError('Source hash mismatch or source exceeds limit: ' + str(path))
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = ''
    module.__cached__ = None
    module.__loader__ = None
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


def verify_hash(path, digest):
    if digest is None or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('Source hash pin pending review; no child launched: ' + str(path))
    if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('Source hash mismatch or missing source; no child launched: ' + str(path))


def plan(profile, evidence, name):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('Invalid run name')
    profile, evidence = Path(profile), Path(evidence)
    if profile.absolute() != profile.resolve() or evidence.absolute() != evidence.resolve():
        raise ValueError('Symlinked or noncanonical profile/evidence paths are not accepted')
    if profile.resolve() != PROFILE:
        raise ValueError('Only this exact source profile is accepted')
    evidence = evidence.resolve()
    pycache_prefix = evidence / (name + '-python-cache')
    run = PROFILE / 'runs' / name
    if pycache_prefix == run or run in pycache_prefix.parents:
        raise ValueError('Derived Python cache prefix must be outside the future run directory')
    command = [HOST_PYTHON, '-I', '-B', '-X', 'pycache_prefix=' + str(pycache_prefix), str(RUNNER), '--profile', str(PROFILE),
               '--evidence-dir', str(evidence), '--name', name]
    return {'command': command, 'record': str(evidence / (name + '-outer.json')),
            'wall_budget_seconds': WALL_SECONDS, 'python_cache_prefix': str(pycache_prefix),
            'source_hash_pin_pending': any(pin is None for pin in (RUNNER_SHA256, OBSERVER_SHA256, PROTOCOL_SHA256, MANIFEST_SHA256)),
            'plan_only_does_not_verify_launch_readiness': True}


def execute(profile, evidence, name):
    configuration = plan(profile, evidence, name)
    if (sys.version_info[:2] != (3, 12) or Path(sys.executable).resolve() != Path(HOST_PYTHON).resolve()
            or not sys.flags.dont_write_bytecode or not sys.flags.isolated):
        raise ValueError('Use the exact Python 3.12 runtime; no child launched')
    # Validate hashes before importing any observer or runner source.
    verify_hash(OBSERVER, OBSERVER_SHA256)
    verify_hash(PROTOCOL, PROTOCOL_SHA256)
    verify_hash(MANIFEST, MANIFEST_SHA256)
    runner = verified_import(RUNNER, RUNNER_SHA256, 'homing_completion_fixed_runner')
    inner, run, paths = runner.plan(Path(profile), Path(evidence), name)
    runner.validate_configuration(inner, run, paths)
    runner.validate_environment(PROFILE, inner['python_cache_prefix'])
    runner.validate_pycache_prefix(inner, require_runtime=False)
    # The complete closure is verified by runner inside this 4800-second guard.
    # No native launch occurs until that verification has succeeded.
    if not Path(evidence).is_dir():
        raise ValueError('Existing evidence directory is required')
    record = Path(configuration['record'])
    for path in (record, record.with_suffix('.json.tmp'), record.with_suffix('.json.log')):
        if path.exists() or path.is_symlink():
            raise ValueError('Fresh outer evidence paths are required')
    guard = verified_import(BASE_GUARD, BASE_GUARD_SHA256, 'homing_completion_fixed_base_guard')
    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(inner['host_environment'])
    os.environ.update(inner['environment'])
    try:
        return guard.supervise(configuration['command'], record, WALL_SECONDS)
    finally:
        os.environ.clear()
        os.environ.update(previous)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--plan', action='store_true', help='Show fixed command without launches or evidence writes')
    args = parser.parse_args(argv)
    try:
        if args.plan:
            print(json.dumps(plan(args.profile, args.evidence_dir, args.name), indent=2))
            return 0
        return execute(args.profile, args.evidence_dir, args.name)
    except (Exception, KeyboardInterrupt) as exc:
        print(json.dumps({'success': False, 'error': type(exc).__name__ + ': ' + str(exc),
                          'physical_completion_proven': False}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
