#!/usr/bin/env python3
"""CPU-free tests with unchanged actual GPIO, CS1237 adapter/protocol sources.
Writes only this experimental directory. Does not run any original CPU/host.
"""
import argparse,csv,hashlib,json,os,pathlib,re,subprocess
BASE=pathlib.Path(__file__).resolve().parent
ROOT=BASE.parents[2]
p=argparse.ArgumentParser();p.add_argument('--shared-namespaces',action='store_true');args=p.parse_args()
out=BASE/'evidence'/('shared' if args.shared_namespaces else 'standalone');out.mkdir(parents=True,exist_ok=True)
work=out/'work';work.mkdir(exist_ok=True);(work/'home/.config').mkdir(parents=True,exist_ok=True)
sources=[ROOT/'nozzle-renode/peripherals/AT32F403A_IO.cs',ROOT/'nozzle-renode/experimental/cs1237-native/Cs1237NativeGpio.cs',ROOT/'nozzle-renode/experimental/cs1237-functional/Cs1237FunctionalProtocol.cs',ROOT/'nozzle-renode/experimental/cs1237-functional/Cs1237FunctionalAdapter.cs',BASE/'PassiveZProbeStateTrace.cs',BASE/'ProbeStateTraceTests.cs']
hashes={str(s.relative_to(ROOT)):hashlib.sha256(s.read_bytes()).hexdigest()for s in sources}
compiled=[]
for i,s in enumerate(sources):
 text=s.read_text()
 if args.shared_namespaces:text=text.replace('Antmicro.Renode.Peripherals.AT32','Antmicro.Renode.Peripherals.PrinterNozzle')
 dest=work/(str(i)+'-'+s.name);dest.write_text(text);compiled.append(dest)
repl='''flash: Memory.MappedMemory @ sysbus 0x08000000
    size: 0x20000
sram: Memory.MappedMemory @ sysbus 0x20000000
    size: 0x5000
'''
for n in ['','Control']:
 repl+=f'''gpio{n}: NozzleExperimental.Cs1237NativeGpio @ sysbus {hex(0x40010800+(0x400 if n else 0))}
    portIndex: 0
sensor{n}: NozzleExperimental.Cs1237FunctionalAdapter @ sysbus
    port: gpio{n}
    syntheticBaseline: 1234
    idealizedElectricalSemantics: true
'''
repl+='''checks: PrinterExperimental.ProbeStateTraceTests @ sysbus
    port: gpio
    sensor: sensor
    controlPort: gpioControl
    controlSensor: sensorControl
    sram: sram
    flash: flash
'''
(work/'test.repl').write_text(repl)
# Every rerun uses a new evidence stream directory: never overwrite old CSV.
runs=out/'captures';runs.mkdir(exist_ok=True)
index=0
while (runs/f'r{index}').exists():index+=1
capture=runs/f'r{index}';capture.mkdir()
lines=[f'include @{s}' for s in compiled]+['emulation SetGlobalQuantum "0.000001"','mach create "probe-state-cpu-free"',f'machine LoadPlatformDescription @{work}/test.repl',f'sysbus LoadBinary @{ROOT}/inputs/nozzle.bin 0x08004000',f'sysbus.checks RunAll "{ROOT}/inputs/nozzle.bin" "{capture}"','emulation RunFor "0.303"','sysbus.checks Finish','quit']
script=work/'test.resc';script.write_text('\n'.join(lines)+'\n')
env=dict(os.environ,HOME=str(work/'home'),XDG_CONFIG_HOME=str(work/'home/.config'),TMPDIR=str(work))
r=subprocess.run([str(ROOT/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(script)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=60)
(capture/'test.log').write_text(r.stdout)
clean=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',r.stdout)
if r.returncode or 'PROBE STATE ALL TESTS PASS:'not in clean or 'There was an error'in clean:raise RuntimeError(clean[-15000:])
for file in capture.glob('*.csv'):
 with file.open()as f:
  rows=list(csv.reader(f))
  assert all(len(row)==len(rows[0])for row in rows),file
for file in capture.glob('*status.json'):json.loads(file.read_text())
assert all(hashlib.sha256((ROOT/s).read_bytes()).hexdigest()==h for s,h in hashes.items())
summary={'scope':'CPU-free actual model tests; synthetic test SRAM and test GPIO stimuli only; no original firmware execution or native replay','checks':len(re.findall('PROBE STATE CHECK PASS:',clean)),'shared_namespaces':args.shared_namespaces,'source_sha256':hashes,'compiled_sha256':{str(s.relative_to(BASE)):hashlib.sha256(s.read_bytes()).hexdigest()for s in compiled},'dependencies_unchanged':True,'capture':str(capture.relative_to(BASE)),'csv_json_parsing_pass':True}
(capture/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
(out/'latest-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(clean[-6000:])
