"""Explicit offline test paths; works from overlay or installed experiment."""
import hashlib
import json
import os
from pathlib import Path
HERE = Path(__file__).resolve().parent

def source_profile(explicit=None):
    candidates = [Path(explicit)] if explicit is not None else ([Path(os.environ['HOMING_TEST_PROFILE'])] if 'HOMING_TEST_PROFILE' in os.environ else [HERE.parents[2], *[r/'calibration-cold-release-c2' for r in HERE.parents]])
    for candidate in candidates:
        if (candidate/'rv1106-at32-link/experimental/sensor30-observation/protocol.py').is_file():
            return candidate.resolve()
    raise ValueError('Pinned sensor30 profile missing; pass --source-profile or HOMING_TEST_PROFILE')

def c2_run_directory(explicit=None):
    candidates = [Path(explicit)] if explicit is not None else ([Path(os.environ['HOMING_C2_RUN'])] if 'HOMING_C2_RUN' in os.environ else [r/'calibration-cold-release-c2/runs/cold-z-release-4800s-c2' for r in HERE.parents])
    for candidate in candidates:
        if (candidate/'cold-release-observation.json').is_file():
            return candidate.resolve()
    raise ValueError('Immutable c2 evidence missing; pass --run-directory or HOMING_C2_RUN')

def fixture(name):
    path = HERE/'fixtures'/name
    manifest = json.loads((HERE/'fixtures/sha256.json').read_text())
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest[name]:
        raise ValueError('Pinned offline fixture changed')
    return data
