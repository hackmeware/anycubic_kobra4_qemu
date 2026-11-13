"""Pure acceptance for physical-only observations. Never touches a plant/model."""
from decimal import Decimal
import csv
import io
import math

AXIS_FIELDS = ('state_time_s', 'angle_rad', 'relative_mm', 'velocity_rad_s', 'contact_torque_nm', 'bridge_enabled')
HEADER = ['sequence', 'observation_time_s'] + [a + '_' + f for a in 'xyz' for f in AXIS_FIELDS] + ['z_bed_clearance_mm', 'z_compression_mm', 'z_contact_force_n', 'z_contact_nonzero']
MAX_GAP = .025

class Physical:
    def __init__(self):
        self.prefix = b''
        self.rows = []
        self.last_growth = None
        self.baseline = None
        self.prerelease_rows = []
        self.release_rows = []
        self.settled_start = None
        self.clear_start = None
        self.ever_clear = False

    def consume(self, data, shared_ns, *, final=False, require_fresh=True):
        if not data.startswith(self.prefix) or final and not data.endswith(b'\n'):
            raise ValueError('Physical trace replaced/truncated/incomplete final tail')
        if data == self.prefix:
            if require_fresh:
                self.fresh(shared_ns)
            return
        self.prefix = data
        complete = data[:data.rfind(b'\n') + 1]
        if not complete:
            return
        reader = csv.DictReader(io.StringIO(complete.decode('ascii')))
        if reader.fieldnames != HEADER:
            raise ValueError('Physical header mismatch')
        rows = list(reader)
        if len(rows) < len(self.rows):
            raise ValueError('Physical rows lost')
        for raw in rows[len(self.rows):]:
            row = self.parse(raw)
            if not self.rows and row['sequence'] != 0:
                raise ValueError('Missing first physical sample')
            if self.rows:
                previous = self.rows[-1]
                gap = row['observation_time_s'] - previous['observation_time_s']
                if row['sequence'] != previous['sequence'] + 1 or gap <= 0 or previous['sequence'] != 0 and gap > MAX_GAP:
                    raise ValueError('Physical sequence/time/gap failure')
                for a in 'xyz':
                    if row[a + '_state_time_s'] < previous[a + '_state_time_s']:
                        raise ValueError('Physical axis time regressed')
            self.rows.append(row)
            self.last_growth = shared_ns
            if self.baseline is not None:
                self.observe_release(row)
        if require_fresh:
            self.fresh(shared_ns)

    @staticmethod
    def parse(raw):
        if set(raw) != set(HEADER) or None in raw.values():
            raise ValueError('Malformed physical row')
        row = {}
        for key, value in raw.items():
            if key in ('sequence', 'z_contact_nonzero') or key.endswith('bridge_enabled'):
                if value not in ('0', '1') and key != 'sequence':
                    raise ValueError('Physical boolean is not canonical')
                if not value.isdigit():
                    raise ValueError('Physical integer invalid')
                row[key] = int(value)
            else:
                row[key] = float(value)
                if not math.isfinite(row[key]):
                    raise ValueError('Physical nonfinite value')
        now = row['observation_time_s']
        if now < 0:
            raise ValueError('Negative source time')
        for a in 'xyz':
            age = now - row[a + '_state_time_s']
            if not -0.000001001 <= age <= 0.000100001:
                raise ValueError('Stale/future physical state')
        z = row['z_relative_mm']
        expected_clearance = z + 10.0
        expected_compression = max(0.0, -expected_clearance)
        force = row['z_contact_force_n']
        if abs(row['z_bed_clearance_mm'] - expected_clearance) > 1e-8 or abs(row['z_compression_mm'] - expected_compression) > 1e-8:
            raise ValueError('Fixture geometry mismatch')
        if force < 0 or force > 5 or row['z_contact_nonzero'] != int(force != 0):
            raise ValueError('Contact force limit/state mismatch')
        if abs(force - max(0.0, row['z_contact_torque_nm'] * 2 * math.pi / .008)) > 1e-7:
            raise ValueError('Contact torque/force mismatch')
        row['z_velocity_mm_s'] = row['z_velocity_rad_s'] * 8 / (2 * math.pi)
        return row

    def fresh(self, shared_ns):
        if not self.rows or self.last_growth is None or shared_ns - self.last_growth > 100_000_000:
            raise ValueError('Required physical trace missing/stale')

    def motion_ready(self):
        # Sequence zero is an attachment snapshot, not proof of native cadence.
        return len(self.rows) >= 2 and self.rows[-1]['observation_time_s'] - self.rows[1]['observation_time_s'] >= .25

    def prerelease(self, floor_s):
        candidates = [r for r in self.rows if r['observation_time_s'] >= floor_s]
        start = None
        for row in candidates:
            valid = (0 < row['z_contact_force_n'] <= 5 and .005 <= row['z_compression_mm'] <= .25 and abs(row['z_velocity_mm_s']) < .05)
            start = row['observation_time_s'] if valid and start is None else start if valid else None
        return start is not None and candidates[-1]['observation_time_s'] - start >= .25

    def latest_window(self, *, floor_s=0., seconds=.25):
        # Minimal qualifying suffix only; complete rows remain in self.rows and
        # the immutable raw CSV for continuous validation/artifact replay.
        if not self.rows:
            raise ValueError('No physical hold window')
        end = self.rows[-1]['observation_time_s']
        for index in range(len(self.rows) - 1, -1, -1):
            candidate = self.rows[index]
            if candidate['sequence'] < 1 or candidate['observation_time_s'] < floor_s:
                break
            if end - candidate['observation_time_s'] >= seconds:
                return self.rows[index:].copy()
        raise ValueError('Insufficient contiguous physical hold window')

    def arm(self, floor_s):
        if self.baseline is not None or not self.prerelease(floor_s):
            raise ValueError('Release prerelease settle absent/repeated')
        self.prerelease_rows = self.latest_window(floor_s=floor_s)
        self.baseline = dict(self.rows[-1])

    def observe_release(self, row):
        base = self.baseline
        dz = row['z_relative_mm'] - base['z_relative_mm']
        if dz < -.05 or dz > 1.25:
            raise ValueError('Wrong-sign/excess physical Z displacement')
        if any(abs(row[a + '_relative_mm'] - base[a + '_relative_mm']) > .05 for a in 'xy'):
            raise ValueError('Unexpected physical XY travel')
        if self.ever_clear and row['z_contact_nonzero']:
            raise ValueError('Recontact after release')
        if not row['z_contact_nonzero']:
            self.ever_clear = True
        good = (.8 <= dz <= 1.2 and row['z_bed_clearance_mm'] >= .5 and row['z_contact_force_n'] == 0 and row['z_contact_nonzero'] == 0 and abs(row['z_velocity_mm_s']) < .05)
        self.clear_start = row['observation_time_s'] if good and self.clear_start is None else self.clear_start if good else None
        self.release_rows.append(row)

    def complete(self):
        return bool(self.release_rows and self.clear_start is not None and self.release_rows[-1]['observation_time_s'] - self.clear_start >= .5)

    def summary(self):
        return {'baseline': self.baseline, 'prerelease_rows': self.prerelease_rows, 'final': self.release_rows[-1] if self.release_rows else None, 'release_rows': self.release_rows, 'settled_clearance_proven': self.complete(), 'direction': 'positive physical Z away from fixed min-side bed' if self.complete() else 'unproven', 'host_coordinates_equated_to_physical': False}

def validate_status(status, count, *, final=False):
    if not isinstance(status, dict):
        raise ValueError('Missing physical status')
    for key in ('dropped_rows', 'error_count'):
        if type(status.get(key)) is not int or status[key] != 0:
            raise ValueError('Physical trace lost/error rows')
    if status.get('capacity_reached') is not False or status.get('last_error') not in ('', None):
        raise ValueError('Physical trace capacity/error')
    if type(status.get('rows_written')) is not int or status['rows_written'] < count:
        raise ValueError('Physical status row count')
    if final and (status.get('stopped') is not True or status['rows_written'] != count):
        raise ValueError('Physical final status incomplete')

class Probe:
    HEADER = ['virtual_time_s', 'sequence', 'kind', 'label', 'pin', 'level']
    def __init__(self, label, pin):
        self.label, self.pin = label, str(pin)
        self.prefix = b''
        self.rows = []
        self.armed_count = None

    def consume(self, data, *, final=False):
        if not data.startswith(self.prefix) or final and not data.endswith(b'\n'):
            raise ValueError('Probe stream truncated/replaced')
        self.prefix = data
        complete = data[:data.rfind(b'\n') + 1].decode('ascii')
        lines = complete.splitlines()
        if not lines or lines[0] != '# PASSIVE GPIO EDGE TRACE v1; source-local virtual timestamps; no SyncTime or signal writes':
            raise ValueError('Probe provenance header')
        reader = csv.DictReader(lines[1:])
        if reader.fieldnames != self.HEADER:
            raise ValueError('Probe header')
        rows = list(reader)
        for index, row in enumerate(rows):
            if set(row) != set(self.HEADER) or row['label'] != self.label or row['pin'] != self.pin or row['level'] not in ('0', '1') or row['sequence'] != str(index):
                raise ValueError('Probe row identity')
            stamp = float(row['virtual_time_s'])
            if not math.isfinite(stamp) or stamp < 0 or row['kind'] != ('initial' if index == 0 else 'edge'):
                raise ValueError('Probe source time/event')
            if index and (stamp < float(rows[index-1]['virtual_time_s']) or row['level'] == rows[index-1]['level']):
                raise ValueError('Probe edge ordering')
        if self.armed_count is not None and len(rows) != self.armed_count:
            raise ValueError('Extra post-release probe edge/pulse')
        self.rows = rows

    def arm(self):
        if self.armed_count is not None or not self.rows or self.rows[-1]['level'] != '0':
            raise ValueError('Probe not low/rearmed at release baseline')
        self.armed_count = len(self.rows)

    def summary(self):
        return {'label': self.label, 'pin': self.pin, 'armed_count': self.armed_count, 'rows': self.rows}

CONTACT_HEADER = ['observation_time_s', 'previous_integration_time_s', 'state_time_s', 'axis', 'kind', 'contact_nonzero', 'angle_rad', 'velocity_rad_s', 'relative_mm', 'contact_torque_nm']

def validate_contacts(data, release_s, expected_count):
    if not data.endswith(b'\n'):
        raise ValueError('Incomplete final contact trace')
    reader = csv.DictReader(io.StringIO(data.decode('ascii')))
    if reader.fieldnames != CONTACT_HEADER:
        raise ValueError('Contact trace schema')
    rows = list(reader)
    if len(rows) != expected_count or len(rows) < 3:
        raise ValueError('Contact trace row count')
    levels = {}
    last_time = {}
    release_seen = False
    for row in rows:
        if set(row) != set(CONTACT_HEADER) or None in row.values() or row['axis'] not in ('0', '1', '2') or row['contact_nonzero'] not in ('0', '1'):
            raise ValueError('Malformed contact trace')
        axis = row['axis']
        values = {k: float(row[k]) for k in CONTACT_HEADER if k not in ('axis', 'kind', 'contact_nonzero')}
        if any(not math.isfinite(v) for v in values.values()):
            raise ValueError('Nonfinite contact trace')
        stamp = values['observation_time_s']
        if stamp < 0 or stamp < last_time.get(axis, 0) or not values['previous_integration_time_s'] <= values['state_time_s'] <= stamp + 1e-6:
            raise ValueError('Contact clock ordering')
        initial = axis not in levels
        if row['kind'] != ('initial' if initial else 'transition') or not initial and row['contact_nonzero'] == levels[axis]:
            raise ValueError('Contact transition sequence')
        if (values['contact_torque_nm'] != 0) != (row['contact_nonzero'] == '1'):
            raise ValueError('Contact torque flag disagreement')
        if axis == '2' and stamp > release_s:
            if row['contact_nonzero'] == '1':
                raise ValueError('Post-release contact entry/recontact')
            release_seen = True
        levels[axis] = row['contact_nonzero']
        last_time[axis] = stamp
    if set(levels) != {'0', '1', '2'} or levels['2'] != '0' or not release_seen:
        raise ValueError('No complete Z contact release transition')
    return True


def final_health(text, probes):
    import re
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text).replace('\r', '')
    def envelope(name):
        begin, end = 'COLD_' + name + '_BEGIN', 'COLD_' + name + '_END'
        starts = list(re.finditer(r'(?m)^' + re.escape(begin) + r'\n', text))
        ends = list(re.finditer(r'(?m)^' + re.escape(end) + r'\n', text))
        if len(starts) != 1 or len(ends) != 1 or ends[0].start() < starts[0].end():
            raise ValueError('Missing/duplicate final health envelope')
        return text[starts[0].end():ends[0].start()].splitlines()
    def number(value):
        # Monitor numeric getters render either decimal or explicit hex.
        if not re.fullmatch(r'(?:0|[1-9][0-9]*|0x[0-9A-Fa-f]+)', value):
            raise ValueError('Malformed getter integer')
        return int(value, 16 if value.startswith('0x') else 10)
    result = {}
    for board, filename in [('nozzle', 'nozzle-z-probe-edges.csv'), ('main', 'main-z-probe-edges.csv')]:
        values = envelope('PROBE_' + board)
        if len(values) != 7 or values[:2] != ['True', 'False'] or values[5:] != ['False', '']:
            raise ValueError('Probe final enabled/capacity/error state')
        count, drops, edges = map(number, values[2:5])
        if count != len(probes[filename].rows) or drops != 0 or edges != count - 1:
            raise ValueError('Probe final loss/counter mismatch')
        result[board] = {'rows': count, 'edges': edges, 'drops': drops, 'stopped': True}
    values = envelope('CONTACT')
    if len(values) != 4 or values[0] != 'False' or values[3] != '' or number(values[2]) != 0:
        raise ValueError('Contact final loss/error/stopped state')
    result['contact_rows'] = number(values[1])
    return result


def paired_z_pulses(probes, floors):
    streams = []
    for filename in ('nozzle-z-probe-edges.csv', 'main-z-probe-edges.csv'):
        rows = probes[filename].rows
        floor = floors.get(filename)
        if type(floor) is not int or floor < 1 or floor >= len(rows) or rows[floor - 1]['level'] != '0':
            raise ValueError('Missing fresh Z probe baseline/pulses')
        selected = rows[floor:]
        if len(selected) < 2 or len(selected) % 2 or [r['level'] for r in selected] != ['1','0'] * (len(selected)//2):
            raise ValueError('Unpaired/reordered Z probe pulse')
        if any(float(r['virtual_time_s']) < float(rows[floor-1]['virtual_time_s']) for r in selected):
            raise ValueError('Old Z probe source evidence')
        streams.append(selected)
    if len(streams[0]) != len(streams[1]):
        raise ValueError('Unmatched PA7/PB2 pulse count')
    for source, destination in zip(*streams):
        if source['level'] != destination['level'] or abs(Decimal(source['virtual_time_s']) - Decimal(destination['virtual_time_s'])) > Decimal('.000001'):
            raise ValueError('PA7/PB2 connector order/timing mismatch')
    return len(streams[0]) // 2
