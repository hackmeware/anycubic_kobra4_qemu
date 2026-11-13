"""Bounded Renode clock-only + synthetic QEMU smoke, no vendor firmware."""
import argparse
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE.parents[1]/'scripts'), str(HERE.parent/'stop-event-clock'), str(HERE/'client')]
from renode_stepper import RenodeStepper
from lockstep_coordinator import LockstepCoordinator
from snapshot_clock import SnapshotClockClient


def stop_process(proc):
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=2)


def main():
    signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(SystemExit(128+signum)))
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qemu', type=pathlib.Path, required=True)
    p.add_argument('--renode', type=pathlib.Path, required=True)
    p.add_argument('--fixture', type=pathlib.Path, required=True)
    p.add_argument('--output', type=pathlib.Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if args.fixture.read_bytes() != bytes.fromhex('feffffea'):
        p.error('Only exact synthetic B . fixture allowed')
    with tempfile.TemporaryDirectory(prefix='snapshot-joint-clock-') as folder:
        tmp = pathlib.Path(folder)
        (tmp/'home/.config').mkdir(parents=True)
        env = dict(os.environ, HOME=str(tmp/'home'), XDG_CONFIG_HOME=str(tmp/'home/.config'), TMPDIR=str(tmp))
        ack = tmp/'ack.json'
        script = tmp/'clock.resc'
        script.write_text(f'''include @{ROOT}/printer-shared-mcu/peripherals/VirtualTimeTelemetry.cs
mach create "main"
emulation SetGlobalQuantum "0.000001"
machine LoadPlatformDescriptionFromString "timeTelemetry: PrinterShared.VirtualTimeTelemetry @ sysbus {{ periodMicroseconds: 1000 }}"
sysbus.timeTelemetry Enable "{tmp}/clock.json"
emulation RunFor "0.001"
sysbus.timeTelemetry PublishStep "{ack}" 0
''')
        (args.output/'clock.resc.txt').write_text(script.read_text())
        with (args.output/'renode.log').open('wb') as log:
            renode = subprocess.Popen([str(args.renode.resolve()), '--disable-gui', '--console', str(script)],
                                      stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
            qemu = None
            gate = None
            try:
                lock = threading.Lock()
                def send(data):
                    with lock:
                        renode.stdin.write(data)
                        renode.stdin.flush()
                stepper = RenodeStepper(renode, ack, send, timeout=15)
                micro = [stepper.time_ns]
                for _ in range(3):
                    micro.append(stepper.step(1000))
                if micro != [1000000, 1001000, 1002000, 1003000]:
                    raise RuntimeError('Renode 1-us acknowledgement mismatch')
                qemu = subprocess.Popen([str(args.qemu.resolve()), '-M', 'rv1106,virtual-deadline-enabled=on',
                    '-m', '64M', '-S', '-display', 'none', '-serial', 'null', '-monitor', 'none', '-qmp', 'stdio',
                    '-nic', 'none', '-icount', 'shift=0,align=off,sleep=off', '-kernel', str(args.fixture.resolve())],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, start_new_session=True)
                q = SnapshotClockClient(qemu.stdout, qemu.stdin, timeout=2)
                gate = LockstepCoordinator(q, stepper, args.output/'coordinator.json')
                limit = time.monotonic()+20
                while len(gate.samples) < 100 and not gate.error and time.monotonic() < limit:
                    time.sleep(.01)
                gate.close()
                if gate.error or len(gate.samples) < 100:
                    raise RuntimeError(gate.error or 'Joint cycle count too low')
                if gate.max_lead != 1 or gate.max_lag != 1000000:
                    raise RuntimeError('Changed actual clock skew')
                result = {'passed': True, 'renode_quantum_ns': 1000, 'coordinator_slice_ns': 1000000,
                          'renode_microstep_times_ns': micro, 'combined_steps': len(gate.samples),
                          'max_actual_lead_ns': gate.max_lead, 'max_actual_lag_ns': gate.max_lag,
                          'native_firmware': False, 'physical_timing_fidelity_proven': False}
                (args.output/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
                print(json.dumps(result))
            finally:
                if gate is not None:
                    gate.close()
                if qemu is not None:
                    stop_process(qemu)
                stop_process(renode)


if __name__ == '__main__':
    main()
