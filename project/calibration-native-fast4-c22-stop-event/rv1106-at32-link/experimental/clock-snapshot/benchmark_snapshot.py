"""Order-balanced QEMU-only comparison; no native acceleration claim."""
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

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1]/'scripts'), str(HERE.parent/'stop-event-clock'), str(HERE/'client'), str(HERE.parent/'stop-latency')]
from stop_event_clock import StopEventClockClient
from snapshot_clock import SnapshotClockClient
from measure_stop_latency import process_metrics, metric_delta


def run(args, mode, index):
    binary = args.baseline if mode == 'baseline_scalar' else args.candidate
    client = SnapshotClockClient if mode == 'candidate_snapshot' else StopEventClockClient
    command = [str(binary), '-M', 'rv1106,virtual-deadline-enabled=on', '-m', '64M', '-S',
               '-display', 'none', '-serial', 'null', '-monitor', 'none', '-qmp', 'stdio',
               '-nic', 'none', '-icount', 'shift=0,align=off,sleep=off', '-kernel', str(args.fixture)]
    with (args.output/f'{index:02d}-{mode}.stderr').open('wb') as stderr:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=stderr, bufsize=0, start_new_session=True)
        q = None
        try:
            q = client(proc.stdout, proc.stdin, timeout=2)
            origin = previous = q.paused_now()
            samples = []
            for step in range(1, args.steps+6):
                if step == 6:
                    before = process_metrics(proc.pid)
                    req0, write0 = q.requests_sent, q.writes_sent
                    started, cpu0 = time.monotonic(), time.process_time()
                start = time.monotonic()
                if q.paused_now() != previous:
                    raise RuntimeError('Frozen clock changed outside control')
                boundary = time.monotonic()-start
                target = origin+step*args.slice_ns
                actual = q.run_until(target)
                if actual != target+1 or q.last_fired != target:
                    raise RuntimeError('Virtual deadline behavior changed')
                previous = actual
                if step > 5:
                    samples.append({'step': step-5, 'deadline_ns': target, 'callback_ns': q.last_fired,
                                    'stop_ns': actual, 'phases_s': {**q.last_phase_wall_s, 'boundary': boundary}})
                    if time.monotonic()-started > 20:
                        raise RuntimeError('20-second measured run cap exceeded')
            wall, cpu = time.monotonic()-started, time.process_time()-cpu0
            after = process_metrics(proc.pid)
            delta = metric_delta(before, after)
            total_qemu_cpu = None if any('unavailable' in r for r in delta.values()) else sum(r['runtime_ns'] for r in delta.values())
            trace = [[x['step'], x['deadline_ns'], x['callback_ns'], x['stop_ns']] for x in samples]
            summary = {'mode': mode, 'slice_ns': args.slice_ns, 'steps': args.steps, 'warmup_steps': 5,
                       'wall_seconds': wall, 'steps_per_second': args.steps/wall,
                       'client_cpu_seconds': cpu, 'qemu_cpu_seconds': None if total_qemu_cpu is None else total_qemu_cpu/1e9,
                       'qmp_requests': q.requests_sent-req0, 'qmp_writes': q.writes_sent-write0,
                       'mean_phases_ms': {k: statistics.mean(x['phases_s'][k] for x in samples)*1000 for k in samples[0]['phases_s']},
                       'trace_sha256': hashlib.sha256(json.dumps(trace).encode()).hexdigest(),
                       'max_stop_overshoot_ns': 1, 'max_callback_overshoot_ns': 0,
                       'native_speedup_proven': False}
            (args.output/f'{index:02d}-{mode}.json').write_text(json.dumps(
                {**summary, 'command': command, 'samples': samples, 'qemu_thread_metrics': delta}, indent=2)+'\n')
            print(json.dumps(summary), flush=True)
            return summary
        finally:
            if q is not None:
                try:
                    q.close()
                except Exception:
                    pass
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
    p.add_argument('--baseline', required=True, type=pathlib.Path)
    p.add_argument('--candidate', required=True, type=pathlib.Path)
    p.add_argument('--fixture', required=True, type=pathlib.Path)
    p.add_argument('--output', required=True, type=pathlib.Path)
    p.add_argument('--slice-ns', type=int, choices=(1000, 1000000), required=True)
    p.add_argument('--steps', type=int, default=250)
    p.add_argument('--reverse', action='store_true')
    args = p.parse_args()
    if not 1 <= args.steps <= 1000:
        p.error('steps must be 1..1000')
    if args.fixture.read_bytes() != bytes.fromhex('feffffea'):
        p.error('Only the exact four-byte B . fixture is accepted')
    args.baseline, args.candidate, args.fixture = args.baseline.resolve(), args.candidate.resolve(), args.fixture.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    order = ['baseline_scalar', 'candidate_scalar', 'candidate_snapshot', 'candidate_snapshot', 'candidate_scalar', 'baseline_scalar']
    if args.reverse:
        order = ['candidate_snapshot', 'baseline_scalar', 'candidate_scalar', 'candidate_scalar', 'baseline_scalar', 'candidate_snapshot']
    results = [run(args, mode, i) for i, mode in enumerate(order)]
    if len({r['trace_sha256'] for r in results}) != 1:
        raise RuntimeError('Different virtual traces across modes')
    (args.output/'summary.json').write_text(json.dumps({'all_virtual_traces_identical': True, 'results': results}, indent=2)+'\n')


if __name__ == '__main__':
    main()
