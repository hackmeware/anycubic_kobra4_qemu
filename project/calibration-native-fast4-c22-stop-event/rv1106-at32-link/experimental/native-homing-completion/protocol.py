"""Fixed native-homing boundary; source loading and generation are offline only."""
import ast
import json
import re
import hashlib
import types
from pathlib import Path
BASE = 'rv1106-at32-link/experimental/sensor30-observation/'
PINS = {BASE + 'observer.py': '04311b970f4f1d250cb4d7ac2cc340275a616f1568a7ace9e81108d0d0723db9', BASE + 'protocol.py': '306495b2a0f714d9114b5c5cd454ef7a5535b6515e5574ec2826965a71893d73'}
XYZ_RELATIVE = 'rv1106-at32-link/scripts/run_native_xyz_observation.py'
PINS[XYZ_RELATIVE] = '5715bd6e8ac16e02b7b7b42fdfce50f75bf3af585269ea68f84e8cdace219153'
LOG_BATCH_LIMIT = 200
STAGES = ('ready', 'baseline', 'home_x', 'status_x', 'home_y', 'status_y', 'home_z', 'status_z')

def load(root):
    modules = []
    for relative in (BASE + 'protocol.py', BASE + 'observer.py'):
        path = Path(root) / relative
        data = path.read_bytes()
        if path.is_symlink() or hashlib.sha256(data).hexdigest() != PINS[relative]:
            raise ValueError('Pinned source mismatch: ' + relative)
        module = types.ModuleType('homing_pinned_' + path.stem)
        module.__file__ = str(path)
        exec(compile(data, str(path), 'exec'), module.__dict__)
        modules.append(module)
    modules[0].load_helpers()
    path = Path(root) / XYZ_RELATIVE
    source = path.read_bytes()
    if path.is_symlink() or hashlib.sha256(source).hexdigest() != PINS[XYZ_RELATIVE]:
        raise ValueError('Pinned XYZ schema/profile source mismatch')
    tree = ast.parse(source, filename=str(path))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ('validate_tmc_manifest', 'validate_profile')]
    if len(selected) != 2:
        raise ValueError('XYZ profile validator source structure changed')
    namespace = {'json': json, 're': re, 'PROFILE': 'synthetic-functional'}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), namespace)
    boundary = Boundary(modules[0])
    boundary.validate_profile = lambda directory: namespace['validate_profile'](directory, 'autobaud')
    return boundary, modules[1]

class Boundary:
    def __init__(self, protocol):
        self.p = protocol

    def log_command_batch(self, token, label):
        """Cold-only finite L1..L200 boundary; original helper stays immutable.

        Same two read-only tails, octal-only marker prefix, fixed suffix helper,
        one-line rendering and TTY cap as the pinned sensor30 log formatter.
        Its older L20 prefix allowlist cannot be reused for the new budget.
        """
        self.p.markers(token, 'PrinterState')
        if type(label) is not str or re.fullmatch(r'L(?:[1-9]|[1-9][0-9]|1[0-9]{2}|200)', label) is None:
            raise ValueError('Only cold log labels L1 through L200 are permitted')
        prefix = 'AMB_' + token + '_' + label
        setup = "AMBIENT_MARKER=$(printf '" + ''.join('\\%03o' % byte for byte in prefix.encode('ascii')) + "')"
        suffix = [setup, self.p._marker_line('B'),
                  'tail -100 /data/main.stdout', 'tail -100 /data/logs/avata_main.log', self.p._marker_line('E')]
        line = '; '.join(suffix)
        if len(line) > 768:
            raise ValueError('Compound capture suffix exceeds reviewed TTY bound')
        return line + '\n'

    def mode(self, stage):
        if stage not in STAGES:
            raise ValueError('Unknown fixed stage')
        return 'GetStatus' if stage in ('baseline', 'status_x', 'status_y', 'status_z') else 'PrinterState'

    def packet(self, stage):
        mode = self.mode(stage)
        if stage == 'ready' or mode == 'GetStatus':
            return self.p.request_packet(mode)
        method = 'Homing'
        value = stage[-1].upper().encode('ascii')
        protobuf = b'\x0a' + bytes([len(value)]) + value
        def string(value):
            return bytes([len(value)]) + value
        headers = (b'\x83\x86\x04' + string(b'/applink.AppLinkService/' + method.encode()) +
                   b'\x01' + string(b'127.0.0.1:50051') + b'\x0f\x10' + string(b'application/grpc') +
                   b'\x00' + string(b'te') + string(b'trailers'))
        return self.p.PREFACE + self.p.frame(4, 0, 0) + self.p.frame(1, 4, 1, headers) + self.p.frame(0, 1, 1, b'\0' + len(protobuf).to_bytes(4, 'big') + protobuf)

    def build(self, stage):
        packet = self.packet(stage)
        base, snapshot, _ = self.p.load_helpers()
        client = snapshot.build_snapshot(packet) if self.mode(stage) == 'GetStatus' else base.build(packet)
        if base.extract_packet(client) != packet or client.count(self.p.PREFACE) != 1:
            raise ValueError('Client request identity mismatch')
        return packet, client

    def commands(self, stage, token, client):
        if client != self.build(stage)[1]:
            raise ValueError('Client substitution')
        mode = self.mode(stage)
        mark = self.p.markers(token, mode)
        path = '/tmp/amb_' + token + ('_s' if mode == 'GetStatus' else '_p')
        lines = ["printf '" + ''.join('\\%03o' % byte for byte in client[off:off + 64]) + "' " + ('>' if off == 0 else '>>') + ' ' + path for off in range(0, len(client), 64)]
        suffix = [f'chmod +x {path}', self.p._marker_setup(mark['begin'][:-2]), self.p._marker_line('B'), 'cat /proc/uptime', f'timeout -t 5 {path} > {path}.out', 'AMBIENT_EXIT=$?', self.p._marker_line('X'), self.p._marker_line('RB'), f'od -v -b {path}.out', self.p._marker_line('RE'), 'cat /proc/uptime', self.p._marker_line('E')]
        line = '; '.join(suffix)
        if len(line) > 768:
            raise ValueError('TTY suffix too long')
        return '\n'.join(lines + [line]) + '\n'

    def verify_wire(self, stage, wire):
        mode = self.mode(stage)
        messages = self.p.response_messages(wire, mode)
        if stage == 'ready':
            return {'api_response': self.p.state_payload(messages[0]), 'terminal_grpc_status': 0}
        if mode == 'GetStatus':
            observations = [self.p.decode_status(message) for message in messages]
            # Preserve the reviewed first-default/second-selected semantics.
            # Selection is strictly by sequence, never by desired value.
            for index, sample in enumerate(observations):
                self.p.validate_sensor30(sample, selected=index == 1)
            return {'temperatures': observations, 'selected_temperatures': observations[1], 'local_cancel_frame_sent': True, 'native_sensor_acquisition_timestamp': None}
        if messages != [b'']:
            raise ValueError('Nonempty/ambiguous generic response; no retry')
        return {'rpc_acceptance_verified': True, 'physical_completion_proven_by_rpc': False, 'response_protobuf_hex': ''}

    def capture(self, stage, token, text):
        extracted = self.p.capture_transport(text, self.mode(stage), token)
        if extracted is None:
            return None
        wire, uptimes, exit_code = extracted
        result = self.verify_wire(stage, wire)
        return dict(result, physical_completion_proven=False, wire_hex=wire.hex(), wire_sha256=hashlib.sha256(wire).hexdigest(), guest_uptime_seconds=uptimes, client_exit_status=exit_code, transport_exit_status=exit_code)
