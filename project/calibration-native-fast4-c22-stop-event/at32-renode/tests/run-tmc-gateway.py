#!/usr/bin/env python3
"""Run actual C# gateway model assertions inside Renode."""
import os,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='tmc-gateway-tests-') as tmp:
    os.makedirs(tmp+'/.config')
    result=subprocess.run([os.environ.get('RENODE',str(ROOT.parent/'at32-runtime/renode_1.17.0-portable/renode')),
        '--disable-gui','--console','tests/tmc-gateway.resc'],cwd=ROOT,
        env=dict(os.environ,HOME=tmp,XDG_CONFIG_HOME=tmp+'/.config',TMPDIR=tmp),
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=90)
    print(result.stdout)
    if result.returncode or 'VIRTUAL TMC GATEWAY TESTS PASS: 34' not in result.stdout:
        raise SystemExit('TMC gateway assertions failed')
