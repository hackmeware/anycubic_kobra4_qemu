#!/usr/bin/env python3
"""Boot original host+MCU firmware for four explicit sensor-fault experiments.

No thresholds or firmware instructions are changed. All guest writes remain in
QEMU snapshot overlays. Not a physical safety certification.
"""
import argparse,json,subprocess,sys,tempfile,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--disk',type=Path,required=True);p.add_argument('--main',type=Path,required=True);p.add_argument('--nozzle',type=Path,required=True);p.add_argument('--seconds',type=float,default=35);a=p.parse_args()
base=[sys.executable,str(ROOT/'scripts/run_link.py'),'--qemu',str(ROOT.parent/'rv1106-qemu/bin/qemu-system-arm-emmc'),'--rv-image',str(ROOT.parent/'rv1106-linux-emmc/linux-test.elf'),'--cpu','cortex-a7,has_el3=off','--disk',str(a.disk.resolve()),'--mcu-image',str(a.main.resolve()),'--mcu-base','0x08004000','--mcu-hext','24000000','--rv-uart','3','--virtual-baud','576000','--nozzle-image',str(a.nozzle.resolve()),'--console-commands',str(ROOT/'tests/sensor-fault-host.commands'),'--timeout',str(a.seconds)]
results=[]
for sensor in ['nozzle','bed']:
 for fault in ['short','open']:
  logs=ROOT/f'test-results/fault-{sensor}-{fault}'
  with tempfile.TemporaryDirectory(prefix='sensor-fault-') as d:
   d=Path(d);main=d/'main.resc';nozzle=d/'nozzle.resc'
   main.write_text('include @scripts/virtual-bed-ntc.resc\n'+(f'sysbus.virtualBedNTC SetSensorFault "{fault}"\n' if sensor=='bed' else ''))
   nozzle.write_text('include @scripts/virtual-nozzle-ntc.resc\n'+(f'sysbus.virtualNozzleNTC SetSensorFault "{fault}"\n' if sensor=='nozzle' else ''))
   mf=d/'main-final.resc';nf=d/'nozzle-final.resc'
   mf.write_text('pause\nsysbus.virtualBedNTC ADCValue\n');nf.write_text('pause\nsysbus.virtualNozzleNTC ADCValue\n')
   subprocess.run(base+['--mcu-setup-commands',str(main),'--nozzle-setup-commands',str(nozzle),'--mcu-final-commands',str(mf),'--nozzle-final-commands',str(nf),'--log-dir',str(logs)],check=True)
  text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',(logs/'console.bin').read_text(errors='replace'))
  role='nozzle_mcu' if sensor=='nozzle' else 'mcu';code='10124' if sensor=='nozzle' else '10123'
  shutdown=bool(re.search("MCU '"+role+r"'.{0,60}(?:error code:|ErrorCode:)\s*25",text))
  peripheral='virtualNozzleNTC' if sensor=='nozzle' else 'virtualBedNTC'
  rlog=(logs/('nozzle-renode.log' if sensor=='nozzle' else 'renode.log')).read_text(errors='replace')
  rlog=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',rlog)
  match=re.search(peripheral+r' ADCValue\s+0x([0-9a-fA-F]+)',rlog)
  observed_raw=int(match.group(1),16) if match else None
  result={'observed_raw':observed_raw,'sensor':sensor,'fault':fault,'injected_raw':0 if fault=='short' else 4095,'native_shutdown_25':shutdown,'host_error_code':code,'host_error_observed':code in text,'firmware_modified':False,'thresholds_modified':False}
  results.append(result);(logs/'fault-result.json').write_text(json.dumps(result,indent=2)+'\n')
  if not shutdown or code not in text or observed_raw!=(0 if fault=='short' else 4095):raise SystemExit('FAIL: '+json.dumps(result))
  print('PASS: '+sensor+' '+fault+' triggers original firmware shutdown25 and native host code'+code,flush=True)
(ROOT/'test-results/sensor-fault-summary.json').write_text(json.dumps(results,indent=2)+'\n')
print('PASS: all four original-firmware sensor fault experiments')
