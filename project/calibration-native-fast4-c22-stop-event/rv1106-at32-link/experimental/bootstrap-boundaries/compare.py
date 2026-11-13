#!/usr/bin/env python3
"""Explicit bounded experiment. Import/offline tests never launch an emulator."""
import argparse
import hashlib
import json
import os
import re
import types
from pathlib import Path
import signal
import select
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'rv1106-at32-link/scripts'))
from renode_stepper import RenodeStepper


def save(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n')
    tmp.replace(path)


def prefix_only(text):
    """Require exact legacy trailer; never silently remove unexpected commands."""
    lines = text.splitlines()
    indexes = [i for i, line in enumerate(lines) if line == 'emulation RunFor "1"']
    if len(indexes) != 1:
        raise ValueError('Expected exactly one legacy one-second bootstrap')
    i = indexes[0]
    if len(lines[i:]) != 3 or lines[i+1] != 'mach set "main"' or not lines[i+2].startswith('sysbus.timeTelemetry PublishStep '):
        raise ValueError('Unexpected legacy trailer; review generator before running')
    return lines[:i]


def load_reference():
    source = HERE/'reference'
    metadata = json.loads((source/'metadata.json').read_text())
    required = {'motor-setup.commands', 'nozzle-setup.commands', 'shared-link.resc.txt',
                'shared-profile.json', 'shared-model-manifest.json'}
    if metadata.get('schema') != 1 or set(metadata['files_sha256']) != required:
        raise ValueError('Invalid packaged reference metadata')
    contents = {}
    for name, digest in metadata['files_sha256'].items():
        data = (source/name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Packaged reference hash mismatch: '+name)
        contents[name] = data.decode()
    if json.loads(contents['shared-profile.json'])['firmware_sha256'] != metadata['firmware_sha256']:
        raise ValueError('Packaged firmware hashes differ')
    return metadata, contents


def relocate_reference(text, metadata, out, root=ROOT):
    # Only the three exact historical path prefixes are relocated. Hashes and
    # model/firmware bytes are never rewritten or relaxed.
    for old, new in [(metadata['original_output'], str(out)),
                     (metadata['original_executor_root'], str(out)),
                     (metadata['original_root'], str(root))]:
        text = re.sub(re.escape(old)+r'(?=/|["\s]|$)', lambda match: new, text)
    return text


def setup(kind, out, deadline=None):
    if kind == 'synthetic':
        lines = ['mach create "main"', f'include @{ROOT}/printer-shared-mcu/peripherals/VirtualTimeTelemetry.cs',
                 'machine LoadPlatformDescriptionFromString "timeTelemetry: PrinterShared.VirtualTimeTelemetry @ sysbus { periodMicroseconds: 1000 }"',
                 f'sysbus.timeTelemetry Enable "{out}/virtual-time.json"']
        boards = ['main']
    else:
        from run_link import parser
        import shared_mcu
        from shared_mcu import prepare
        reference_metadata, reference = load_reference()
        for name in ('motor-setup.commands', 'nozzle-setup.commands'):
            text = relocate_reference(reference[name], reference_metadata, out)
            (out/name).write_text(text)
        a = parser().parse_args(['--shared-mcus', '--clock-coupled', '--clock-lockstep',
            '--clock-source', 'qom-deadline', '--qemu-icount-shift', '0',
            '--mcu-image', str(ROOT/'inputs/mcu.bin'), '--nozzle-image', str(ROOT/'inputs/nozzle.bin'),
            '--motor-image', str(ROOT/'inputs/motor.bin'), '--mcu-base', '0x08004000', '--mcu-hext', '24000000',
            '--motor-plant', 'electromechanical-driver', '--nozzle-tmc-model', 'autobaud',
            '--motor-enable-wiring', 'mcu-control-only',
            '--motor-setup-commands', str(out/'motor-setup.commands'),
            '--trace-homing-gpio', '--assumed-xy-diag-cable', '--log-dir', str(out)])
        if hasattr(a, 'renode_bootstrap'):
            a.renode_bootstrap = 'legacy'
        original_subprocess = shared_mcu.subprocess
        def bounded_generate(*args, **kwargs):
            kwargs['timeout'] = max(.01, (deadline or time.monotonic()+30)-time.monotonic()-2)
            return original_subprocess.run(*args, **kwargs)
        shared_mcu.subprocess = types.SimpleNamespace(run=bounded_generate, DEVNULL=subprocess.DEVNULL)
        try:
            script, _ = prepare(a, out, ['include @scripts/virtual-bed-ntc.resc'],
                                (out/'nozzle-setup.commands').read_text().splitlines())
        finally:
            shared_mcu.subprocess = original_subprocess
        lines = prefix_only(script.read_text())
        expected_lines = prefix_only(relocate_reference(reference['shared-link.resc.txt'], reference_metadata, out))
        if lines != expected_lines:
            raise ValueError('Ready-check exact setup commands drifted')
        expected = json.loads(reference['shared-profile.json'])
        actual = json.loads((out/'shared-profile.json').read_text())
        for key, value in expected.items():
            if actual.get(key) != value:
                raise ValueError('Ready-check profile drift: '+key)
        if any(key in actual for key in ('z_probe_profile', 'thermal_profile')):
            raise ValueError('Unexpected Z or thermal profile')
        # Same source bytes as ready-check; generated hashes include absolute output paths.
        source_manifest = json.loads(reference['shared-model-manifest.json'])
        actual_manifest = json.loads((out/'shared-model-manifest.json').read_text())
        source_keys = lambda rows: [(r['board'], r['source'], r['source_sha256']) for r in rows]
        if source_keys(source_manifest) != source_keys(actual_manifest):
            raise ValueError('Ready-check model manifest drift')
        boards = ['main', 'nozzle', 'motor']
    if kind == 'synthetic':
        lines += [f'include @{HERE}/BoundaryProbe.cs',
                  'machine LoadPlatformDescriptionFromString "boundaryProbe: BootstrapExperiment.BoundaryProbe @ sysbus"']
    lines += ['emulation SetGlobalQuantum "0.000001"', 'mach set "main"']
    return lines, boards


def bounded_send(process, data, deadline):
    """Nonblocking pipe writes; no background writer can outlive this operation."""
    fd = process.stdin.fileno()
    os.set_blocking(fd, False)
    view = memoryview(data)
    while view:
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Monitor pipe write deadline reached')
        if process.poll() is not None:
            raise BrokenPipeError('Monitor exited during write')
        _, writable, _ = select.select([], [fd], [], min(remaining, .05))
        if not writable:
            continue
        try:
            count = os.write(fd, view[:4096])
        except BlockingIOError:
            continue
        if count <= 0:
            raise BrokenPipeError('Zero-length monitor write')
        view = view[count:]


class ProcessGuard:
    """Own a single process group; failed/stopped states are never resumed."""
    def __init__(self, process, deadline, record):
        self.process = process
        self.deadline = deadline
        self.record = record
        self.forced = threading.Event()
        self.cancelled = threading.Event()
        self.signals = []
        self.timer = threading.Timer(max(.001, deadline-time.monotonic()-2), self.expire)
        self.timer.daemon = True
        self.timer.start()

    def group_exists(self):
        try:
            os.killpg(self.process.pid, 0)
            return True
        except ProcessLookupError:
            return False

    def kill(self, reason):
        if reason == 'absolute_runtime_deadline' and self.cancelled.is_set():
            return
        self.forced.set()
        entry = {'signal': 'SIGKILL', 'signal_number': int(signal.SIGKILL),
                 'process_group': self.process.pid, 'reason': reason,
                 'monotonic_s': time.monotonic(), 'outcome': 'pending'}
        self.signals.append(entry)
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
            entry['outcome'] = 'sent'
        except ProcessLookupError:
            entry['outcome'] = 'group_absent'
        except OSError as exc:
            entry['outcome'] = 'error'
            entry['error'] = repr(exc)

    def expire(self):
        if not self.cancelled.is_set():
            self.kill('absolute_runtime_deadline')

    def close(self):
        self.cancelled.set()
        self.timer.cancel()
        self.timer.join(timeout=max(0, min(.5, self.deadline-time.monotonic())))
        stopped = not self.timer.is_alive()
        # No normal termination is requested here: RunFor could still be active,
        # or RenodeStepper could have SIGSTOPped the leader after a failed ack.
        if self.group_exists():
            self.kill('cleanup_of_live_or_uncertain_group')
        while time.monotonic() < self.deadline:
            self.process.poll()  # Reap leader before testing group absence.
            if not self.group_exists():
                break
            time.sleep(min(.01, max(0, self.deadline-time.monotonic())))
        self.record.update(exit_code=self.process.poll(), forced_signals=list(self.signals),
                           watchdog_stopped=stopped, process_group_absent=not self.group_exists(),
                           forced_termination=self.forced.is_set())
        clean = (self.process.returncode == 0 and not self.forced.is_set()
                 and stopped and self.record['process_group_absent'])
        self.record['clean_exit'] = clean
        if not clean:
            self.record['passed'] = False
        if self.process.stdin:
            self.process.stdin.close()
        return clean


def run_arm(kind, mode, out, deadline, paused_motor_probe=False):
    if paused_motor_probe and (kind != 'native-prefix' or mode != 'legacy'):
        raise ValueError('Paused motor probe requires native-prefix legacy mode')
    out.mkdir()
    ack = out/'renode-step.json'
    record = {'passed': False, 'clean_exit': False, 'vendor_firmware_ran': False,
              'vendor_firmware_launch_attempted': False, 'kind': kind, 'mode': mode,
              'compared_duration_ns': 1000000000 if kind == 'synthetic' else 20000000,
              'acknowledged_time_ns': None,
              'global_quantum_ns': 1000, 'full_native_one_second_proven': False}
    if paused_motor_probe:
        record.update(paused_motor_probe_enabled=True, equivalence_established=False,
                      diagnostic_status='incomplete', paused_motor_probe=None)
    save(out/'result.json', record)
    p = None
    guard = None
    try:
        lines, boards = setup(kind, out, deadline)
        total = record['compared_duration_ns']
        if mode == 'legacy':
            lines += [f'emulation RunFor "{total/1e9:.9f}"']
        lines += [f'sysbus.timeTelemetry PublishStep "{ack}" 0']
        script = out/'experiment.resc'
        script.write_text('\n'.join(lines)+'\n')
        env = dict(os.environ, HOME=str(out/'home'), XDG_CONFIG_HOME=str(out/'home/.config'))
        (out/'home/.config').mkdir(parents=True)
        if time.monotonic() >= deadline-2:
            raise TimeoutError('Overall experiment budget exhausted')
        with (out/'renode.log').open('wb') as log:
            record['vendor_firmware_launch_attempted'] = kind != 'synthetic'
            record['vendor_firmware_ran'] = None if kind != 'synthetic' else False
            save(out/'result.json', record)
            p = subprocess.Popen([str(ROOT/'at32-runtime/renode_1.17.0-portable/renode'),
                '--disable-gui', '--console', str(script)], stdin=subprocess.PIPE,
                stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
            guard = ProcessGuard(p, deadline, record)
            def send(data):
                if guard.forced.is_set() or time.monotonic() >= deadline-2:
                    raise TimeoutError('Overall experiment deadline reached')
                with (out/'monitor-input.commands').open('ab') as command_log:
                    command_log.write(data)
                bounded_send(p, data, deadline-2)
            s = RenodeStepper(p, ack, send, timeout=max(.01, deadline-time.monotonic()-2))
            times = [s.time_ns]
            if s.time_ns != (total if mode == 'legacy' else 0):
                raise ValueError('Unexpected bootstrap acknowledgment time')
            record['vendor_firmware_ran'] = kind != 'synthetic' and s.time_ns > 0
            record['acknowledged_time_ns'] = s.time_ns
            save(out/'result.json', record)
            if mode == 'segmented':
                for _ in range(total//1000000):
                    s.timeout = max(.01, deadline-time.monotonic()-2)
                    times.append(s.step(1000000))
                    record['acknowledged_time_ns'] = s.time_ns
                    record['vendor_firmware_ran'] = kind != 'synthetic'
                    save(out/'result.json', record)
            save(out/'acknowledgments.json', {'actual_times_ns': times, 'final_ack': json.loads(ack.read_text())})
            captures = []
            commands = []
            probe = None
            if paused_motor_probe:
                # Import and instantiate only after the original 20 ms RunFor
                # acknowledgment has been validated and saved above.
                import importlib.util
                spec = importlib.util.spec_from_file_location('paused_motor_probe', HERE/'paused_motor_probe.py')
                probe = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(probe)
                if tuple(boards) != probe.BOARDS:
                    raise ValueError('Unexpected boards for paused motor probe')
                commands += probe.before_capture_commands(out)
            for board in boards:
                commands += [f'mach set "{board}"']
                if kind == 'synthetic':
                    captures.append(f'{board}-events.csv')
                    commands += [f'sysbus.boundaryProbe Export "{out}/{board}-events.csv"']
                if kind != 'synthetic':
                    captures.append(f'{board}-sram.bin')
                    commands += [f'dump_file 0x20000000 0x18000 @{out}/{board}-sram.bin', 'cpu PC', 'cpu SP']
            if kind != 'synthetic':
                commands += ['mach set "nozzle"',
                    f'sysbus.passiveNozzleThermalObserver WriteCsv "{out}/nozzle-thermal.csv"',
                    'sysbus.passiveNozzleThermalObserver Stop',
                    f'sysbus.passiveNozzleThermalObserver WriteStreamStatus "{out}/nozzle-thermal-status.json"',
                    f'sysbus.tmcTimingObserver WriteCsv "{out}/nozzle-tmc-edges.csv"',
                    'sysbus.tmcTimingObserver Dropped', 'mach set "motor"',
                    'sysbus.passiveMotorStateTrace Stop', 'sysbus.passiveMotorStateTrace LastError',
                    'sysbus.homingEdges Stop', 'sysbus.homingEdges DroppedRows', 'sysbus.homingEdges LastError',
                    'mach set "main"', 'sysbus.homingEdges Stop',
                    'sysbus.homingEdges DroppedRows', 'sysbus.homingEdges LastError']
            if probe is not None:
                commands += probe.after_capture_commands(out)
            commands += ['quit']
            send(('\n'.join(commands)+'\n').encode())
            p.wait(timeout=max(.01, deadline-time.monotonic()-2))
            record['exit_code'] = p.returncode
            record['clean_exit'] = p.returncode == 0 and not guard.forced.is_set() and not guard.group_exists()
            if not record['clean_exit']:
                raise RuntimeError('Nonzero/forced exit is not clean')
            if kind != 'synthetic':
                captures += ['mcu-tx.bin', 'nozzle-tx.bin', 'motor-tx.bin', 'main-motor-tx.bin', 'main-homing-edges.csv', 'motor-homing-edges.csv', 'motor-state.csv', 'nozzle-thermal.csv', 'nozzle-thermal-live.csv', 'nozzle-tmc-edges.csv']
            if kind != 'synthetic':
                status = json.loads((out/'nozzle-thermal-status.json').read_text())
                for key in ('dropped_rows', 'stream_dropped_rows', 'stream_error_count'):
                    if status.get(key) != 0:
                        raise ValueError('Nozzle observer status failure: '+key)
                if status.get('last_stream_error'):
                    raise ValueError('Nozzle observer stream error')
            hashes = {}
            for name in captures:
                data = (out/name).read_bytes()
                if name.endswith('-sram.bin') and len(data) != 0x18000:
                    raise ValueError('Truncated SRAM '+name)
                hashes[name] = hashlib.sha256(data).hexdigest()
            for board in (boards if kind == 'synthetic' else []):
                events = [int(x) for x in (out/f'{board}-events.csv').read_text().splitlines()]
                if events != list(range(100000, total+1, 100000)):
                    raise ValueError('Unexpected timer event count or actual timestamp sequence')
            if probe is not None:
                record['paused_motor_probe'] = probe.validate_probe(out)
                record['diagnostic_status'] = record['paused_motor_probe']['status']
                if not record['paused_motor_probe']['observations_passed']:
                    raise ValueError('Paused motor observations fail stability, main acknowledgment endpoint, or pre-install anchor')
            record.update(passed=True, captures_sha256=hashes, timer_events_per_board=total//100000 if kind == 'synthetic' else None)
    except Exception as exc:
        record['error'] = repr(exc)
    finally:
        if guard is not None:
            guard.close()
        elif p is not None:
            # Guard initialization failure still cannot leave the launched group.
            try: os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            try: p.wait(timeout=max(.01, deadline-time.monotonic()))
            except subprocess.TimeoutExpired: pass
            record.update(passed=False, clean_exit=False, forced_termination=True,
                          forced_signals=[{'signal': 'SIGKILL', 'reason': 'guard_initialization_failure'}])
        save(out/'result.json', record)
        if record.get('watchdog_stopped') is False:
            raise RuntimeError('Watchdog did not join: fatal, no subsequent leg permitted')
    return record


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kind', choices=['synthetic', 'native-prefix'], required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--wall-seconds', type=float, default=180)
    ap.add_argument('--mode', choices=['legacy', 'segmented'], help='Required for one native prefix leg')
    ap.add_argument('--paused-motor-probe', action='store_true',
                    help='Optional post-ack read-only diagnostic; native-prefix legacy only')
    a = ap.parse_args()
    if not 5 <= a.wall_seconds <= 180: ap.error('wall-seconds must be 5..180')
    if a.kind == 'native-prefix' and (a.mode is None or a.wall_seconds > 45):
        ap.error('Native prefix requires --mode and --wall-seconds <= 45')
    if a.paused_motor_probe and (a.kind != 'native-prefix' or a.mode != 'legacy'):
        ap.error('--paused-motor-probe requires --kind native-prefix --mode legacy')
    out = a.output.resolve()
    if any(c in str(out) for c in '\n\r"\\ '): ap.error('Unsafe output path')
    if a.kind == 'native-prefix':
        out.parent.mkdir(parents=True, exist_ok=True)
        options = {'paused_motor_probe': True} if a.paused_motor_probe else {}
        result = run_arm(a.kind, a.mode, out, time.monotonic()+a.wall_seconds, **options)
        return 0 if result['passed'] else 1
    out.mkdir(parents=True, exist_ok=False)
    summary = {'passed': False, 'status': 'incomplete', 'kind': a.kind, 'vendor_firmware_expected': a.kind != 'synthetic',
        'compared_duration_ns': 1000000000 if a.kind == 'synthetic' else 20000000,
        'full_native_one_second_proven': False, 'wall_budget_s': a.wall_seconds, 'arms': []}
    save(out/'comparison.json', summary)
    deadline = time.monotonic()+a.wall_seconds
    for label, mode in [('baseline-a', 'legacy'), ('candidate', 'segmented'), ('baseline-b', 'legacy')]:
        result = run_arm(a.kind, mode, out/label, deadline)
        summary['arms'].append(result)
        save(out/'comparison.json', summary)
        if not result['passed']: break
    if len(summary['arms']) == 3 and all(x['passed'] for x in summary['arms']):
        first, candidate, repeat = [x['captures_sha256'] for x in summary['arms']]
        summary['baseline_repeat_equal'] = first == repeat
        summary['candidate_equal'] = first == candidate
        summary['passed'] = first == repeat == candidate
    summary['status'] = 'passed_observed_captures_only' if summary['passed'] else 'failed_or_inconclusive'
    save(out/'comparison.json', summary)
    return 0 if summary['passed'] else 1

if __name__ == '__main__':
    sys.exit(main())
