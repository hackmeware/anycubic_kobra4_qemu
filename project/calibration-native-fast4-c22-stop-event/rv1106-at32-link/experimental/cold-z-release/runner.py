#!/usr/bin/env python3
"""Fixed bounded supervision for the fixed virtual homing and cold Z release observer.

Use this experiment's outer_guard.py. Host progress is evidence only, not a
resumable snapshot. The fixed 45-second shared-time threshold actively requests stop when sampled
by the unchanged supervisor, not as a strict pre-step cap; no timing/stepping semantics are changed here.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import threading
import time
import types

HERE = Path(__file__).resolve().parent
EXPECTED_PROFILE = HERE.parents[2]
OBSERVER_RELATIVE = 'rv1106-at32-link/experimental/cold-z-release/observer.py'
# Intentionally unlaunchable until the final observer is reviewed and pinned.
OBSERVER_SHA256 = '49db7f0e3a6e78fdc1adc7adf9648f0eac4ea68b314129d8d841ca8fa405e061'
PROTOCOL_RELATIVE = 'rv1106-at32-link/experimental/cold-z-release/cold_protocol.py'
PROTOCOL_SHA256 = 'a0ff7f052b28a396f11f2019c52d61acae20a5208318304c29dd2a87ba21a157'
MANIFEST_RELATIVE = 'rv1106-at32-link/experimental/cold-z-release/execution-manifest.json'
MANIFEST_SHA256 = 'd427910d5c002d7d4ea8da1bcf82e44b9e4b617fb9da977020c11453c4b092de'
MANIFEST_SCOPE = 'cold-release-execution-source-closure'
READY_REFERENCE_RELATIVE = 'rv1106-at32-link/experimental/sensor30-observation/evidence/ready-baseline.console.txt'
LAUNCHER_RELATIVE = 'rv1106-at32-link/experimental/cold-z-release/run_cold_release_fixture.sh'
PINNED_CONTROLS = {
    LAUNCHER_RELATIVE: '4b0c413b97d55362ad596e273fe11f779d60139c2d170bcf223f958e288d01d4',
    'rv1106-at32-link/experimental/cold-z-release/cold_physical.py': 'c6cfb84edfaf27c515f151a38c3eca24a69bfcce6b09ae8a6420ac1a1e9e70b8',
    'rv1106-at32-link/scripts/bounded_native_supervisor.py': '48abc81b323217ecf6811dec29c865b6b9bf87f470f7c4ec24bae3bd597f4ca7',
    'rv1106-at32-link/scripts/run_native_ready_observation.py': '59d018994fe46282ade656f6e144ece30caf718e427c1bd99ad4f0d7f409b510',
    'rv1106-at32-link/scripts/run_native_event_fixture.sh': 'ff22ddc0992c618c67c88667f3c7acdb20e572e0eaac13679811c10ba8344913',
    'rv1106-at32-link/scripts/run_link.py': '4735e76d68e943ecd1fa92a0ad2cce253fc4146f3fc1335c00f08b6f311c21d9',
    'rv1106-at32-link/experimental/bootstrap-boundaries/outer_guard.py': 'd2f1eb705e1b11311223c3584d578ced1963d2e11de2148306315952a81c1348',
    'rv1106-at32-link/experimental/clock-snapshot/runtime/run-baseline': 'b5c7bb59304db4082d491b9008392c3e5f2af98bab38cb1901831d9e36ecbcd1',
}
TOTAL_SECONDS = 4780
GRACE_SECONDS = 8
TERM_SECONDS = 2
KILL_SECONDS = 2
ACTIVE_SECONDS = TOTAL_SECONDS - GRACE_SECONDS - TERM_SECONDS - KILL_SECONDS
OUTER_SECONDS = 4800
VIRTUAL_THRESHOLD_NS = 45_000_000_000
PROGRESS_INTERVAL_SECONDS = 1.0
RSS_LIMIT_BYTES = 4 * 1024**3
AVAILABLE_FLOOR_BYTES = 2 * 1024**3
DISK_FLOOR_BYTES = 512 * 1024**2
TAIL_BYTES = 2048
JSON_LIMIT_BYTES = 1024 * 1024
HOST_PYTHON_DIR = '/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin'
HOST_PYTHON = str(Path(HOST_PYTHON_DIR) / 'python3')
OBSERVER_WORK_SECONDS = 4760
SHARED_STOP_SECONDS = 45
RELEASE_GCODE = "G91\nG1 Z1 F60\nM400\nG90"
LOG_NAMES = ('launcher.log', 'renode.log', 'qemu.log', 'console.bin')
Z_PARAMETERS = ('BED_RELATIVE_MM', 'OPPOSITE_STOP_RELATIVE_MM', 'BED_SIDE',
                'STIFFNESS_N_PER_MM', 'DAMPING_NS_PER_MM', 'BASELINE_COUNTS',
                'COUNTS_PER_N', 'SIGNAL_POLARITY', 'HISTORY_CAPACITY', 'QUERY_TRACE_ROWS')


def safe_json(path):
    """Never follow a link or block on a FIFO while reading optional evidence."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Evidence is not a regular file')
        data = stream.read(JSON_LIMIT_BYTES + 1)
    if len(data) > JSON_LIMIT_BYTES:
        raise ValueError('Evidence exceeds the JSON size limit')
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError('Evidence is not a JSON object')
    return value


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def fresh(path):
    return not path.exists() and not path.is_symlink()


def available_memory():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1]) * 1024
    raise RuntimeError('MemAvailable is unavailable')


def group_members(pgid):
    """Observe only; the outer subreaper owns orphan and detached-child tracking."""
    if type(pgid) is not int or pgid <= 0:
        return []
    rows = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            raw = (entry / 'stat').read_text()
            fields = raw[raw.rfind(')') + 2:].split()
            if int(fields[2]) == pgid:
                with (entry / 'cmdline').open('rb') as command:
                    arguments = command.read(4096).split(b'\0')
                rows.append({'pid': int(entry.name), 'ppid': int(fields[1]),
                             'pgid': int(fields[2]), 'session': int(fields[3]),
                             'state': fields[0], 'starttime_ticks': int(fields[19]),
                             'qemu_baseline_process': any(arg.endswith(b'/qemu-baseline') for arg in arguments[:4]),
                             'rss_bytes': int(fields[21]) * os.sysconf('SC_PAGE_SIZE')})
        except (OSError, ValueError, IndexError):
            # Processes may disappear between the directory scan and stat read.
            continue
    return sorted(rows, key=lambda row: row['pid'])


def log_tail(path, previous=None):
    result = {'status': 'missing', 'size_bytes': None, 'tail': ''}
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('Log is not a regular file')
            stream.seek(max(0, info.st_size - TAIL_BYTES))
            data = stream.read(TAIL_BYTES)
        identity = [info.st_dev, info.st_ino]
        result.update(status='observed', size_bytes=info.st_size,
                      identity=identity, mtime_ns=info.st_mtime_ns,
                      tail=data.decode('utf-8', errors='replace'),
                      tail_is_complete_file=info.st_size <= TAIL_BYTES,
                      truncated_since_previous=False, replaced_since_previous=False)
        if previous and previous.get('status') == 'observed':
            replaced = identity != previous.get('identity')
            result['replaced_since_previous'] = replaced
            result['truncated_since_previous'] = not replaced and info.st_size < previous['size_bytes']
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        result.update(status='unavailable', error=str(exc))
    return result


def virtual_progress(path, step_ack=False):
    """A missing bootstrap export means unknown time, never zero or host time."""
    try:
        sample = safe_json(path)
        now = sample.get('virtual_time_ns')
        if type(now) is not int or now < 0:
            raise ValueError('Invalid virtual_time_ns')
        if step_ack and (type(sample.get('step_id')) is not int or sample['step_id'] < 0
                         or type(sample.get('schema')) is not int or sample['schema'] != 1
                         or sample.get('source') != 'renode-shared-mcu-step'
                         or sample.get('enabled') is not True or sample.get('paused') is not True
                         or sample.get('time_went_backwards') is not False
                         or not isinstance(sample.get('epoch'), str) or not sample['epoch']):
            raise ValueError('Invalid paused Renode step acknowledgement')
        answer = {'status': 'observed', 'virtual_time_ns': now,
                  'threshold_reached': now >= VIRTUAL_THRESHOLD_NS}
        for key in ('epoch', 'sequence', 'step_id', 'time_went_backwards'):
            if key in sample and isinstance(sample[key], (str, int, bool, type(None))):
                answer[key] = sample[key]
        return answer
    except FileNotFoundError:
        return {'status': 'missing', 'virtual_time_ns': None}
    except (OSError, ValueError) as exc:
        return {'status': 'unavailable', 'virtual_time_ns': None, 'error': str(exc)}


def environment(profile, pycache_prefix=None):
    return {'GLOBAL_QUANTUM_US': '1', 'NOZZLE_TMC_MODEL': 'autobaud',
            'HEADLESS_READY_ONLY': '1', 'THERMAL_PROFILE': 'none', 'Z_PROBE_PROFILE': 'synthetic-functional', 'PASSIVE_MOTOR_TRACE': '0',
            'NATIVE_NOZZLE_HEATER': '0', 'CLOCK_CLIENT': 'scalar', 'ICOUNT_SHIFT': '0',
            'RENODE_BOOTSTRAP': 'legacy', 'PYTHONDONTWRITEBYTECODE': '1',
            **({'PYTHONPYCACHEPREFIX': str(pycache_prefix)} if pycache_prefix is not None else {}),
            'QEMU_BINARY': str(profile / 'rv1106-at32-link/experimental/clock-snapshot/runtime/run-baseline')}


def plan(profile, evidence, name):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('Invalid run name')
    if Path(profile).absolute() != Path(profile).resolve() or Path(evidence).absolute() != Path(evidence).resolve():
        raise ValueError('Symlinked or noncanonical profile/evidence paths are not accepted')
    profile, evidence = profile.resolve(), evidence.resolve()
    if profile != EXPECTED_PROFILE:
        raise ValueError('Only this exact source profile is accepted')
    run = profile / 'runs' / name
    pycache_prefix = evidence / (name + '-python-cache')
    if pycache_prefix == run or run in pycache_prefix.parents:
        raise ValueError('Derived Python cache prefix must be outside the future run directory')
    paths = {key: evidence / (name + suffix) for key, suffix in (
        ('configuration', '-configuration.json'), ('progress', '-progress.jsonl'),
        ('latest', '-latest.json'), ('supervision', '-supervision.json'),
        ('audit', '-post-audit.json'))}
    command = [HOST_PYTHON, '-I', '-B', '-X', 'pycache_prefix=' + str(pycache_prefix),
               str(profile / OBSERVER_RELATIVE),
               '--run-name', name, '--seconds', str(ACTIVE_SECONDS)]
    configuration = {
        'schema_version': 1, 'profile': str(profile), 'run_name': name, 'run_directory': str(run),
        'evidence_directory': str(evidence), 'command': command,
        'python_cache_prefix': str(pycache_prefix),
        'environment': environment(profile, pycache_prefix),
        'host_environment': {'PATH': HOST_PYTHON_DIR + ':/usr/bin:/bin', 'HOME': str(profile / 'at32-runtime/home'),
                             'LANG': 'C.UTF-8'},
        'budgets_seconds': {'total': TOTAL_SECONDS, 'stop_at': ACTIVE_SECONDS,
                           'graceful': GRACE_SECONDS, 'term': TERM_SECONDS,
                           'kill': KILL_SECONDS, 'planned_outer': OUTER_SECONDS},
        'virtual_threshold_ns': VIRTUAL_THRESHOLD_NS, 'virtual_threshold_is_strict_stepping_cap': False,
        'progress_interval_seconds': PROGRESS_INTERVAL_SECONDS,
        'resource_stop_min_available_bytes': AVAILABLE_FLOOR_BYTES,
        'resource_stop_max_group_rss_bytes': RSS_LIMIT_BYTES,
        'preflight_min_free_disk_bytes': DISK_FLOOR_BYTES,
        'bootstrap_seconds': 1, 'bootstrap_unchanged': True,
        'checkpoint_kind': 'Host progress evidence only; not a resumable VM snapshot',
        'observer_work_host_seconds': OBSERVER_WORK_SECONDS,
        'shared_stop_seconds': SHARED_STOP_SECONDS,
        'release_gcode': RELEASE_GCODE,
        'request_count': 10,
        'source_hash_pin_pending': any(pin is None for pin in (OBSERVER_SHA256, PROTOCOL_SHA256, MANIFEST_SHA256, *PINNED_CONTROLS.values())),
        'outer_guard_required': True, 'orphan_tracking_owner': 'outer_guard.py',
        'progress_writes_monitor_commands': False, 'progress_adds_virtual_steps': False,
        'firmware_changes': False, 'heating_commands': False, 'homing_commands': True,
        'print_commands': False, 'motion_commands': True, 'zero_commands': False, 'physical_completion_proven': False,
        'rss_note': 'Sampled summed process-group RSS may double-count shared mappings and miss peaks.',
        'artifacts': {key: str(path) for key, path in paths.items()},
    }
    return configuration, run, paths


def validate_configuration(configuration, run, paths):
    expected, expected_run, expected_paths = plan(Path(configuration['profile']),
        Path(configuration['evidence_directory']), configuration['run_name'])
    # Runtime evidence is added only after this equality check. No command,
    # environment, budget or destination substitutions are accepted.
    if configuration != expected or run != expected_run or paths != expected_paths:
        raise ValueError('Configuration differs from the fixed cold_release plan')


def verify_source(path, expected):
    if expected is None or not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('Source hash pin pending review; no child launched: ' + str(path))
    if path.is_symlink() or not path.is_file():
        raise ValueError('Required source is missing or symlinked: ' + str(path))
    checksum = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Required source is not a regular file: ' + str(path))
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    digest = checksum.hexdigest()
    if digest != expected:
        raise ValueError('Source hash mismatch; no child launched: ' + str(path))
    return digest


def verified_source_module(path, expected, module_name):
    """Compile exactly the verified source bytes; never consult bytecode caches."""
    if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('Source hash pin pending review; no child launched: ' + str(path))
    if path.is_symlink() or not path.is_file():
        raise ValueError('Required source is missing or symlinked: ' + str(path))
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Required source is not regular: ' + str(path))
        source = stream.read(JSON_LIMIT_BYTES + 1)
    if len(source) > JSON_LIMIT_BYTES or hashlib.sha256(source).hexdigest() != expected:
        raise ValueError('Source hash mismatch or source exceeds limit: ' + str(path))
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = ''
    module.__cached__ = None
    module.__loader__ = None
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


def validate_pycache_prefix(configuration, *, require_runtime):
    prefix = Path(configuration['python_cache_prefix'])
    expected = Path(configuration['evidence_directory']) / (configuration['run_name'] + '-python-cache')
    if prefix != expected or prefix.absolute() != prefix.resolve():
        raise ValueError('Unexpected Python cache prefix; no child launched')
    if not fresh(prefix):
        raise ValueError('Fresh absent Python cache prefix required; no child launched')
    if (require_runtime and (sys.pycache_prefix != str(prefix)
                             or not sys.flags.dont_write_bytecode or not sys.flags.isolated)):
        raise ValueError('Python runtime cache isolation differs from fixed launch; no child launched')
    if 'PYTHONPYCACHEPREFIX' in os.environ and os.environ['PYTHONPYCACHEPREFIX'] != str(prefix):
        raise ValueError('Unexpected PYTHONPYCACHEPREFIX override; no child launched')


def verify_manifest(profile):
    """Verify reviewed transitive identities without loading code or changing state.

    The manifest excludes the two pin-owning wrappers to avoid circular hashes.
    Outer guard pins runner; runner pins this manifest and its direct modules.
    This proves file identity only, never hardware accuracy or safe calibration.
    """
    manifest = profile / MANIFEST_RELATIVE
    digest = verify_source(manifest, MANIFEST_SHA256)
    document = safe_json(manifest)
    if (type(document.get('schema_version')) is not int or document['schema_version'] != 1
            or document.get('scope') != MANIFEST_SCOPE):
        raise ValueError('Invalid execution manifest schema/scope')
    files = document.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Execution manifest has no source closure')
    mandatory = set(PINNED_CONTROLS) | {OBSERVER_RELATIVE, PROTOCOL_RELATIVE, READY_REFERENCE_RELATIVE}
    if not mandatory <= set(files):
        raise ValueError('Execution manifest omits required controlling sources')
    start = time.monotonic()
    for relative, expected in files.items():
        if not isinstance(relative, str) or not relative or str(Path(relative)) != relative:
            raise ValueError('Invalid execution manifest relative path')
        local = Path(relative)
        path = profile / local
        if local.is_absolute() or '..' in local.parts or path.resolve() != path.absolute():
            raise ValueError('Execution manifest path escapes or follows a symlink')
        if relative in (MANIFEST_RELATIVE, 'rv1106-at32-link/experimental/cold-z-release/runner.py',
                        'rv1106-at32-link/experimental/cold-z-release/outer_guard.py'):
            raise ValueError('Execution manifest contains a circular pin-owning source')
        verify_source(path, expected)
    symlinks = document.get('symlinks', {})
    if not isinstance(symlinks, dict) or set(symlinks) & set(files):
        raise ValueError('Invalid or overlapping execution manifest symlinks')
    absent = document.get('absent_targets', [])
    if not isinstance(absent, list) or any(not isinstance(value, str) for value in absent):
        raise ValueError('Invalid execution manifest absent targets')
    if len(set(absent)) != len(absent) or set(absent) & (set(files) | set(symlinks)):
        raise ValueError('Duplicate or overlapping execution manifest absent targets')
    for relative in absent:
        local = Path(relative)
        path = profile / local
        if (not relative or str(local) != relative or local.is_absolute()
                or '..' in local.parts or path.resolve() != path.absolute()):
            raise ValueError('Noncanonical or outside execution manifest absent target')
        if path.exists() or path.is_symlink():
            raise ValueError('Execution manifest absent target is newly present or symlinked')
    referenced_absent = set()
    for relative, target in symlinks.items():
        if (not isinstance(relative, str) or not relative or str(Path(relative)) != relative
                or Path(relative).is_absolute() or '..' in Path(relative).parts
                or not isinstance(target, str) or not target or Path(target).is_absolute()):
            raise ValueError('Invalid execution manifest symlink path/target')
        path = profile / relative
        if (not path.is_symlink() or path.parent.resolve() != path.parent.absolute()
                or os.readlink(path) != target):
            raise ValueError('Execution manifest symlink changed or absent')
        resolved = path.resolve()
        try:
            target_relative = str(resolved.relative_to(profile))
        except ValueError as exc:
            raise ValueError('Execution manifest symlink target is outside profile') from exc
        if target_relative in absent:
            if resolved.exists() or resolved.is_symlink():
                raise ValueError('Execution manifest absent symlink target is newly present')
            referenced_absent.add(target_relative)
        elif target_relative not in files or not resolved.is_file():
            raise ValueError('Execution manifest symlink target is not a listed regular file or absent target')
    if referenced_absent != set(absent):
        raise ValueError('Orphan execution manifest absent target has no symlink reference')
    return {'sha256': digest, 'entry_count': len(files), 'symlink_count': len(symlinks),
            'absent_target_count': len(absent),
            'verification_elapsed_host_seconds': time.monotonic() - start,
            'scope': MANIFEST_SCOPE, 'physical_calibration_proven': False}


def validate_environment(profile, pycache_prefix=None):
    if any(key in os.environ for key in ('BASH_ENV', 'ENV', 'PYTHONPATH', 'PYTHONHOME',
                                         'LD_PRELOAD', 'LD_LIBRARY_PATH', 'LD_AUDIT')):
        raise ValueError('Unexpected shell, Python or loader override; use the documented clean launch')
    expected = environment(profile, pycache_prefix)
    if pycache_prefix is None and 'PYTHONPYCACHEPREFIX' in os.environ:
        raise ValueError('Unexpected PYTHONPYCACHEPREFIX without derived prefix')
    for key, value in expected.items():
        if key in os.environ and os.environ[key] != value:
            raise ValueError('Unexpected environment override: ' + key)
    if any(key.startswith('Z_') and key != 'Z_PROBE_PROFILE' for key in os.environ):
        raise ValueError('Unexpected Z profile parameters; no child launched')
    forbidden = ('RUN_SECONDS', 'PASSIVE_CONTACT_TRACE',
                 'PASSIVE_NOZZLE_TRACE', 'PASSIVE_HOMING_GPIO', 'PASSIVE_TMC_TRACE',
                 'RECOVERED_NOZZLE_NTC', 'ASSUMED_XY_DIAG_CABLE', 'MOTOR_ENABLE_WIRING')
    if any(key in os.environ for key in forbidden):
        raise ValueError('Unexpected launcher environment override; no child launched')


def preflight(configuration, run, paths):
    validate_configuration(configuration, run, paths)
    profile = Path(configuration['profile'])
    evidence = Path(configuration['evidence_directory'])
    if not evidence.is_dir() or not (profile / 'runs').is_dir():
        raise ValueError('Existing evidence and profile/runs directories are required')
    if sys.version_info[:2] != (3, 12) or Path(sys.executable).resolve() != Path(HOST_PYTHON).resolve():
        raise ValueError('Use the exact Python 3.12 runtime; no child launched')
    if not os.access(Path(HOST_PYTHON_DIR) / 'python3', os.X_OK):
        raise ValueError('The expected Python 3.12 runtime is unavailable; no child launched')
    experiment = profile / 'rv1106-at32-link/experimental/cold-z-release'
    if evidence == experiment or experiment in evidence.parents:
        raise ValueError('Run evidence must be outside the source experiment directory')
    candidates = [run, *paths.values(), *(path.with_name(path.name + '.tmp')
                                         for key, path in paths.items() if key != 'progress')]
    if any(not fresh(path) for path in candidates):
        raise ValueError('Fresh run and evidence paths are required')
    validate_environment(profile, configuration['python_cache_prefix'])
    validate_pycache_prefix(configuration, require_runtime=True)
    available = available_memory()
    disk = {str(directory): shutil.disk_usage(directory).free for directory in (evidence, run.parent)}
    if available < AVAILABLE_FLOOR_BYTES:
        raise ValueError('MemAvailable below 2 GiB; no child launched')
    if any(value < DISK_FLOOR_BYTES for value in disk.values()):
        raise ValueError('Free disk below 512 MiB; no child launched')
    required = (OBSERVER_RELATIVE, PROTOCOL_RELATIVE, LAUNCHER_RELATIVE,
                'rv1106-at32-link/scripts/run_native_ready_observation.py',
                'rv1106-at32-link/scripts/bounded_native_supervisor.py',
                'rv1106-at32-link/scripts/run_native_event_fixture.sh',
                'rv1106-at32-link/scripts/run_link.py',
                'rv1106-at32-link/experimental/bootstrap-boundaries/outer_guard.py',
                'rv1106-at32-link/experimental/cold-z-release/outer_guard.py',
                'rv1106-at32-link/experimental/clock-snapshot/runtime/run-baseline',
                'rv1106-at32-link/experimental/clock-snapshot/runtime/bin/qemu-baseline',
                'at32-runtime/renode_1.17.0-portable/renode',
                'rv1106-linux-display-128diag/linux-test.elf',
                'inputs/mcu.bin', 'inputs/motor.bin', 'inputs/nozzle.bin', 'inputs/offline-emmc.img')
    for relative in required:
        path = profile / relative
        if not path.is_file() or path.stat().st_size == 0 or not os.access(path, os.R_OK):
            raise ValueError('Missing or unreadable required input: ' + str(path))
    configuration['preflight'] = {'available_memory_bytes': available, 'free_disk_bytes': disk}
    configuration['controlling_source_sha256'] = {
        relative: verify_source(profile / relative, digest)
        for relative, digest in PINNED_CONTROLS.items()}
    configuration['observer_sha256'] = verify_source(profile / OBSERVER_RELATIVE, OBSERVER_SHA256)
    configuration['protocol_sha256'] = verify_source(profile / PROTOCOL_RELATIVE, PROTOCOL_SHA256)
    configuration['execution_manifest'] = verify_manifest(profile)
    configuration['runner_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def load_supervisor(profile):
    source = profile / 'rv1106-at32-link/scripts/bounded_native_supervisor.py'
    # Compile exact hash-verified bytes. No monkeypatching: all Ready validation
    # and cleanup gates remain unchanged, and no cached helper may substitute.
    return verified_source_module(source,
        PINNED_CONTROLS['rv1106-at32-link/scripts/bounded_native_supervisor.py'],
        'cold_release_bounded_supervisor')


def read_cold_release_report(path):
    report = safe_json(path)
    observer_path = EXPECTED_PROFILE / OBSERVER_RELATIVE
    verify_source(observer_path, OBSERVER_SHA256)
    verify_source(EXPECTED_PROFILE / PROTOCOL_RELATIVE, PROTOCOL_SHA256)
    observer = verified_source_module(observer_path, OBSERVER_SHA256, 'cold_release_final_report_validation')
    observer.validate_final_report(report)
    observer.validate_artifacts(path.parent, report)
    # Explicit wrapper gate: one genuine Ready request alone never passes.
    if (report.get('phase') != 'verified_cold_release' or type(report.get('request_count')) is not int
            or report['request_count'] != 10 or report.get('final_export_requested') is not True
            or type(report.get('launcher_exit_code')) is not int or report['launcher_exit_code'] != 0
            or report.get('virtual_release_proven') is not True
            or report.get('physical_completion_proven') is not False
            or report.get('calibration_completed') is not False
            or report.get('release_gcode') != RELEASE_GCODE):
        raise ValueError('Cold release report is not an exact completed ten-request physical release observation')
    return report


class Recorder:
    """One host sampler and one append-only evidence writer; bounded retained state."""
    def __init__(self, run, paths):
        self.run, self.paths = run, paths
        self.stream = paths['progress'].open('x')
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, name='cold_release-host-progress', daemon=True)
        self.started = time.monotonic()
        self.count = 0
        self.last_sample_time = None
        self.maximum_interval = 0.0
        self.maximum_rss = 0
        self.minimum_available = None
        self.errors = []
        self.resource_guard_triggered = False
        self.pending_stop = False
        self.previous_logs = {}
        self.last_row = None
        self.milestones = {}
        self.maximum_observed_virtual_time_ns = None

    def request_stop(self):
        try:
            with (self.run / 'stop-request').open('x') as stream:
                stream.write('Host progress sampler requests stop; no continuation.\n')
            return 'created'
        except FileExistsError:
            return 'already_present'
        except FileNotFoundError:
            return 'pending_run_directory'

    def sample(self, final=False):
        now = time.monotonic()
        gap = None if self.last_sample_time is None else now - self.last_sample_time
        if gap is not None:
            self.maximum_interval = max(self.maximum_interval, gap)
        self.last_sample_time = now
        try:
            supervision = safe_json(self.paths['supervision'])
        except FileNotFoundError:
            supervision = {}
        pgid = supervision.get('process_group_id')
        rows = group_members(pgid)
        rss, available = sum(row['rss_bytes'] for row in rows), available_memory()
        self.maximum_rss = max(self.maximum_rss, rss)
        self.minimum_available = available if self.minimum_available is None else min(self.minimum_available, available)
        if rss > RSS_LIMIT_BYTES or available < AVAILABLE_FLOOR_BYTES:
            self.resource_guard_triggered = self.pending_stop = True
        logs = {name: log_tail(self.run / name, self.previous_logs.get(name)) for name in LOG_NAMES}
        self.previous_logs = logs
        virtual = virtual_progress(self.run / 'virtual-time.json')
        step = virtual_progress(self.run / 'renode-step.json', step_ack=True)
        virtual_ns = virtual.get('virtual_time_ns')
        if virtual_ns is not None:
            self.maximum_observed_virtual_time_ns = max(self.maximum_observed_virtual_time_ns or 0, virtual_ns)
        observations = {
            'virtual_time_export_observed': virtual['status'] == 'observed',
            'legacy_full_bootstrap_ack_observed': step['status'] == 'observed' and step['virtual_time_ns'] >= 1_000_000_000,
            'post_bootstrap_step_ack_observed': step['status'] == 'observed' and step['virtual_time_ns'] > 1_000_000_000 and step['step_id'] > 0,
            'qemu_baseline_process_observed': any(member['qemu_baseline_process'] for member in rows),
            'nonempty_console_observed': (logs['console.bin'].get('size_bytes') or 0) > 0,
        }
        for name, observed in observations.items():
            if observed and name not in self.milestones:
                self.milestones[name] = {'first_elapsed_seconds': now - self.started}
        stages = supervision.get('stages')
        row = {'schema_version': 1, 'sequence': self.count, 'final_sample': final,
               'elapsed_seconds': now - self.started, 'host_unix_time_ns': time.time_ns(),
               'interval_since_previous_seconds': gap, 'process_group_id': pgid,
               'members': rows, 'group_rss_bytes': rss, 'available_memory_bytes': available,
               'last_supervisor_stage': stages[-1] if isinstance(stages, list) and stages else None,
               'virtual_time': virtual, 'renode_step': step, 'milestones': dict(self.milestones),
               'logs': logs, 'resource_guard_triggered': self.resource_guard_triggered,
               'resumable_vm_snapshot': False, 'physical_completion_proven': False}
        if self.pending_stop:
            row['stop_request'] = self.request_stop()
        self.write(row)

    def write(self, row):
        self.stream.write(json.dumps(row, allow_nan=False) + '\n')
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.count += 1
        self.last_row = row
        # Keep the latest summary small; detailed tails and process rows stay in JSONL.
        latest = {key: value for key, value in row.items() if key not in ('logs', 'members')}
        latest.update(status='active', success=False, sample_count=self.count,
                      success_scope='Validated synthetic-fixture cold release and inner cleanup only; outer guard must be checked separately',
                      outer_guard_verification_pending=True,
                      progress_file=str(self.paths['progress']),
                      checkpoint_kind='Evidence only; not a resumable VM snapshot',
                      logs={key: {k: v for k, v in value.items() if k != 'tail'}
                            for key, value in row.get('logs', {}).items()},
                      process_count=len(row.get('members', [])), sampling_errors=list(self.errors))
        atomic_json(self.paths['latest'], latest)

    def attempt_sample(self, final=False):
        try:
            self.sample(final=final)
        except Exception as exc:
            message = type(exc).__name__ + ': ' + str(exc)
            if message not in self.errors:
                self.errors.append(message)
            self.pending_stop = True
            row = {'schema_version': 1, 'sequence': self.count, 'final_sample': final,
                   'elapsed_seconds': time.monotonic() - self.started,
                   'sampling_error': message, 'resumable_vm_snapshot': False}
            try:
                row['stop_request'] = self.request_stop()
            except OSError as stop_error:
                row['stop_request_error'] = str(stop_error)
            try:
                self.write(row)
            except Exception as write_error:
                message = 'Progress persistence failed: ' + str(write_error)
                if message not in self.errors:
                    self.errors.append(message)

    def loop(self):
        while not self.stop.is_set():
            begin = time.monotonic()
            self.attempt_sample()
            self.stop.wait(max(0, PROGRESS_INTERVAL_SECONDS - (time.monotonic() - begin)))
        self.attempt_sample(final=True)

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=2)
        finished = not self.thread.is_alive()
        if finished:
            self.stream.close()
        return finished


def audit_group(pgid):
    result = {'members': group_members(pgid), 'group_absent_confirmed': False,
              'group_probe_error': None, 'scope': 'Same PID namespace and process group only; outer guard audits all descendants'}
    if type(pgid) is int and pgid > 0:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            result['group_absent_confirmed'] = True
        except OSError as exc:
            result['group_probe_error'] = str(exc)
    return result


def execute(configuration, run, paths):
    preflight(configuration, run, paths)
    with paths['configuration'].open('x') as stream:
        json.dump(configuration, stream, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    supervisor = load_supervisor(Path(configuration['profile']))
    recorder = Recorder(run, paths)
    result = {'success': False, 'errors': ['Supervisor did not return a result']}
    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(configuration['host_environment'])
    os.environ.update(configuration['environment'])
    sampler_started = False
    try:
        recorder.thread.start()
        sampler_started = True
        result = supervisor.supervise(
            configuration['command'], stop_request=run / 'stop-request',
            native_report=run / 'ready-prerequisite.json', evidence=paths['supervision'],
            total_seconds=TOTAL_SECONDS, grace_seconds=GRACE_SECONDS,
            term_seconds=TERM_SECONDS, kill_seconds=KILL_SECONDS,
            virtual_time_file=run / 'virtual-time.json', max_virtual_time_ns=VIRTUAL_THRESHOLD_NS)
    except (Exception, KeyboardInterrupt) as exc:
        result = {'success': False, 'errors': [type(exc).__name__ + ': ' + str(exc)]}
    finally:
        if sampler_started:
            finished = recorder.finish()
        else:
            recorder.stream.close()
            finished = False
        os.environ.clear()
        os.environ.update(previous)
    audit = audit_group(result.get('process_group_id'))
    audit.update(sample_count=recorder.count, sampling_finished=finished,
                 maximum_sampled_group_rss_bytes=recorder.maximum_rss,
                 minimum_sampled_available_memory_bytes=recorder.minimum_available,
                 maximum_sample_interval_seconds=recorder.maximum_interval,
                 progress_interval_over_two_seconds=recorder.maximum_interval > 2,
                 resource_guard_triggered=recorder.resource_guard_triggered,
                 milestones=recorder.milestones,
                 maximum_observed_virtual_time_ns=recorder.maximum_observed_virtual_time_ns,
                 sampling_errors=recorder.errors, resumable_vm_snapshot=False)
    cold_release_valid = False
    cold_release_error = None
    try:
        read_cold_release_report(run / 'cold-release-observation.json')
        cold_release_valid = True
    except Exception as exc:
        cold_release_error = type(exc).__name__ + ': ' + str(exc)
    success = (cold_release_valid and result.get('success') is True and result.get('native_report_valid') is True
               and result.get('child_exit_code') == 0 and not result.get('forced_signals')
               and audit['group_absent_confirmed'] and not audit['members'] and finished
               and recorder.count > 0 and not recorder.errors and not recorder.resource_guard_triggered
               and recorder.maximum_interval <= 2)
    report = {'success': success, 'cold_release_report_valid': cold_release_valid,
              'cold_release_report_error': cold_release_error, 'virtual_release_proven': cold_release_valid,
              'physical_completion_proven': False, 'calibration_completed': False,
              'success_scope': 'Validated synthetic-fixture cold release and inner cleanup only; outer guard must be checked separately',
              'outer_guard_verification_pending': True,
              'resumable_vm_snapshot': False, 'supervision': result, 'post_audit': audit}
    atomic_json(paths['audit'], report)
    if finished:
        latest = safe_json(paths['latest'])
        latest.update(status='finished' if success else 'failed', success=success,
                      success_scope=report['success_scope'], outer_guard_verification_pending=True,
                      post_audit_file=str(paths['audit']), supervision_file=str(paths['supervision']))
        atomic_json(paths['latest'], latest)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--plan', action='store_true', help='Print fixed configuration without writes or child launches')
    args = parser.parse_args(argv)
    try:
        configuration, run, paths = plan(args.profile, args.evidence_dir, args.name)
        if args.plan:
            print(json.dumps(configuration, indent=2))
            return 0
        report = execute(configuration, run, paths)
    except (Exception, KeyboardInterrupt) as exc:
        print(json.dumps({'success': False, 'error': type(exc).__name__ + ': ' + str(exc),
                          'physical_completion_proven': False}), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report['success'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
