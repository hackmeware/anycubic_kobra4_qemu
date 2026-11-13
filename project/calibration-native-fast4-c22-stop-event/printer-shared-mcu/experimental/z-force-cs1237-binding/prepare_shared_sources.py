#!/usr/bin/env python3
"""Prepare explicit bridge sources/commands; does not patch/load core, firmware, GPIO or sensor."""
import argparse,hashlib,json,pathlib,re
base=pathlib.Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True)
p.add_argument('--maximum-state-age-ns',type=int,required=True);p.add_argument('--maximum-producer-lead-ns',type=int,required=True)
p.add_argument('--capacity',type=int,default=4096);p.add_argument('--trace-rows',type=int,default=0)
p.add_argument('--fixture',default='zBedContactFixture');p.add_argument('--sensor',default='sensor');p.add_argument('--gpio',default='gpioA');p.add_argument('--source-name',default='synthetic_z_force')
a=p.parse_args()
for name in [a.fixture,a.sensor,a.gpio,a.source_name]:
 if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',name):p.error('Use simple explicit Renode names without punctuation')
if not (0<a.maximum_state_age_ns<=1000000000 and 0<=a.maximum_producer_lead_ns<=1000000000 and 2<=a.capacity<=1000000 and 0<=a.trace_rows<=1000000):p.error('Invalid declared history bounds')
out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
for name in ['ZForceHistory.cs','MotorZForceSource.cs','Cs1237ZForceBinding.cs']:
 text=(base/name).read_text().replace('Antmicro.Renode.Peripherals.AT32','Antmicro.Renode.Peripherals.PrinterMotor');(out/name).write_text(text)
(out/'motor-source.repl').write_text(f'''// Prerequisite: separately reviewed synthetic bed fixture already loaded.
zForceSource: PrinterExperimental.MotorZForceSource @ sysbus
    fixture: {a.fixture}
    tmr8: tmr8
    maximumStateAgeNanoseconds: {a.maximum_state_age_ns}
    maximumProducerLeadNanoseconds: {a.maximum_producer_lead_ns}
    capacity: {a.capacity}
    maximumTraceRows: {a.trace_rows}
''')
(out/'nozzle-binding.repl').write_text(f'''// Prerequisite: explicit functional sensor and native GPIO wrapper already loaded.
zForceBinding: PrinterExperimental.Cs1237ZForceBinding @ sysbus
    port: {a.gpio}
    sensor: {a.sensor}
    sourceName: "{a.source_name}"
''')
(out/'motor-tail.commands').write_text(f'''# Append to MOTOR setup after the synthetic physical fixture is configured.
# Existing shared setup configures nozzle before motor, but all this is before RunFor.
# Does NOT apply disable-contact.patch or create/replace GPIO, sensor, or physical fixture.
mach set "motor"
include @{out}/ZForceHistory.cs
include @{out}/MotorZForceSource.cs
machine LoadPlatformDescription @{out}/motor-source.repl
sysbus.zForceSource Register "{a.source_name}"
mach set "nozzle"
include @{out}/Cs1237ZForceBinding.cs
machine LoadPlatformDescription @{out}/nozzle-binding.repl
mach set "motor"
''')
files={x.name:hashlib.sha256(x.read_bytes()).hexdigest()for x in out.iterdir()if x.is_file() and x.name!='manifest.json'}
(out/'manifest.json').write_text(json.dumps({'explicit_experimental_only':True,'physical_timing_fidelity':False,'maximum_state_age_ns':a.maximum_state_age_ns,'maximum_producer_lead_ns':a.maximum_producer_lead_ns,'files':files},indent=2)+'\n')
print(out/'motor-tail.commands')
