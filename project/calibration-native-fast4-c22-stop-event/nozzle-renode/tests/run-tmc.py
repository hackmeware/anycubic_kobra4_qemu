#!/usr/bin/env python3
"""Execute C# TMC assertions in actual Renode (not a duplicate Python model)."""
import os, subprocess, tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='nozzle-tmc-') as tmp:
    Path(tmp,'.config').mkdir()
    p=subprocess.run([os.environ.get('RENODE',str(root.parent/'at32-runtime/renode_1.17.0-portable/renode')),'--disable-gui','--console','tests/tmc.resc'],cwd=root,env=dict(os.environ,HOME=tmp,XDG_CONFIG_HOME=tmp+'/.config',TMPDIR=tmp),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=90)
    print(p.stdout)
    if p.returncode or 'NOZZLE TMC TESTS PASS: 16' not in p.stdout or 'NOZZLE GPIO WAVEFORM PASS' not in p.stdout:
        raise SystemExit('Nozzle TMC assertions failed')
