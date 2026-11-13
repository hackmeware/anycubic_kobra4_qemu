#!/usr/bin/env python3
"""Inspect saved native homing state, never attach to or change a running MCU.

Main layouts: constructor 08006444, home 080061c8, samplers 08006a24/
080069c8. Motor layouts: docs/ROTOR-FEEDBACK-EVIDENCE.md and its assembly.
GPIO descriptors are software identities, not verified inter-board wiring.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

MAIN_SHA = '9bd702c8a076f29c0ac019cc7c8ea6c7afa52d13580fea04e977e3dce0a5d517'
MOTOR_SHA = '76b439293ab08207317007f5179243a0684c1b27668442781bcb2e201ff62661'
BASE = 0x20000000


def checked_firmware(path, expected):
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
        raise ValueError('Unrecognized firmware; refusing fixed layouts')


class Dump:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        self.sha = hashlib.sha256(self.data).hexdigest()

    def read(self, address, fmt):
        offset = address - BASE
        if offset < 0 or offset + struct.calcsize(fmt) > len(self.data):
            raise ValueError('Address outside saved SRAM: ' + hex(address))
        return struct.unpack_from(fmt, self.data, offset)[0]

    def u32(self, address):
        return self.read(address, '<I')

    def u8(self, address):
        return self.read(address, '<B')


def main_objects(firmware, sram):
    checked_firmware(firmware, MAIN_SHA)
    d = Dump(sram)
    if len(d.data) != 0x18000:
        raise ValueError('Expected 96 KiB main dump starting at 0x20000000')
    count, table = d.u8(BASE + 0x13c), d.u32(BASE + 0x140)
    records = []
    for oid in range(count):
        if d.u32(table + 8 * oid) != 0x08006445:
            continue
        obj = d.u32(table + 8 * oid + 4)
        d.u8(obj + 51)  # Validate entire constructor-sized object first.
        gpio, mask = d.u32(obj + 12), d.u32(obj + 16)
        valid = gpio in range(0x40010800, 0x40012400, 0x400) and 0 < mask <= 0x8000 and not mask & (mask - 1)
        pin = 'P' + chr(65 + (gpio - 0x40010800) // 0x400) + str(mask.bit_length() - 1) if valid else None
        records.append(dict(
            oid=oid, object=hex(obj), callback=hex(d.u32(obj + 4)),
            gpio_descriptor=hex(gpio), gpio_mask=hex(mask),
            configured_pin=pin, descriptor_is_gpio=valid,
            sampler_read_address=hex(gpio + 8), mode=d.u8(obj + 0x2a),
            motor_index_raw=d.u8(obj + 0x29),
            flags_raw=d.u8(obj + 0x24), requested_sample_count=d.u8(obj + 0x25),
            remaining_samples=d.u8(obj + 0x26), trigger_reason_raw=d.u8(obj + 0x27),
            trigger_object=hex(d.u32(obj + 0x20)),
            arm_counter_raw=d.u32(obj + 0x2c), disarm_counter_raw=d.u32(obj + 0x30),
            inter_board_connection_verified=False))
    return dict(firmware_sha256=MAIN_SHA, sram_sha256=d.sha, oid_count=count,
                oid_table=hex(table), endstops=records)


def motor_objects(firmware, sram):
    checked_firmware(firmware, MOTOR_SHA)
    d = Dump(sram)
    records = []
    for index in range(3):
        detector = BASE + 0x3a2c + index * 0x54
        records.append(dict(motor_index=index,
            commutation_dispatch_mode=d.u8(BASE + 0x0a + index),
            status_word_raw=hex(d.read(BASE + 0xc00 + index * 0x10, '<H')),
            detector_record=hex(detector), event_state_50_raw=d.u8(detector + 0x50),
            detector_state_51_raw=d.u8(detector + 0x51),
            static_output_pin=['PB5', 'PB4', 'PB15'][index],
            output_level_observed=None, inter_board_connection_verified=False))
    return dict(firmware_sha256=MOTOR_SHA, sram_sha256=d.sha, motors=records)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('main_firmware')
    p.add_argument('main_sram')
    p.add_argument('--motor-firmware')
    p.add_argument('--motor-sram')
    a = p.parse_args()
    if bool(a.motor_firmware) != bool(a.motor_sram):
        p.error('Supply both motor arguments or neither')
    out = dict(scope='Saved firmware state only; no inferred homing success, physical position, GPIO level or board wiring.',
               main=main_objects(a.main_firmware, a.main_sram))
    if a.motor_sram:
        out['motor'] = motor_objects(a.motor_firmware, a.motor_sram)
    print(json.dumps(out, indent=2))
