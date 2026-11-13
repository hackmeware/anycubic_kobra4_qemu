#!/usr/bin/env python3
"""Generate a reviewable patch and isolated test copy. Never edit production source."""
import difflib, hashlib, json, pathlib
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'motor-renode/peripherals/GenericStepperElectromechanical.cs'

def extended(text):
    edits=[
      ('        // Explicit scenario initial conditions. Never called on an MCU reset.\n',
       '        // External fixture removal; preserves rotor/current/velocity state.\n'
       '        public void DisableContact(){ContactEnabled=false;}\n'),
      ('        public ulong TriggerCount{get;private set;}public ulong ClippedSamples{get;private set;}\n',
       '        // Integrate the previous contact through now before removing the external fixture.\n'
       '        public void DisableRelativeContact(int axis){Check(axis);AdvanceAxisToNow(axis);rotors[axis].DisableContact();}\n')]
    for anchor,addition in edits:
        if text.count(anchor)!=1: raise RuntimeError('Core source anchor changed; review required')
        if addition in text: raise RuntimeError('Extension already present; review required')
        text=text.replace(anchor,addition+anchor)
    return text

def prepare(destination):
    original=SOURCE.read_text();result=extended(original)
    destination.write_text(result)
    patch=''.join(difflib.unified_diff(original.splitlines(True),result.splitlines(True),
      fromfile='a/motor-renode/peripherals/GenericStepperElectromechanical.cs',
      tofile='b/motor-renode/peripherals/GenericStepperElectromechanical.cs'))
    (HERE/'disable-contact.patch').write_text(patch)
    return {'core_source_sha256':hashlib.sha256(original.encode()).hexdigest(),
            'isolated_extended_core_sha256':hashlib.sha256(result.encode()).hexdigest(),
            'patch_sha256':hashlib.sha256(patch.encode()).hexdigest()}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True)
    a=p.parse_args();print(json.dumps(prepare(a.output),indent=2))
