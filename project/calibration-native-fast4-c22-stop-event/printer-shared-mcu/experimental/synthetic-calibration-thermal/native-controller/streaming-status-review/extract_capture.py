"""Offline deterministic fixture extraction; never starts a native process/RPC."""
import hashlib
import importlib.util
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[4]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def sha(data):
    return hashlib.sha256(data).hexdigest()

def main():
    ready = load('capture_ready', ROOT / 'rv1106-at32-link/scripts/run_native_ready_observation.py')
    temps = load('capture_temps', HERE.parent / 'schema-temperature/temperature_schema.py')
    run = ROOT / 'runs/native-nozzle-230-synthetic-r2'
    console = (run / 'console.bin').read_bytes()
    observation = (run / 'thermal-observation.json').read_bytes()
    report = json.loads(observation)
    request = next(r for r in report['requests'] if r['stage'] == 'status001')
    # Decode without universal-newline conversion, preserving original region text.
    region = ready.bounded_region(console.decode('utf-8', errors='strict'), request['begin'], request['end'])
    raw = ready.bounded_region(region, ready.RAW_BEGIN, ready.RAW_END)
    data = ready.read_od(raw)
    (HERE / 'r2-full-stream.http2.bin').write_bytes(data)
    pos = 0
    frames, messages = [], []
    pending = b''
    first_end = None
    while pos < len(data):
        assert len(data) - pos >= 9
        size = int.from_bytes(data[pos:pos+3], 'big')
        kind, flags = data[pos+3:pos+5]
        stream = int.from_bytes(data[pos+5:pos+9], 'big')
        end = pos + 9 + size
        assert end <= len(data)
        frames.append(dict(offset=pos, end=end, size=size, type=kind, flags=flags, stream=stream))
        if kind == 0 and stream == 1:
            assert flags == 0, 'Fixture extractor handles observed unpadded, nonterminal DATA only'
            pending += data[pos+9:end]
            while len(pending) >= 5:
                length = int.from_bytes(pending[1:5], 'big')
                if len(pending) < 5 + length:
                    break
                assert pending[0] == 0
                protobuf = pending[5:5+length]
                pending = pending[5+length:]
                status = temps._nested(protobuf, (1,))[1]
                heaters = temps._nested(status, (2, 3))
                presence = {}
                for name, field in (('nozzle', 2), ('bed', 3)):
                    values = temps._selected(heaters[field], (1, 2), 0)
                    presence[name] = dict(current_field_present=1 in values, target_field_present=2 in values)
                index = len(messages) + 1
                filename = f'r2-message-{index:02d}.protobuf.bin'
                (HERE / filename).write_bytes(protobuf)
                messages.append(dict(index=index, completed_at_http2_offset=end, filename=filename,
                    protobuf_sha256=sha(protobuf), protobuf_length=len(protobuf),
                    temperatures=temps.decode_get_status_temperatures(protobuf), scalar_presence=presence))
                if first_end is None:
                    assert not pending, 'First frame also contains additional message bytes'
                    first_end = end
        pos = end
    assert not pending and first_end is not None
    prefix = data[:first_end]
    (HERE / 'r2-first-message-prefix.http2.bin').write_bytes(prefix)
    statuses = {k: re.findall(r'(?m)^'+k+r'=(\d+)\r?$', region)
                for k in ('READY_CLIENT_STATUS', 'GRPC_PROBE_TRANSPORT_EXIT')}
    result = dict(source_run=str(run.relative_to(ROOT)), console_sha256=sha(console),
        observation_sha256=sha(observation), begin_marker=request['begin'], end_marker=request['end'],
        original_statuses=statuses, original_error=report['error'],
        original_request_method=request['method'], request_protobuf_hex=request['protobuf_hex'],
        original_client_timeout_guest_seconds=request['client_timeout_guest_seconds'],
        files={'r2-full-stream.http2.bin':dict(length=len(data),sha256=sha(data)),
               'r2-first-message-prefix.http2.bin':dict(length=len(prefix),sha256=sha(prefix))},
        frames=frames, messages=messages,
        caveat='The first-message prefix is an offline snapshot fixture, not proof that the timed-out r2 request succeeded. No END_STREAM/trailers present. Full original capture and status 143 preserved. First message scalar absence means proto3 zero, not verified live sensor readiness.',
        correction='Earlier recovery correctly mapped temperature fields but omitted RPC cardinality. Treating GetStatus as unary was incorrect; its server-streaming handler sends recurring messages. r2 timed out before heating. No new native execution performed.')
    (HERE/'capture-evidence.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result['files'],indent=2))

if __name__ == '__main__':
    main()
