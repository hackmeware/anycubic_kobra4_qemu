#!/usr/bin/env python3
"""Run self-contained Renode IO assertions, fail on missing success marker."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--renode', default=os.environ.get('RENODE', str(Path(os.environ.get('RENODE_RUNTIME', ROOT.parent / 'at32-runtime')) / 'run-renode')))
a = p.parse_args()
with tempfile.TemporaryDirectory(prefix='at32-io-test-') as home:
    env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=home + '/.config', TMPDIR=home)
    result = subprocess.run([a.renode, '--disable-gui', '--console', str(ROOT / 'tests/io.resc')], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=90)
    output = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', result.stdout)
    print(output)
    match = re.search(r'IO TESTS PASS: (\d+)', output)
    if result.returncode or not match or int(match.group(1)) < 39:
        raise SystemExit('IO behavior assertions failed; inspect Renode output above.')
