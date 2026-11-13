#!/usr/bin/env python3
import json,re,subprocess,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[2];pkg=root/'printer-shared-mcu'
with tempfile.TemporaryDirectory(prefix='printer-time-test-') as d:
 d=Path(d);out=d/'time.json';script=d/'test.resc'
 script.write_text(f'''include @{pkg}/peripherals/VirtualTimeTelemetry.cs
mach create "clock-test"
machine LoadPlatformDescriptionFromString "timeTelemetry: PrinterShared.VirtualTimeTelemetry @ sysbus"
sysbus.timeTelemetry Enable "{out}"
emulation RunFor "0.025"
log "PERIODIC_NS"
sysbus.timeTelemetry LastNanoseconds
log "PERIODIC_SEQUENCE"
sysbus.timeTelemetry Sequence
sysbus.timeTelemetry Stop
log "TELEMETRY TEST COMPLETE"
quit
''')
 p=subprocess.run([str(root/'at32-runtime/run-renode'),'--disable-gui','--console',str(script)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=45)
 log=p.stdout.decode(errors='replace');(pkg/'tests/telemetry-verified.log').write_text(log)
 assert p.returncode==0 and 'TELEMETRY TEST COMPLETE' in log and 'There was an error' not in log
 data=json.loads(out.read_text());assert data['virtual_time_ns']==25000000 and data['sequence']==4 and not data['enabled'] and not data['time_went_backwards']
 assert int(re.search(r'Script: PERIODIC_NS\s+0x([0-9a-fA-F]+)',log)[1],16)==20000000
 assert int(re.search(r'Script: PERIODIC_SEQUENCE\s+0x([0-9a-fA-F]+)',log)[1],16)==3
 assert not list(d.glob('*.tmp'))
 (pkg/'tests/telemetry-result.json').write_text(json.dumps(data,indent=2)+'\n')
 print('PASS: initial sample +10ms/+20ms, atomic stop at25ms, no temporary file remaining')
