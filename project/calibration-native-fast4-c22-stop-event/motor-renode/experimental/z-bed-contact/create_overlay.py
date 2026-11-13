#!/usr/bin/env python3
"""Generate explicit load/enable commands after the two-method patch is reviewed/applied."""
import argparse,hashlib,json,pathlib
base=pathlib.Path(__file__).resolve().parent;root=base.parents[2]
p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True)
p.add_argument('--shared',action='store_true',help='Target the existing namespace-isolated PrinterMotor plant')
a=p.parse_args()
core=(root/'motor-renode/peripherals/GenericStepperElectromechanical.cs').read_text()
if 'public void DisableContact(){ContactEnabled=false;}' not in core or 'public void DisableRelativeContact(int axis)' not in core:
 raise SystemExit('Blocked: production core lacks the reviewed two-method extension. Review disable-contact.patch first; this script will not apply it.')
out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
s=(base/'VirtualZBedContactFixture.cs').read_text()
if a.shared:s=s.replace('Antmicro.Renode.Peripherals.AT32','Antmicro.Renode.Peripherals.PrinterMotor')
(out/'VirtualZBedContactFixture.cs').write_text(s)
(out/'fixture.repl').write_text('''// Disabled until SetEnabled true. Explicit synthetic scenario, not recovered physical geometry.
zBedContactFixture: MotorExperimental.VirtualZBedContactFixture @ sysbus
    plant: electromechanicalPlant
    bedRelativeMillimeters: -10
    oppositeStopRelativeMillimeters: 252
    bedIsMinimum: true
    stiffnessNewtonsPerMillimeter: 20
    dampingNewtonSecondsPerMillimeter: 0.05
    baselineCounts: 0
    countsPerNewton: 10000
    signalPolarity: 1
''')
(out/'load.commands').write_text(f'include @{out}/VirtualZBedContactFixture.cs\nmachine LoadPlatformDescription @{out}/fixture.repl\n')
(out/'enable.commands').write_text((out/'load.commands').read_text()+'sysbus.zBedContactFixture SetEnabled true\n')
manifest={'shared_namespace':a.shared,'fixture_source_sha256':hashlib.sha256((base/'VirtualZBedContactFixture.cs').read_bytes()).hexdigest(),
 'core_source_sha256':hashlib.sha256(core.encode()).hexdigest(),'files':{x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in out.iterdir() if x.is_file()}}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(out/'enable.commands')
