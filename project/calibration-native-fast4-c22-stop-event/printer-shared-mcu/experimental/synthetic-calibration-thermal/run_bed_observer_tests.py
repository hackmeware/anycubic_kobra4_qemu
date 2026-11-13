#!/usr/bin/env python3
"""CPU-free actual GPIO/ADC/thermal observer tests. No firmware or controller."""
import argparse,csv,json,os,re,subprocess,tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]; BASE=Path(__file__).resolve().parent
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve()
if out.exists():raise SystemExit('Use a new output directory; never replace earlier evidence')
out.mkdir(parents=True)
with tempfile.TemporaryDirectory(prefix='bed-observer-') as folder:
 d=Path(folder);(d/'home/.config').mkdir(parents=True)
 sources=[ROOT/'at32-renode/peripherals'/n for n in ['AT32F403A_System.cs','AT32F403A_IO.cs','VirtualPrinterThermal.cs']]+[BASE/n for n in ['ResolvedBedHeaterBinding.cs','PassiveBedThermalObserver.cs','PassiveBedThermalObserverTests.cs']]
 bed=(BASE/'bed.repl').read_text()
 fixture='''adc1: AT32.AT32ADC @ sysbus 0x40012400
gpioA: AT32.AT32GPIO @ sysbus 0x40010800
baselineAdc: AT32.AT32ADC @ sysbus 0x41012400
baselinePort: AT32.AT32GPIO @ sysbus 0x41010800
'''+bed+'\n'+bed.replace('virtualBedNTC','baselineThermal').replace('syntheticBedHeaterBinding','baselineBinding').replace('adc1','baselineAdc').replace('gpioA','baselinePort')+'''
observer: AT32.PassiveBedThermalObserver @ sysbus
    portA: gpioA
    thermal: virtualBedNTC
checks: ThermalExperimental.PassiveBedThermalObserverTests @ sysbus
    port: gpioA
    baselinePort: baselinePort
    thermal: virtualBedNTC
    baseline: baselineThermal
    observer: observer
'''
 (d/'fixture.repl').write_text(fixture)
 lines=[f'include @{s}' for s in sources]+['mach create "bed-observer-no-cpu"',f'machine LoadPlatformDescription @{d}/fixture.repl',f'sysbus.checks Prepare "{out}"','emulation RunFor "0.0025"','sysbus.checks Switch','emulation RunFor "0.0075"','sysbus.checks CheckPWM','emulation RunFor "0.09"','sysbus.checks Finish','quit']
 (d/'test.resc').write_text('\n'.join(lines)+'\n');(out/'test.resc.txt').write_text((d/'test.resc').read_text())
 env=dict(os.environ,HOME=str(d/'home'),XDG_CONFIG_HOME=str(d/'home/.config'),TMPDIR=str(d))
 run=subprocess.run([str(ROOT/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(d/'test.resc')],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=120)
 (out/'renode.log').write_text(run.stdout);clean=re.sub(r'\x1b\[[0-9;]*m','',run.stdout)
 assert run.returncode==0 and not re.search(r'error CS\d|Error while|Could not compile|Unhandled exception|There was an error|Errors during compilation|\[ERROR\]',clean),clean
 assert 'PASSIVE BED OBSERVER TESTS PASS:' in clean,clean
 result=json.loads((out/'assertions.json').read_text());assert result['passed'] and result['assertions']==36 and result['final_updates']==10,result
 rows=list(csv.DictReader((out/'live.csv').open()));assert all(None not in row for row in rows)
 edges=[r for r in rows if r['event']=='edge'];assert [(r['time_us'],r['virtual_time_ns'],r['changed_level']) for r in edges]==[('0','0','1'),('2500','2500000','0'),('100000','100000000','1'),('100000','100000000','0')],edges
 status=json.loads((out/'live-status.json').read_text());assert status['stream_rows_written']==len(rows) and status['stream_dropped_rows']==status['stream_error_count']==0,status
 capped=json.loads((out/'capped-status.json').read_text());assert capped['stream_rows_written']==2 and capped['stream_capacity_reached'] and capped['stream_dropped_rows']>0,capped
 failed=json.loads((out/'failed-status.json').read_text());assert failed['stream_error_count']==1 and failed['last_stream_error'] and not failed['streaming'],failed
 (out/'summary.json').write_text(json.dumps({'passed':True,'scope':'CPU-free actual GPIO, model, ADC and observer; no native controller/firmware.', 'result':result,'status':status,'capped':capped,'failed_stream':failed},indent=2)+'\n')
 print(f"PASS: {result['assertions']} C# assertions; independent identical plant, actual PWM, precise timestamps, original faults, caps/drop/error accounting")
