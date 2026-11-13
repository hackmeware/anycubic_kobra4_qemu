#!/usr/bin/env python3
"""Load the selected generated three-MCU models at zero, with NO firmware or time advance."""
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

OUT = ROOT / 'evidence/synthetic-z-profile-integration/model-smoke'
OUT.mkdir(parents=True, exist_ok=True)
if any(OUT.glob('z-*.json')):
    raise SystemExit('Prior model smoke exports exist; archive before rerunning, never reuse evidence')
with tempfile.TemporaryDirectory(prefix='z-profile-model-') as folder:
    tmp = Path(folder)
    (tmp / 'home/.config').mkdir(parents=True)
    args = arguments(tmp)
    args.log_dir = OUT
    args.nozzle_tmc_model = 'autobaud'
    script, _ = prepare(args, tmp, [], ['emulation SetGlobalQuantum "0.000001"'])
    setup = script.read_text().split('emulation RunFor "1"')[0]
    lines = [line for line in setup.splitlines() if not line.startswith(('sysbus LoadBinary ', 'cpu VectorTableOffset ', 'cpu SP ', 'cpu PC '))]
    # Platforms contain CPUs, but no firmware is loaded and no execution/time advance is requested.
    lines += [final_commands(args), 'echo "SYNTHETIC Z GENERATED MODEL ZERO-EPOCH LOAD COMPLETE"', 'quit']
    text = '\n'.join(lines) + '\n'
    assert 'LoadBinary' not in text and 'RunFor' not in text and '\nstart\n' not in text
    resc = tmp / 'model-only.resc'
    resc.write_text(text)
    (OUT / 'model-only.resc.txt').write_text(text)
    env = dict(os.environ, HOME=str(tmp / 'home'), XDG_CONFIG_HOME=str(tmp / 'home/.config'), TMPDIR=str(tmp))
    run = subprocess.run([str(ROOT / 'at32-runtime/renode_1.17.0-portable/renode'), '--disable-gui', '--console', str(resc)],
                         env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
    (OUT / 'renode.log').write_text(run.stdout)
    if run.returncode != 0 or any(s in run.stdout for s in ['There was an error', 'Errors during compilation', 'Error CS']) or 'SYNTHETIC Z GENERATED MODEL ZERO-EPOCH LOAD COMPLETE' not in run.stdout:
        raise RuntimeError(run.stdout[-16000:])
    sensor = json.loads((OUT / 'z-sensor-status.json').read_text())
    force = json.loads((OUT / 'z-force-status.json').read_text())
    assert sensor['timed_provider_bound'] and sensor['now_ns'] == 0 and sensor['conversions'] == 0
    assert sensor['provider_calls'] == 0 and sensor['adapter_errors'] == 0
    assert force['bound'] and force['registered'] and force['fixture_enabled'] and not force['faulted']
    assert force['now_ns'] == 0 and force['captures'] == 1 and force['samples_read'] == 0
    assert force['current_force_n'] == 0 and force['maximum_state_age_ns'] == 100000 and force['maximum_producer_lead_ns'] == 1000
    for board in ['main', 'nozzle']:
        assert (OUT / (board + '-z-probe-edges.csv')).is_file()
    summary = {'scope': 'Three generated model platforms loaded at zero. NO firmware loaded, NO CPU execution, NO time advancement, NO physical timing/native homing claim.',
               'passed': True, 'nozzle_tmc_model': 'autobaud', 'sensor': sensor, 'force': force,
               'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in [ROOT / 'rv1106-at32-link/scripts/shared_mcu.py', ROOT / 'rv1106-at32-link/scripts/z_probe_selection.py', Path(__file__)]}}
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('PASS: selected generated models load, exclusive binding at zero, baseline force0, fixed bounds, no firmware/time advance')
