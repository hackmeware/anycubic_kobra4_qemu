#!/usr/bin/env python3
"""Cortex-M execution, virtual RX pacing, reset, overflow and TX-forward tests."""
import argparse, os, re, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--renode',default=os.environ.get('RENODE',str(ROOT.parent/'at32-runtime/renode_1.17.0-portable/renode')))
a=p.parse_args()
subprocess.run(['python3',str(ROOT/'tests/make-serial-wire-firmware.py')],check=True)
expected=[0,1,1,1,2,2,2,3,3,0x434241,0xC0,0,0,3,0,1,4,0x44434241,4,0x41424344,2,1,0,0]
with tempfile.TemporaryDirectory(prefix='at32-wire-') as home:
 result=subprocess.run([a.renode,'--disable-gui','--console',str(ROOT/'tests/serial-wire.resc')],cwd=ROOT,
  env=dict(os.environ,HOME=home,XDG_CONFIG_HOME=home+'/.config'),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=90)
 output=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',result.stdout)
 print(output)
 values=[int(x,16) for x in re.findall(r'^0x([0-9A-Fa-f]+)\s*$',output,re.M)]
 if result.returncode or values!=expected:
  raise SystemExit(f'Serial wire assertion failure:\nExpected {expected}\nActual   {values}')
 print(f'SERIAL WIRE TESTS PASS: {len(expected)} checks; actual Cortex-M consumed and echoed ABCD without UART overrun.')
