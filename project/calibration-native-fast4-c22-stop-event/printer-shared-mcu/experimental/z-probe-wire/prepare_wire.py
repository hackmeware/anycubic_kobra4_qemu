#!/usr/bin/env python3
"""Generate, never execute, an explicitly assumed noninverting PA7 -> PB2 fixture."""
import argparse
import hashlib
import json
import pathlib
import re


def valid_name(value):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise argparse.ArgumentTypeError('Use a simple Renode identifier')
    return value


def connect_commands(connector, return_machine):
    # Target selection MUST precede source attachment. Do not repeat SelectSourcePin.
    return [
        'mach set "main"',
        f'emulation CreateGPIOConnector "{connector}"',
        f'connector Connect sysbus.gpioB {connector}',
        f'{connector} SelectDestinationPin sysbus.gpioB 2',
        'mach set "nozzle"',
        f'connector Connect sysbus.gpioA {connector}',
        f'{connector} SelectSourcePin sysbus.gpioA 7',
        f'mach set "{return_machine}"',
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--assume-pa7-pb2-noninverting', action='store_true', required=True,
                        help='Explicit synthetic fixture assumption, not verified physical cable')
    parser.add_argument('--connector', type=valid_name, default='syntheticZProbe')
    parser.add_argument('--return-machine', choices=['main', 'nozzle', 'motor'], default='main')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    header = '''# EXPLICIT SYNTHETIC NONINVERTING FIXTURE; PHYSICAL CABLE UNVERIFIED.
# No firmware/PA7 writes, forced probe success, force/position shortcut or clock changes.
# Execute ONCE after both machines/GPIO overlays exist, before the first RunFor/start.
# Main PB2 remains subject to native GPIO configuration and original endstop logic.
# Do not re-select this source, reuse the connector, or silently continue after target reset.
'''
    (out/'connect.commands').write_text(header+'\n'.join(connect_commands(args.connector,args.return_machine))+'\n')
    (out/'disconnect.commands').write_text('''# OPTIONAL synthetic unplug, not firmware-trigger success.
# Requires emulation already paused at a queue-drained boundary; hot unplug is unverified.
# Destination-only detach avoids disturbing source observers. Retain dangling source sink.
# ReleasePin restores the actual target pull/floating behavior; it is not a forced level.
# Detach alone leaves the last external drive latched in AT32GPIO.
'''+f'''mach set "main"
{args.connector} DetachFrom sysbus.gpioB
sysbus.gpioB ReleasePin 2
mach set "{args.return_machine}"
''')
    manifest = {
        'explicit_experimental_only': True,
        'physical_cable_verified': False,
        'hardware_electrical_timing_fidelity': False,
        'source': 'nozzle.gpioA resolved PA7',
        'destination': 'main.gpioB external PB2',
        'inverted': False,
        'startup_only': True,
        'target_reset_requires_new_fixture_or_reviewed_reconnect': True,
        'files': {name: hashlib.sha256((out/name).read_bytes()).hexdigest()
                  for name in ['connect.commands','disconnect.commands']},
    }
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(out/'connect.commands')


if __name__ == '__main__':
    main()
