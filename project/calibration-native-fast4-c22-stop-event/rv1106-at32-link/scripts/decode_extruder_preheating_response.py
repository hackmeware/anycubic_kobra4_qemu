#!/usr/bin/env python3
"""Decode the statically recovered response schema, without any I/O to a printer.

Input must be one reassembled response protobuf or one uncompressed gRPC message,
not a TCP/HTTP2 frame. Transport status and actual thermal state are separate.
Original scalar source names are unavailable; error_code is a diagnostic alias.
"""
import argparse
import json


def _varint(data, pos):
    value = 0
    for shift in range(0, 70, 7):
        if pos == len(data):
            raise ValueError('truncated varint')
        byte = data[pos]
        pos += 1
        if shift == 63 and byte > 1:
            raise ValueError('varint exceeds 64 bits')
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
    raise ValueError('unterminated varint')


def _fields(data):
    pos = 0
    while pos < len(data):
        tag, pos = _varint(data, pos)
        number, wire = tag >> 3, tag & 7
        if number == 0 or number > 0x1fffffff:
            raise ValueError('invalid protobuf field number')
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire in (1, 2, 5):
            if wire == 2:
                size, pos = _varint(data, pos)
            else:
                size = 8 if wire == 1 else 4
            if size > len(data) - pos:
                raise ValueError('truncated protobuf field')
            value, pos = data[pos:pos + size], pos + size
        else:
            raise ValueError('unsupported protobuf wire type')
        yield number, wire, value


def decode_response(data):
    result = {'error_present': False, 'error_code': 0, 'error_message': ''}
    for number, wire, value in _fields(data):
        if number != 1:
            continue
        if wire != 2:
            raise ValueError('response field 1 must be an ErrorMessage')
        result['error_present'] = True
        for error_number, error_wire, error_value in _fields(value):
            if error_number == 1:
                if error_wire != 0 or error_value > 0xffffffff:
                    raise ValueError('ErrorMessage field 1 must be a 32-bit varint')
                result['error_code'] = error_value
            elif error_number == 2:
                if error_wire != 2:
                    raise ValueError('ErrorMessage field 2 must be a string')
                result['error_message'] = error_value.decode('utf-8')
    result['error_reported'] = bool(result['error_code'] or result['error_message'])
    return result


def decode_grpc_message(data):
    if len(data) < 5:
        raise ValueError('truncated gRPC header')
    if data[0] != 0:
        raise ValueError('only uncompressed gRPC messages are supported')
    if int.from_bytes(data[1:5], 'big') != len(data) - 5:
        raise ValueError('gRPC message length mismatch; reassemble exactly one message')
    return decode_response(data[5:])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--protobuf-hex')
    group.add_argument('--grpc-message-hex')
    args = parser.parse_args()
    try:
        result = (decode_response(bytes.fromhex(args.protobuf_hex))
                  if args.protobuf_hex is not None
                  else decode_grpc_message(bytes.fromhex(args.grpc_message_hex)))
    except (ValueError, UnicodeError) as error:
        parser.error(str(error))
    result['scope'] = 'Schema decode only. Check gRPC status, native target and actual GPIO/thermal evidence separately.'
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
