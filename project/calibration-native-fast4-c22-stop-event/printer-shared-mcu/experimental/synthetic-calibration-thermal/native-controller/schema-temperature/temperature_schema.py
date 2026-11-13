"""Read-only GetStatus protobuf decoder. See evidence.json for exact native build.

GetStatus is SERVER-STREAMING; this decoder handles one message only, never
unary RPC completion. Transport cardinality was omitted in the initial recovery
and is corrected by streaming-status-review/cardinality-source-evidence.json.
Input is protobuf payload, NOT the five-byte gRPC message envelope.
Native reports whole degrees (round(double), then signed int32).
Strict observer policy rejects ambiguous duplicates, missing nested messages,
wrong wire types, groups, truncated values, and malformed varints. Omitted
scalar temperatures have protobuf default zero, not a missing-sensor meaning.
No transport, controller, or printer-side actions are performed here.
"""
RPC_METHOD = '/applink.AppLinkService/GetStatus'
REQUEST = b''
RPC_CARDINALITY = 'server_streaming'

class DecodeError(ValueError):
    pass

def _varint(data, pos):
    value = 0
    start = pos
    for shift in range(0, 70, 7):
        if pos == len(data):
            raise DecodeError('truncated varint')
        byte = data[pos]
        pos += 1
        if shift == 63 and byte > 1:
            raise DecodeError('varint exceeds uint64')
        value |= (byte & 127) << shift
        if byte < 128:
            if pos - start > 1 and byte == 0:
                raise DecodeError('noncanonical varint')
            return value, pos
    raise DecodeError('unterminated varint')

def _fields(data):
    pos = 0
    while pos < len(data):
        tag, pos = _varint(data, pos)
        number, wire = tag >> 3, tag & 7
        if not 1 <= number <= 0x1fffffff:
            raise DecodeError('invalid field number')
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire in (1, 2, 5):
            if wire == 2:
                size, pos = _varint(data, pos)
            else:
                size = 8 if wire == 1 else 4
            end = pos + size
            if end > len(data):
                raise DecodeError('truncated field')
            value, pos = data[pos:end], end
        else:
            raise DecodeError('unsupported protobuf wire type')
        yield number, wire, value

def _selected(data, wanted, wire):
    out = {}
    for number, actual, value in _fields(data):
        if number in wanted:
            if actual != wire or number in out:
                raise DecodeError('wrong wire type or duplicate observed field')
            out[number] = value
    return out

def _nested(data, wanted):
    out = _selected(data, wanted, 2)
    if set(out) != set(wanted):
        raise DecodeError('required nested status missing')
    return out

def _int32(value):
    if value <= 0x7fffffff:
        return value
    if value >= 0xffffffff80000000:
        return value - (1 << 64)
    raise DecodeError('noncanonical signed int32')

def decode_get_status_temperatures(payload):
    """Return {'nozzle': {'current': int, 'target': int}, 'bed': {...}}.

    Absence of a required heater/status message raises DecodeError. Integer
    values are native rounded readings, not inferred ADC/model temperatures.
    """
    if not isinstance(payload, bytes):
        raise TypeError('payload must be bytes')
    if len(payload) > 4 * 1024 * 1024:
        raise DecodeError('response exceeds observer limit')
    status = _nested(payload, (1,))[1]
    heaters = _nested(status, (2, 3))
    result = {}
    for name, field in (('nozzle', 2), ('bed', 3)):
        values = _selected(heaters[field], (1, 2), 0)
        result[name] = {'current': _int32(values.get(1, 0)),
                        'target': _int32(values.get(2, 0))}
    return result
