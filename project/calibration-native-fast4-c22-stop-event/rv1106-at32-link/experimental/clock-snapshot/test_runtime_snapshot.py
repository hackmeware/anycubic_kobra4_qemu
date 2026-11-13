"""Bounded actual-QEMU read-only snapshot/schema/state regression.

Raw monitor deliberately observes RESET rather than hiding its state transition;
production clients must still invalidate on RESET, as offline tests require.
"""
import argparse
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1]/'scripts'), str(HERE.parent/'stop-event-clock'), str(HERE/'client')]
from stop_event_clock import BoundedStreamPair
from snapshot_clock import SnapshotClockClient


def check(value, message):
    if not value:
        raise RuntimeError(message)


class VM:
    def __init__(self, executable, fixture, enabled):
        self.proc = subprocess.Popen([str(executable), '-M', 'rv1106'+(',virtual-deadline-enabled=on' if enabled else ''),
            '-m', '64M', '-S', '-display', 'none', '-serial', 'null', '-monitor', 'none',
            '-qmp', 'stdio', '-nic', 'none', '-icount', 'shift=0,align=off,sleep=off', '-kernel', str(fixture)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, start_new_session=True)
        self.stream = BoundedStreamPair(self.proc.stdout, self.proc.stdin, timeout=2)
        self.serial = 0
        self.events = []
        check('QMP' in self.read(), 'Missing greeting')
        self.call('qmp_capabilities')

    def read(self):
        result = json.loads(self.stream.readline())
        check(isinstance(result, dict), 'Malformed QMP object')
        return result

    def call(self, command, arguments=None, error=False):
        self.serial += 1
        request = {'execute': command, 'id': self.serial}
        if arguments is not None:
            request['arguments'] = arguments
        self.stream.write((json.dumps(request)+'\n').encode())
        limit = time.monotonic()+2
        while True:
            self.stream.timeout = limit-time.monotonic()
            check(self.stream.timeout > 0, 'QMP command timeout')
            result = self.read()
            if 'event' in result:
                self.events.append(result)
                continue
            check(result.get('id') == self.serial, 'Unexpected response id')
            self.stream.timeout = 2
            if error:
                check('error' in result, 'Expected QMP error')
                return result['error']
            check('error' not in result and 'return' in result, str(result))
            return result['return']

    def get(self, name):
        return self.call('qom-get', {'path': '/machine', 'property': name})

    def set(self, name, value, error=False):
        return self.call('qom-set', {'path': '/machine', 'property': name, 'value': value}, error=error)

    def close(self):
        self.stream.close()
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.proc.wait(timeout=2)


def compare(vm, label):
    state = vm.get('virtual-clock-state')
    for name in SnapshotClockClient.INTS:
        check(type(state.get(name)) is int, 'Non-integer '+name)
    for name in SnapshotClockClient.BOOLS:
        check(type(state.get(name)) is bool, 'Non-boolean '+name)
    check(state['schema'] == 1 and state['source'] == SnapshotClockClient.SOURCE, 'Schema/source')
    check(state['initialized'] is True, 'Uninitialized')
    check(state['running'] is False and vm.call('query-status')['running'] is False, 'Not paused')
    mapping = {'enabled': 'virtual-deadline-enabled', 'epoch': 'virtual-clock-epoch',
               'virtual_time_ns': 'virtual-time-ns', 'deadline_ns': 'virtual-deadline-ns',
               'armed': 'virtual-deadline-armed', 'fired': 'virtual-deadline-fired',
               'fired_ns': 'virtual-deadline-fired-ns', 'stop_ns': 'virtual-deadline-stop-ns'}
    for field, prop in mapping.items():
        check(state[field] == vm.get(prop), f'{label}: scalar mismatch {field}')
    for _ in range(5):
        check(vm.get('virtual-clock-state') == state, f'{label}: snapshot changed frozen state')
    return {'label': label, 'snapshot': state}


def main():
    signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(SystemExit(128+signum)))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True, type=pathlib.Path)
    parser.add_argument('--baseline', required=True, type=pathlib.Path)
    parser.add_argument('--fixture', required=True, type=pathlib.Path)
    parser.add_argument('--output', required=True, type=pathlib.Path)
    args = parser.parse_args()
    check(args.fixture.read_bytes() == bytes.fromhex('feffffea'), 'Wrong synthetic fixture')
    cases = []
    vm = VM(args.baseline.resolve(), args.fixture.resolve(), True)
    try:
        vm.call('qom-get', {'path': '/machine', 'property': 'virtual-clock-state'}, error=True)
        check(vm.call('query-status')['running'] is False, 'Baseline unexpectedly started')
        cases.append({'label': 'unmodified baseline lacks new property', 'passed': True})
    finally:
        vm.close()
    for enabled in (False, True):
        vm = VM(args.candidate.resolve(), args.fixture.resolve(), enabled)
        try:
            cases.append(compare(vm, 'initial-enabled' if enabled else 'initial-disabled'))
            state = vm.get('virtual-clock-state')
            check(state['enabled'] is enabled, 'Snapshot changed opt-in')
            vm.set('virtual-clock-state', state, error=True)
            check(vm.get('virtual-clock-state') == state, 'Readonly set changed state')
            if not enabled:
                vm.set('virtual-deadline-ns', 1000000, error=True)
                cases.append(compare(vm, 'disabled-after-refused-arm'))
                continue
            vm.set('virtual-deadline-ns', -1, error=True)
            vm.set('virtual-deadline-ns', 1000000)
            cases.append(compare(vm, 'armed'))
            vm.set('virtual-deadline-ns', 0)
            cases.append(compare(vm, 'canceled'))
            for quantum in (1000, 1000000):
                target = vm.get('virtual-time-ns')+quantum
                vm.set('virtual-deadline-ns', target)
                vm.call('cont')
                limit = time.monotonic()+2
                while vm.call('query-status')['running']:
                    check(time.monotonic() < limit, 'Deadline did not stop')
                cases.append(compare(vm, f'fired-{quantum}'))
                result = cases[-1]['snapshot']
                check(result['fired_ns'] == target and result['stop_ns'] == target+1, 'Changed exact stop')
            target = vm.get('virtual-time-ns')+50000000
            vm.set('virtual-deadline-ns', target)
            vm.call('cont')
            live = vm.get('virtual-clock-state')
            check(live['running'] is True and vm.call('query-status')['running'] is True, 'Read paused running VM')
            vm.call('stop')
            cases.append({'label': 'running-read-does-not-pause', 'snapshot': live})
            cases.append(compare(vm, 'manual-stop-before-deadline'))
            vm.set('virtual-deadline-ns', 0)
            epoch = vm.get('virtual-clock-epoch')
            vm.call('system_reset')
            limit = time.monotonic()+2
            while vm.get('virtual-clock-epoch') == epoch:
                check(time.monotonic() < limit, 'Reset did not advance epoch')
            cases.append(compare(vm, 'reset'))
            reset = cases[-1]['snapshot']
            check(reset['epoch'] == epoch+1 and reset['deadline_ns'] == 0 and not reset['armed']
                  and not reset['fired'] and reset['fired_ns'] == reset['stop_ns'] == -1, 'Bad reset state')
        finally:
            vm.close()
    args.output.write_text(json.dumps({'passed': True, 'synthetic_only': True, 'cases': cases}, indent=2)+'\n')
    print(json.dumps({'passed': True, 'cases': len(cases)}))


if __name__ == '__main__':
    main()
