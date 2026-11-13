"""Bounded QEMU-only protocol benchmark, no Renode/vendor image/disk/network.

Only the explicit four-byte ARM branch-to-self fixture is accepted. This does
not establish native printer throughput, synchronization, or hardware fidelity.
"""
import argparse
import hashlib
import json
import os
import pathlib
import signal
import statistics
import subprocess
import sys
import time

BASE = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE / 'scripts'))
sys.path.insert(0, str(BASE / 'experimental/batched-clock'))
from timed_baseline_clock import EventClockClient
from batched_event_clock import BatchedEventClockClient
from stop_event_clock import StopEventClockClient


class CountingWriter:
    def __init__(self, stream):
        self.stream = stream
        self.requests = self.writes = 0

    def write(self, data):
        self.requests += data.count(b'\n')
        self.writes += 1
        return self.stream.write(data)

    def flush(self):
        self.stream.flush()

    def fileno(self):
        return self.stream.fileno()

    def close(self):
        self.stream.close()


def run(mode, args, index):
    cls = {'baseline': EventClockClient, 'batched': BatchedEventClockClient,
           'stop_event': StopEventClockClient}[mode]
    command = [str(args.qemu), '-M', 'rv1106,virtual-deadline-enabled=on',
               '-m', '64M', '-S', '-display', 'none', '-serial', 'null',
               '-monitor', 'none', '-qmp', 'stdio', '-nic', 'none',
               '-icount', 'shift=0,align=off,sleep=off', '-kernel', str(args.fixture)]
    log = args.output / f'{index:02d}-{mode}.stderr'
    with log.open('wb') as stderr:
        p = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=stderr, bufsize=0, start_new_session=True)
        q = None
        try:
            writer = CountingWriter(p.stdin)
            q = cls(p.stdout, writer, timeout=2)
            q.call('stop')
            origin = previous = q.now()
            samples, phases = [], []
            def counts():
                return ((q.requests_sent, q.writes_sent) if mode == 'stop_event'
                        else (writer.requests, writer.writes))
            req0, wr0 = counts()
            begin, cpu_begin = time.monotonic(), time.process_time()
            for step in range(1, args.steps + 1):
                if time.monotonic() - begin > 20:
                    raise RuntimeError('QEMU-only benchmark exceeded 20-second run cap')
                if hasattr(q, 'paused_now'):
                    boundary = q.paused_now()
                else:
                    if q.call('query-status').get('running') is not False:
                        raise RuntimeError('Baseline boundary is not paused')
                    boundary = q.now()
                if boundary != previous:
                    raise RuntimeError(f'Paused counter changed: {boundary} != {previous}')
                target = origin + step * 1000000
                actual = q.run_until(target)
                # Exact fixture invariant, stricter than the coordinator limit.
                if actual != target + 1:
                    raise RuntimeError(f'Unexpected exact fixture stop: {actual} != {target}+1')
                samples.append([step, target, q.last_fired, actual])
                phases.append(q.last_phase_wall_s)
                previous = actual
            wall, cpu = time.monotonic()-begin, time.process_time()-cpu_begin
            result = {'mode': mode, 'steps': args.steps, 'wall_seconds': wall,
                      'client_cpu_seconds': cpu, 'steps_per_second': args.steps/wall,
                      'qmp_requests': counts()[0]-req0, 'qmp_writes': counts()[1]-wr0,
                      'maximum_deadline_overshoot_ns': max(s[3]-s[1] for s in samples),
                      'virtual_trace_sha256': hashlib.sha256(json.dumps(samples).encode()).hexdigest(),
                      'mean_phase_wall_s': {k: statistics.mean(x[k] for x in phases) for k in phases[0]},
                      'samples': samples}
            q.call('stop')
            return result
        finally:
            if q is not None:
                try:
                    q.close()
                except Exception:
                    pass
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                p.wait(timeout=2)


def main():
    def terminate(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', type=pathlib.Path, required=True)
    parser.add_argument('--fixture', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--steps', type=int, default=250)
    parser.add_argument('--order', default='baseline,batched,stop_event,stop_event,batched,baseline')
    args = parser.parse_args()
    args.qemu, args.fixture = args.qemu.resolve(), args.fixture.resolve()
    if args.fixture.read_bytes() != bytes.fromhex('feffffea'):
        parser.error('Only the exact four-byte ARM B . fixture is accepted')
    if not 1 <= args.steps <= 1000:
        parser.error('steps must be 1..1000')
    order = args.order.split(',')
    if len(order) > 12 or any(x not in ('baseline', 'batched', 'stop_event') for x in order):
        parser.error('Invalid mode order or too many runs')
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    for index, mode in enumerate(order):
        result = run(mode, args, index)
        results.append(result)
        (args.output / f'{index:02d}-{mode}.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps({k: v for k, v in result.items() if k != 'samples'}), flush=True)
    if len({r['virtual_trace_sha256'] for r in results}) != 1:
        raise RuntimeError('Virtual traces differ across modes')
    summary = {'scope': 'QEMU-only synthetic fixture, no Renode or native firmware',
               'clock_frequency_modified': False, 'physical_timing_fidelity_proven': False,
               'native_speedup_proven': False, 'all_virtual_traces_identical': True,
               'fixture_sha256': hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
               'results': [{k: v for k, v in r.items() if k != 'samples'} for r in results]}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2)+'\n')


if __name__ == '__main__':
    main()
