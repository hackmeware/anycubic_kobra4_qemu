#!/usr/bin/env python3
"""Compile unchanged real peripherals in isolated shared namespaces, with no CPUs/firmware."""
import hashlib,json,os,pathlib,re,subprocess,tempfile,time
base=pathlib.Path(__file__).resolve().parent
root=base.parents[2]
out=base/'results';out.mkdir(exist_ok=True)
for name in ['test-summary.json','compiled-fixture.repl','actual-plant.json','actual-plant.csv','nozzle-binding.json','bed-binding.json','unit-tests.log','analysis.json']:
    p=out/name
    if p.exists():p.unlink()
# Validate the actual opt-in profile guard values, not only separate negative-test clones.
profile_checks=0
for name,expected in {
    'nozzle.repl':{'heaterPowerWatts':'60','heatCapacityJoulesPerKelvin':'20','conductanceWattsPerKelvin':'0.2',
                  'maximumCelsius':'400','stopHeaterAtMaximum':'true','updateMicroseconds':'10000',
                  'ambientCelsius':'25','heaterActiveHigh':'true','pullResistanceOhms':'4700',
                  'adcMaximum':'4095','thermistorToGround':'true','useRecoveredNozzleCurve':'true','channel':'0'},
    'bed.repl':{'heaterPowerWatts':'200','heatCapacityJoulesPerKelvin':'600','conductanceWattsPerKelvin':'1.5',
                'maximumCelsius':'150','stopHeaterAtMaximum':'true','updateMicroseconds':'10000',
                'ambientCelsius':'25','heaterActiveHigh':'true','pullResistanceOhms':'4700','betaKelvin':'3950',
                'nominalResistanceOhms':'100000','nominalCelsius':'25','adcMaximum':'4095',
                'thermistorToGround':'true','channel':'8'}}.items():
    text=(base/name).read_text()
    for key,value in expected.items():
        found=re.findall(r'^\s+'+re.escape(key)+r':\s*([^\s]+)\s*$',text,re.M)
        assert found==[value],(name,key,found,value)
        profile_checks+=1
sources=[]
for board,namespace in [('at32-renode','PrinterMain'),('nozzle-renode','PrinterNozzle')]:
    for name in ['AT32F403A_System.cs','AT32F403A_IO.cs','VirtualPrinterThermal.cs']:
        sources.append((root/board/'peripherals'/name,namespace))
sources += [(root/'nozzle-renode/peripherals/NativeNozzleHeaterBinding.cs','PrinterNozzle'),
            (base/'ResolvedBedHeaterBinding.cs','PrinterMain'),(base/'SyntheticThermalTests.cs',None)]
protected=[root/'inputs'/name for name in ['mcu.bin','nozzle.bin','motor.bin']]
protected += [root/'at32-renode/docs/THERMAL-BINDINGS.md',root/'at32-renode/platforms/virtual-bed-ntc.repl',
              root/'at32-renode/platforms/virtual-commanded-bed.repl',root/'nozzle-renode/platforms/virtual-nozzle-recovered-ntc.repl']
protected += [base/'nozzle.repl',base/'bed.repl',base/'run_tests.py',base/'analyze.py']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
before={str(p.relative_to(root)):sha(p) for p,_ in sources}
before.update({str(p.relative_to(root)):sha(p) for p in protected})
with tempfile.TemporaryDirectory(prefix='synthetic-thermal-unit-') as folder:
    d=pathlib.Path(folder);(d/'home/.config').mkdir(parents=True)
    compiled=[];compiled_sha={}
    for i,(p,namespace) in enumerate(sources):
        text=p.read_text()
        if namespace:text=text.replace('Antmicro.Renode.Peripherals.AT32','Antmicro.Renode.Peripherals.'+namespace)
        target=d/(str(i)+'-'+p.name);target.write_text(text);compiled.append(target)
        compiled_sha[str(p.relative_to(root))]=sha(target)
    nozzle=(base/'nozzle.repl').read_text().replace('AT32.','PrinterNozzle.').replace('adc1','nozzleAdc').replace('gpioB','nozzlePort')
    bed=(base/'bed.repl').read_text().replace('AT32.','PrinterMain.').replace('adc1','bedAdc').replace('gpioA','bedPort')
    platform='''nozzleAdc: PrinterNozzle.AT32ADC @ sysbus 0x40012400
nozzlePort: PrinterNozzle.AT32GPIO @ sysbus 0x40010c00
bedAdc: PrinterMain.AT32ADC @ sysbus 0x41012400
bedPort: PrinterMain.AT32GPIO @ sysbus 0x41010800
'''+nozzle+'\n'+bed+'''
checks: ThermalExperimental.SyntheticThermalTests @ sysbus
    nozzlePort: nozzlePort
    bedPort: bedPort
    nozzleAdc: nozzleAdc
    bedAdc: bedAdc
    nozzle: virtualNozzleNTC
    bed: virtualBedNTC
    nozzleBinding: nativeNozzleHeaterBinding
    bedBinding: syntheticBedHeaterBinding
'''
    (d/'fixture.repl').write_text(platform)
    lines=[f'include @{p}' for p in compiled]+[
        'mach create "synthetic-thermal-no-CPU"',f'machine LoadPlatformDescription @{d}/fixture.repl',
        'sysbus.checks Prepare','emulation RunFor "1"','sysbus.checks EndPwmBeginFull',
        'emulation RunFor "1"','sysbus.checks CheckInitialHeatRate','emulation RunFor "149"',
        'sysbus.checks EndFullBeginCooling','emulation RunFor "20"','sysbus.checks CheckCoolingBeginOpen',
        'emulation RunFor "1"','sysbus.checks CheckOpenResetShort','emulation RunFor "1"',
        'sysbus.checks CheckResetAndBeginRecovery','emulation RunFor "1"','sysbus.checks CheckRecoveryAndBeginLong',
        'emulation RunFor "115"','sysbus.checks CheckOutOfTable',
        'emulation RunFor "1100"','sysbus.checks Finish','emulation RunFor "1"','sysbus.checks CheckPostLatchEdges',f'sysbus.checks WriteResults "{out}/actual-plant"',
        f'sysbus.nativeNozzleHeaterBinding WriteStatus "{out}/nozzle-binding.json"',
        f'sysbus.syntheticBedHeaterBinding WriteStatus "{out}/bed-binding.json"','quit']
    (d/'test.resc').write_text('\n'.join(lines)+'\n')
    env=dict(os.environ,HOME=str(d/'home'),XDG_CONFIG_HOME=str(d/'home/.config'),TMPDIR=str(d))
    started=time.monotonic()
    r=subprocess.run([str(root/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(d/'test.resc')],
                     env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=120)
    elapsed=time.monotonic()-started;(out/'unit-tests.log').write_text(r.stdout)
    clean=re.sub(r'\x1b\[[0-9;]*m','',r.stdout)
    expected=['SYNTHETIC THERMAL GPIO PWM PASS','SYNTHETIC THERMAL INITIAL RATE PASS','SYNTHETIC THERMAL TARGET CROSSING PASS',
              'SYNTHETIC THERMAL COOLING PASS','SYNTHETIC THERMAL FAULT RESET PASS','SYNTHETIC THERMAL RESET RECOVERY PASS',
              'SYNTHETIC THERMAL OUT OF TABLE PASS','SYNTHETIC THERMAL LONG NEGATIVES PASS','SYNTHETIC THERMAL TESTS PASS:']
    assert r.returncode==0,clean[-20000:]
    assert not re.search(r'error CS\d|Error while|Could not compile|Unhandled exception|There was an error|Errors during compilation|\[ERROR\]',clean),clean
    result=json.loads((out/'actual-plant.json').read_text())
    assert all(any(stage.startswith(s) for stage in result['completed_stages']) for s in expected),result
    assert result['assertions']==93 and result['dropped_rows']==0,result
    assert not result['native_firmware_run'] and not result['direct_duty_used'] and not result['temperature_injection_used']
    assert all(sha(root/p)==h for p,h in before.items()),'An input changed during the isolated tests'
    subprocess.run(['python3',str(base/'analyze.py')],check=True)
    (out/'test-summary.json').write_text(json.dumps({'scope':'CPU-free actual C# GPIO/thermal/ADC tests only. No native firmware, shared launcher edit, direct duty, temperature injection, native control-loop or calibration claim.',
        'wall_seconds':elapsed,'profile_value_checks':profile_checks,'result':result,'source_sha256':before,'compiled_source_sha256':compiled_sha,
        'profiles_sha256':{p.name:sha(p) for p in [base/'nozzle.repl',base/'bed.repl']},'inputs_unchanged':True},indent=2)+'\n')
    (out/'compiled-fixture.repl').write_text(platform)
    print('\n'.join(stage for stage in result['completed_stages'] if 'PASS' in stage))
    print(f'CPU-free wall time: {elapsed:.3f}s')
