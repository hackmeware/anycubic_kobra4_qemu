#!/usr/bin/env python3
"""Bounded original-three-MCU idle startup. No QEMU, host replay, homing, heat or print request."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'rv1106-at32-link/scripts'))
sys.path.insert(0, str(ROOT / 'rv1106-at32-link/tests'))
from shared_mcu import prepare
from test_z_probe_profile import arguments
from z_probe_selection import final_commands

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--prepare-only', action='store_true', help='Generate preserved script, never execute Renode')
a = p.parse_args()
out = a.output.resolve()
if out.exists():
    raise SystemExit('Use a new output directory; prior evidence is never overwritten')
out.mkdir(parents=True)
# Preserve generated sources and exact script for this bounded run; no transient source references.
work = out / 'executor'
work.mkdir()
(work / 'home/.config').mkdir(parents=True)
args = arguments(work)
args.log_dir = out
args.nozzle_tmc_model = 'autobaud'
script, _ = prepare(args, work, [], ['emulation SetGlobalQuantum "0.000001"'])
setup = script.read_text().split('emulation RunFor "1"')[0]
lines = [setup]
for stage in ['zero', 'first-window']:
    if stage == 'first-window':
        lines += ['emulation RunFor "0.31"']
    lines += ['mach set "nozzle"', f'sysbus.sensor WriteStatus "{out}/{stage}-sensor-status.json"',
              'mach set "motor"', f'sysbus.zProfileEvidence WriteStatus "{out}/{stage}-force-status.json"']
lines += ['emulation RunFor "0.095"', final_commands(args),
          'echo "ORIGINAL THREE MCU IDLE STARTUP SMOKE COMPLETE AT 405 MS"', 'quit']
script = work / 'startup-only.resc'
script.write_text('\n'.join(lines) + '\n')
metadata = {'scope': 'Original three MCU binaries, standalone shared Renode idle startup405ms. No QEMU, external UART replay, host command, homing/heater/print request or native Z attempt.',
            'end_ns': 405000000, 'first_window_ns': 310000000,
            'firmware_sha256': {name: hashlib.sha256((ROOT / 'inputs' / name).read_bytes()).hexdigest() for name in ['mcu.bin', 'nozzle.bin', 'motor.bin']},
            'script_sha256': hashlib.sha256(script.read_bytes()).hexdigest(), 'prepared_only': a.prepare_only}
(out / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
if a.prepare_only:
    print(script)
    raise SystemExit(0)
env = dict(os.environ, HOME=str(work / 'home'), XDG_CONFIG_HOME=str(work / 'home/.config'), TMPDIR=str(work))
try:
    run = subprocess.run([str(ROOT / 'at32-runtime/renode_1.17.0-portable/renode'), '--disable-gui', '--console', str(script)],
                         env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=240)
except subprocess.TimeoutExpired as error:
    raw = error.stdout or b''
    (out / 'renode.log').write_bytes(raw.encode() if isinstance(raw, str) else raw)
    (out / 'result.json').write_text(json.dumps({'passed': False, 'error': 'wall-clock timeout240s; do not infer completion'}, indent=2) + '\n')
    raise
(out / 'renode.log').write_text(run.stdout)
result = {'returncode': run.returncode, 'completed': 'ORIGINAL THREE MCU IDLE STARTUP SMOKE COMPLETE AT 405 MS' in run.stdout,
          'monitor_error': any(s in run.stdout for s in ['There was an error', 'Errors during compilation', 'Error CS']),
          'observed': {name: json.loads((out / name).read_text()) for name in ['zero-sensor-status.json', 'zero-force-status.json',
              'first-window-sensor-status.json', 'first-window-force-status.json', 'z-sensor-status.json', 'z-force-status.json'] if (out / name).exists()}}
sensor = result['observed'].get('z-sensor-status.json', {})
force = result['observed'].get('z-force-status.json', {})
result['passed'] = bool(run.returncode == 0 and result['completed'] and not result['monitor_error'] and sensor.get('conversions', 0) > 0
                        and sensor.get('provider_calls', 0) > 0 and sensor.get('provider_failures', 1) == 0
                        and sensor.get('adapter_errors', 1) == 0 and sensor.get('protocol_errors', 1) == 0
                        and force.get('captures', 0) > 1 and force.get('samples_read', 0) > 0 and force.get('faulted', True) is False)
(out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'passed': result['passed'], 'completed': result['completed'], 'sensor': sensor, 'force': force}, indent=2))
if not result['passed']:
    raise SystemExit('Startup gate failed or incomplete; inspect evidence, do not widen age/skew bounds or fabricate captures')
