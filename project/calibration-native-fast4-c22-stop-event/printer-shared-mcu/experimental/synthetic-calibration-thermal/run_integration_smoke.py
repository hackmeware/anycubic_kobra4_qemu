#!/usr/bin/env python3
"""Load generated thermal + tested Z/autobaud composition at zero. NO firmware or execution."""
import argparse
import csv
import json
import os
from pathlib import Path
import re
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'rv1106-at32-link/scripts'), str(ROOT / 'rv1106-at32-link/tests')]
from shared_mcu import prepare
from test_thermal_profile import MAIN, NOZZLE
from test_z_probe_profile import arguments
from thermal_profile_selection import PROFILE, final_commands, sha
from z_probe_selection import final_commands as z_final
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args(); out = a.output.resolve()
if out.exists(): raise SystemExit('Use a new output directory; never overwrite earlier evidence')
out.mkdir(parents=True); work = out / 'executor'; work.mkdir()
(work / 'home/.config').mkdir(parents=True)
args = arguments(work); args.log_dir = out; args.thermal_profile = PROFILE; args.nozzle_tmc_model = 'autobaud'
script, _ = prepare(args, work, MAIN, NOZZLE)
setup = script.read_text().split('emulation RunFor "1"')[0]
lines = [line for line in setup.splitlines() if not line.startswith(('sysbus LoadBinary ', 'cpu VectorTableOffset ', 'cpu SP ', 'cpu PC '))]
lines += [final_commands(args), z_final(args), 'echo "THERMAL Z AUTOBAUD ZERO EPOCH NO FIRMWARE SMOKE COMPLETE"', 'quit']
text = '\n'.join(lines) + '\n'
assert 'LoadBinary' not in text and 'RunFor' not in text and '\nstart\n' not in text
resc = work / 'model-only.resc'; resc.write_text(text)
env = dict(os.environ, HOME=str(work / 'home'), XDG_CONFIG_HOME=str(work / 'home/.config'), TMPDIR=str(work))
run = subprocess.run([str(ROOT / 'at32-runtime/renode_1.17.0-portable/renode'), '--disable-gui', '--console', str(resc)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
(out / 'renode.log').write_text(run.stdout)
clean = re.sub(r'\x1b\[[0-9;]*m', '', run.stdout)
assert run.returncode == 0 and not re.search(r'error CS\d|Error while|Could not compile|Unhandled exception|There was an error|Errors during compilation|\[ERROR\]', clean), clean[-20000:]
assert 'THERMAL Z AUTOBAUD ZERO EPOCH NO FIRMWARE SMOKE COMPLETE' in clean
observed = {}
for name, code in [('nozzle', '4023'), ('bed', '3911')]:
    rows = list(csv.DictReader((out / (name + '-thermal-live.csv')).open()))
    assert rows and all(row['time_us'] == '0' and row['physical_temperature_c'] == '25' and row['published_adc_code'] == code for row in rows), rows
    assert all(row['sensor_fault'] == 'none' and row['model_overtemperature'] == '0' and row['model_heater_latched_off'] == '0' and row['last_heater_duty'] == '0' and row['last_fan_duty'] == '0' and row['thermal_updates'] == '0' for row in rows), rows
    status = json.loads((out / (name + '-thermal-live-status.json')).read_text())
    assert status['dropped_rows'] == status['stream_dropped_rows'] == status['stream_error_count'] == 0 and not status['stream_write_outcome_uncertain'], status
    observed[name] = {'rows': rows, 'status': status, 'binding': json.loads((out / (name + '-heater-binding.json')).read_text())}
sensor = json.loads((out / 'z-sensor-status.json').read_text()); force = json.loads((out / 'z-force-status.json').read_text())
assert sensor['timed_provider_bound'] and sensor['now_ns'] == 0 and sensor['conversions'] == 0 and sensor['provider_calls'] == 0 and sensor['adapter_errors'] == 0
assert force['bound'] and force['registered'] and force['fixture_enabled'] and not force['faulted'] and force['now_ns'] == 0 and force['captures'] == 1
assert force['maximum_state_age_ns'] == 100000 and force['maximum_producer_lead_ns'] == 1000
summary = {'passed': True, 'scope': 'Generated three-MCU platform load at zero; NO firmware loaded, no CPU execution, no time advance, no native heating/calibration claim.', 'observed': observed, 'z_sensor': sensor, 'z_force': force, 'script_sha256': sha(resc)}
(out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print('PASS: thermal/Z/autobaud generated composition, zero-epoch original ADC codes, guards clear, exclusive actual-pad bindings, no firmware or time advance')
