#!/usr/bin/env python3
"""Derive fresh diagnostic boot ELF from private inputs, never modify originals."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

RECIPE_SHA256 = '59e34b5e0628712f8f9befaf85682e5901f8261e0420a5a8be60ea6a02aa5de0'

def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def prepare(project, inputs, output, network_helper=None):
    project, inputs = Path(project).resolve(strict=True), Path(inputs).resolve(strict=True)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('output must be a new directory')
    recipe = project/'rv1106-linux-display-128diag/prepare.py'
    if sha(recipe) != RECIPE_SHA256:
        raise ValueError('diagnostic recipe mismatch; review new source explicitly')
    required = ['kernel-zImage', 'kernel-board-dtb.dtb', 'disk-layout.json']
    source_hashes = {name: sha(inputs/name) for name in required}
    layout = json.loads((inputs/'disk-layout.json').read_text())
    if not isinstance(layout.get('partitions'), list) or not layout['partitions']:
        raise ValueError('partition layout missing')
    # The source recipe is known project code, never code from the firmware.
    code = recipe.read_text()
    code = code.replace('root=Path(__file__).resolve().parent', 'root=Path('+repr(str(output))+')', 1)
    code = code.replace("str(root.parent/'rv1106-qemu/tools')", repr(str(project/'rv1106-qemu/tools')), 1)
    helper_hash = None
    if network_helper is not None:
        helper = Path(network_helper).resolve(strict=True)
        helper_hash = sha(helper)
        hook = ('import importlib.util\n'
                '_spec=importlib.util.spec_from_file_location("kobra_network", '+repr(str(helper))+')\n'
                '_module=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_module)\n'
                'nodes=_module.enable_usb_host(nodes)\n')
        code = code.replace("names=b''; offsets={}; tree={}", hook+"names=b''; offsets={}; tree={}", 1)
    output.mkdir(mode=0o700)
    derived = output/'prepare-derived.py'
    derived.write_text(code)
    env = dict(os.environ, RV_INPUTS=str(inputs), RV1106_RAM_MB='128', PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run([sys.executable, str(derived)], env=env, capture_output=True, text=True, timeout=30)
    (output/'prepare.stdout').write_text(result.stdout)
    (output/'prepare.stderr').write_text(result.stderr)
    if result.returncode:
        raise RuntimeError('diagnostic preparation failed; inspect new output logs')
    report = {'profile':'fresh-r9-diagnostic-128', 'recipe_sha256':RECIPE_SHA256,
              'source_sha256':source_hashes, 'network_helper_sha256':helper_hash,
              'outputs':{name:sha(output/name) for name in ['linux-test.elf','linux-test.dtb','boot-trampoline.bin']},
              'firmware_derived':True, 'redistribute':False, 'guest_boot_tested':False,
              'requires_root_hook':'/emulation-init.sh',
              'warning':'Successful ELF assembly does not prove disk readiness, startup or calibration.'}
    (output/'PREPARATION.json').write_text(json.dumps(report, indent=2)+'\n')
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--inputs', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--network-helper', help='Reviewed local baseline_network.py; enables generic-xhci DT')
    args=parser.parse_args()
    try: report=prepare(args.project,args.inputs,args.output,args.network_helper)
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc: parser.exit(1,str(exc)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__': main()
