"""Offline adapter integration; real packet/command/capture and probe parsers.

Only process ownership, profile closure, and thermal/model exporters are synthetic.
No command text is executed, and no RPC, client or emulator is launched.
"""
import csv
import io
import json
import math
from pathlib import Path
import re
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
from test_support import source_profile, fixture
PROFILE = source_profile()
o = types.ModuleType('homing_runtime_observer')
o.__file__ = str(HERE / 'observer.py')
exec(compile((HERE / 'observer.py').read_bytes(), o.__file__, 'exec'), o.__dict__)
b, base = o.cp.load(PROFILE)
p = b.p
STATUS_WIRE = fixture('get-status.response.http2.bin')
READY_WIRE = fixture('printer-state.response.http2.bin')


def unary():
    def header(k, v):
        return b'\0' + bytes([len(k)]) + k + bytes([len(v)]) + v
    return p.frame(1, 4, 1, b'\x88' + header(b'content-type', b'application/grpc')) + p.frame(0, 0, 1, b'\0\0\0\0\0') + p.frame(1, 5, 1, header(b'grpc-status', b'0'))


def csv_data(header, rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header, lineterminator='\n')
    writer.writeheader(); writer.writerows(rows)
    return out.getvalue().encode()


def row(i, t, z=-10.1, force=2., velocity=0.):
    r = dict(sequence=str(i), observation_time_s=str(t))
    for a in 'xyz':
        r.update({a + '_state_time_s': str(t), a + '_angle_rad': '0', a + '_relative_mm': str(z if a == 'z' else 0.), a + '_velocity_rad_s': str(velocity * 2 * math.pi / 8 if a == 'z' else 0.), a + '_contact_torque_nm': str(force * .008 / (2 * math.pi) if a == 'z' else 0.), a + '_bridge_enabled': '1'})
    r.update(z_bed_clearance_mm=str(z + 10), z_compression_mm=str(max(0, -z - 10)), z_contact_force_n=str(force), z_contact_nonzero=str(int(force != 0)))
    return r


class SyntheticNozzle:
    """Explicit thermal fixture; not a transport or physical acceptance stub."""
    def __init__(self): self.rows = []; self.last_growth_shared_ns = None
    def consume(self, data, now):
        if data != b'SYNTHETIC_THERMAL_CONTRACT\n': raise ValueError('thermal fixture changed')
        self.rows = [{'time_us': str(now // 1000)}]; self.last_growth_shared_ns = now
    def summary(self): return {'available': bool(self.rows), 'synthetic_contract_fixture': True}


class Harness:
    def __init__(self, root, bad=None):
        self.root = root; self.bad = bad; self.t = 0.; self.wall = 0.; self.rows = []; self.release = None; self.home_z_time = None; self.commands = []; self.stages = []
    def monotonic(self): return self.wall
    def launch(self, args, env):
        self.args = args; self.env = env; self.d = self.root / 'runs' / args[1]; self.d.mkdir(parents=True)
        self.console = 'COUPLED_STARTUP_COMMANDS_DONE\n'
        if self.bad != 'late_ready': self.console += '[1970-01-01 00:00:00.001] [info] [1] Printer is ready at 0.001.\n'
        (self.d / 'console-input.commands').write_text('')
        (self.d / 'nozzle-thermal-live.csv').write_bytes(b'SYNTHETIC_THERMAL_CONTRACT\n')
        for filename, label, pin in self.probe_names():
            (self.d / filename).write_text('# PASSIVE GPIO EDGE TRACE v1; source-local virtual timestamps; no SyncTime or signal writes\nvirtual_time_s,sequence,kind,label,pin,level\n0,0,initial,' + label + ',' + str(pin) + ',0\n')
        self.sample(); return self
    @staticmethod
    def probe_names(): return [('nozzle-z-probe-edges.csv', 'nozzle_PA7_Z', 7), ('main-z-probe-edges.csv', 'main_PB2_Z', 2)]
    def poll(self): return None
    def sample(self):
        z = -9.1 if self.home_z_time is None else -10.1; force = 0. if self.home_z_time is None else 2.; velocity = 0.
        if self.release is not None:
            delta = min(1., max(0., self.t - self.release)); z += delta
            force = max(0., -z - 10) * 20; velocity = 1. if delta < 1 else 0.
            if self.bad == 'wrong_direction': z = -10.2; force = 4.; velocity = -1.
        self.rows.append(row(len(self.rows), self.t, z, force, velocity))
        (self.d / 'physical-state.csv').write_bytes(csv_data(o.physical.HEADER, self.rows))
        (self.d / 'console.bin').write_text(self.console)
        (self.d / 'virtual-time.json').write_text(json.dumps(dict(schema=1, source='renode-shared-mcu', enabled=True, time_went_backwards=False, virtual_time_ns=round(self.t * 1e9), sequence=len(self.rows), epoch='synthetic')))
    def sleep(self, seconds):
        self.wall += .1; self.t = round(self.t + .01, 8)
        if self.bad == 'late_ready' and self.t >= 6 and 'Printer is ready' not in self.console:
            self.console += '[1970-01-01 00:00:00.001] [info] [1] Printer is ready at 0.001.\n'
        self.sample()
    def wait(self, timeout):
        if self.bad == 'cleanup': raise o.subprocess.TimeoutExpired('synthetic', timeout)
        if self.bad == 'final_native_fault': self.console += '[1970-01-01 00:00:09.999] [error] [1] MCU failed\n'
        self.sleep(.1)
        if self.bad == 'final_recontact':
            self.rows[-1] = row(len(self.rows)-1, self.t, -10.1, 2.)
            (self.d / 'physical-state.csv').write_bytes(csv_data(o.physical.HEADER, self.rows))
        (self.d / 'physical-state-status.json').write_text(json.dumps(dict(rows_written=len(self.rows), dropped_rows=0, error_count=0, capacity_reached=False, last_error='', stopped=True)))
        monitor = ''
        for board in ('nozzle', 'main'):
            monitor += f'COLD_PROBE_{board}_BEGIN\nTrue\nFalse\n3\n0\n2\nFalse\n\nCOLD_PROBE_{board}_END\n'
        monitor += 'COLD_CONTACT_BEGIN\nFalse\n5\n0\n\nCOLD_CONTACT_END\n'
        if self.bad == 'final_health': monitor = monitor.replace('\n3\n0\n2\n', '\n3\n1\n2\n')
        (self.d / 'renode.log').write_text(monitor)
        if self.bad == 'final_probe':
            for filename, label, pin in self.probe_names():
                with (self.d / filename).open('a') as f: f.write(f'{self.t},3,edge,{label},{pin},1\n')
        contact = []
        for axis in range(3):
            contact.append(dict(observation_time_s=0, previous_integration_time_s=0, state_time_s=0, axis=axis, kind='initial', contact_nonzero=0, angle_rad=0, velocity_rad_s=0, relative_mm=-10.1 if axis == 2 else 0, contact_torque_nm=0))
        on = (self.home_z_time or 0) + .0001
        contact.append(dict(observation_time_s=on, previous_integration_time_s=on, state_time_s=on, axis=2, kind='transition', contact_nonzero=1, angle_rad=0, velocity_rad_s=0, relative_mm=-10.1, contact_torque_nm=.002))
        contact.append(dict(observation_time_s=(self.release or 0)+.11, previous_integration_time_s=(self.release or 0)+.11, state_time_s=(self.release or 0)+.11, axis=2, kind='transition', contact_nonzero=0, angle_rad=0, velocity_rad_s=0, relative_mm=-9.99, contact_torque_nm=0))
        (self.d / 'contact-transitions.csv').write_bytes(csv_data(o.physical.CONTACT_HEADER, contact))
        return 0
    def owner(self, path):
        h = self
        class Owner:
            pending = None
            def check(self): pass
            def close(self): pass
            def complete(self, label):
                if self.pending != label: raise ValueError('synthetic batch mismatch')
                self.pending = None
            def append_once(self, label, commands):
                if self.pending is not None: raise ValueError('overlapping batch')
                self.pending = label; h.commands.append(commands)
                match = re.search(r"AMBIENT_MARKER=\$\(printf '((?:\\[0-7]{3})+)'\)", commands)
                if not match: raise ValueError('real marker setup absent')
                prefix = bytes(int(v, 8) for v in re.findall(r'\\([0-7]{3})', match[1])).decode('ascii')
                token, kind = prefix.split('_')[1:]
                if kind == 'C':
                    if commands != p.shell_check_command_batch(token): raise ValueError('shell command mismatch')
                    h.console += p.shell_check_expected(token)
                elif kind.startswith('L'):
                    if commands != b.log_command_batch(token, kind): raise ValueError('log command mismatch')
                    h.console += prefix + '_B\nsynthetic log snapshot\n' + prefix + '_E\n'
                else:
                    stage = label
                    packet, client = b.build(stage)
                    if commands != b.commands(stage, token, client): raise ValueError('RPC command mismatch')
                    uploaded = b''.join(bytes(int(v, 8) for v in re.findall(r'\\([0-7]{3})', line.split("'", 2)[1])) for line in commands.splitlines() if line.startswith("printf '"))
                    if uploaded != client or p.load_helpers()[0].extract_packet(uploaded) != packet: raise ValueError('uploaded client differs')
                    h.stages.append(stage)
                    if h.bad == 'uncertain': raise OSError('synthetic uncertain append')
                    wire = READY_WIRE if stage == 'ready' else STATUS_WIRE if b.mode(stage) == 'GetStatus' else unary()
                    dump = '\n'.join(f'{off:07o} ' + ' '.join(f'{v:03o}' for v in wire[off:off+16]) for off in range(0, len(wire), 16)) + f'\n{len(wire):07o}\n'
                    status = 20 if b.mode(stage) == 'GetStatus' else 0
                    h.console += f'{prefix}_B\n1.00 0.00\n{prefix}_X={status}\n{prefix}_RB\n{dump}{prefix}_RE\n1.01 0.00\n{prefix}_E\n'
                    if stage.startswith('home_'):
                        stamp = 100 + len(h.commands)*2
                        h.console += f'[1970-01-01 00:00:01.{stamp:03d}] [info] [1] Home Rail Begin - stepper: {stage[-1]}\n'
                        if h.bad != 'missing_rail': h.console += f'[1970-01-01 00:00:01.{stamp+1:03d}] [info] [1] Home Rail Complete - stepper: {stage[-1]}\n'
                    if stage == 'home_z':
                        h.home_z_time = h.t
                        for filename, label_, pin in h.probe_names():
                            delay = .000001 if pin == 2 else 0.
                            with (h.d / filename).open('a') as f: f.write(f'{h.t+.0002+delay:.6f},1,edge,{label_},{pin},1\n{h.t+.001+delay:.6f},2,edge,{label_},{pin},0\n')
                    if stage == 'status_z': h.release = h.t + .01
                (h.d / 'console.bin').write_text(h.console)
        return Owner()


def run_mock(bad=None, artifact_check=None):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); h = Harness(root, bad)
        mocked = types.ModuleType('synthetic_base'); mocked.__dict__.update(base.__dict__)
        mocked.ConsoleOwner = h.owner; mocked.PassiveNozzle = SyntheticNozzle
        mocked.final_passive = lambda *args: {'synthetic_contract_fixture': True, 'final_export_verified': True}
        boundary = o.cp.Boundary(p)
        boundary.validate_profile = lambda directory: {'synthetic_profile_contract_fixture': True}
        with patch.object(o.cp, 'load', return_value=(boundary, mocked)), patch.object(o, 'ROOT', root), patch.object(o, 'validate_model_exports', return_value={'synthetic_model_contract_fixture': True}), patch.object(o.subprocess, 'Popen', side_effect=AssertionError('No real subprocess allowed')):
            result = o.run(root, 'synthetic', '/tmp/unused', h)
            if artifact_check: artifact_check(h.d, result)
        return result, h


class RuntimeTests(unittest.TestCase):
    def test_complete_real_eight_stage_boundary_and_replay(self):
        def check(directory, result):
            self.assertTrue(result['success'], result.get('error'))
            self.assertTrue(o.validate_final_report(result))
            self.assertTrue(o.validate_artifacts(directory))
        result, h = run_mock(artifact_check=check)
        self.assertEqual(result['phase'], 'verified_homing_completion')
        self.assertEqual(h.stages, list(o.cp.STAGES)); self.assertEqual(result['request_count'], 8)
        self.assertTrue(result['homing_completed']); self.assertTrue(result['natural_release_observed'])
        self.assertFalse(result['physical_completion_proven']); self.assertFalse(result['calibration_completed'])
        self.assertNotIn('release_gcode', result)
        for item in result['requests']:
            expected = 20 if b.mode(item['stage']) == 'GetStatus' else 0
            self.assertEqual(item['result']['transport_exit_status'], expected)
        self.assertEqual(sum(batch['kind'] == 'shell' for batch in result['batches']), 8)
        self.assertFalse(any(command.startswith(('RPC ', 'SHELL ', 'LOG ')) for command in h.commands))
        self.assertEqual(h.env['PASSIVE_MOTOR_TRACE'], '0')
        self.assertTrue(h.args[0].endswith('experimental/native-homing-completion/run_homing_fixture.sh'))
    def test_late_ready_passes_L21(self):
        result, h = run_mock('late_ready')
        self.assertTrue(result['success'], result.get('error'))
        self.assertTrue(any(v['label'].endswith('_L21') for v in result['batches'] if v['kind'] == 'log'))
    def test_uncertain_append_is_not_retried(self):
        result, h = run_mock('uncertain')
        self.assertFalse(result['success']); self.assertEqual(result['request_count'], 1); self.assertEqual(h.stages, ['ready'])
    def test_missing_rail_has_no_fallback(self):
        result, h = run_mock('missing_rail')
        self.assertFalse(result['success']); self.assertEqual(h.stages, ['ready', 'baseline', 'home_x'])
    def test_wrong_direction_has_no_extra_rpc(self):
        result, h = run_mock('wrong_direction')
        self.assertFalse(result['success']); self.assertEqual(h.stages, list(o.cp.STAGES))
    def test_cleanup_is_bounded(self):
        result, h = run_mock('cleanup')
        self.assertFalse(result['success']); self.assertTrue(result['cleanup_timeout'])
    def test_final_later_hazards_reject(self):
        for bad in ('final_native_fault', 'final_recontact', 'final_health', 'final_probe'):
            with self.subTest(bad=bad):
                result, h = run_mock(bad)
                self.assertFalse(result['success']); self.assertEqual(h.stages, list(o.cp.STAGES))
    def test_all_real_log_labels(self):
        for i in range(1, 201):
            command = b.log_command_batch('a'*20, 'L'+str(i))
            self.assertEqual(command.count('\n'), 1); self.assertLessEqual(len(command.rstrip('\n')), 768)
        for label in ('L0', 'L01', 'L201', 'F', '', None):
            with self.subTest(label=label), self.assertRaises(ValueError): b.log_command_batch('a'*20, label)

if __name__ == '__main__': unittest.main(verbosity=2)
