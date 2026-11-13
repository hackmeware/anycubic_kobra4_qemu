#!/usr/bin/env python3
"""Small analytic/static checks; optional bounded, CPU-free actual C# model suite."""
import argparse, csv, hashlib, json, math, os, pathlib, re, subprocess, tempfile, time
from generate import BASE, ROOT, REFERENCE, FACTORS, factor_value, parameters, profile_text, sha
OUT = BASE / 'evidence'
SOURCE_INPUTS = []
for board, namespace in [('at32-renode', 'PrinterMain'), ('nozzle-renode', 'PrinterNozzle')]:
    for name in ['AT32F403A_System.cs', 'AT32F403A_IO.cs', 'VirtualPrinterThermal.cs']:
        SOURCE_INPUTS.append((ROOT/board/'peripherals'/name, namespace))
SOURCE_INPUTS += [(ROOT/'nozzle-renode/peripherals/NativeNozzleHeaterBinding.cs', 'PrinterNozzle'),
                  (REFERENCE/'ResolvedBedHeaterBinding.cs', 'PrinterMain'),
                  (BASE/'AcceleratedFunctionalThermalTests.cs', None)]

def protected_inputs():
    paths = [p for p, _ in SOURCE_INPUTS]
    paths += [ROOT/'inputs'/name for name in ['mcu.bin', 'nozzle.bin', 'motor.bin']]
    paths += [ROOT/p for p in ['at32-renode/docs/THERMAL-BINDINGS.md',
        'at32-renode/platforms/virtual-bed-ntc.repl', 'at32-renode/platforms/virtual-commanded-bed.repl',
        'nozzle-renode/platforms/virtual-nozzle-recovered-ntc.repl',
        'nozzle-renode/docs/verified-adc-configuration.json', 'at32-renode/docs/verified-adc-configuration.json',
        'evidence/recovered-nozzle-thermal/nozzle-thermal-recovered-evidence.json',
        'at32-renode/docs/thermal-runtime-config-evidence.json',
        'printer-shared-mcu/tools/generate.py', 'printer-shared-mcu/bootstrap.resc.in',
        'rv1106-at32-link/run-linked.sh'] if (ROOT/p).is_file()]
    paths += [REFERENCE/name for name in ['nozzle.repl', 'bed.repl']]
    paths += sorted((REFERENCE/'native-controller').rglob('*.py'))
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}

def check_profiles_and_theory():
    checks = 0
    bad = [-1, 0, 0.5, 3, 11, float('nan'), float('inf'), -float('inf'), True, False, None, '', '4x']
    for value in bad:
        try: factor_value(value)
        except ValueError: checks += 1
        else: raise AssertionError(('Invalid factor accepted', value))
    rows = []
    for factor in FACTORS:
        for sensor in ['nozzle', 'bed']:
            expected = profile_text(sensor, factor)
            actual = (BASE/'profiles'/f'{factor}x'/(sensor+'.repl')).read_text()
            assert actual == expected
            # Ignoring comments, ONLY the one heat capacity line may differ.
            significant = lambda s: [line for line in s.splitlines() if line.strip() and not line.lstrip().startswith('//')]
            original = significant((REFERENCE/(sensor+'.repl')).read_text())
            candidate = significant(actual)
            assert len(original) == len(candidate)
            changed = [(a, b) for a, b in zip(original, candidate) if a != b]
            assert len(changed) == (0 if factor == 1 else 1)
            assert all(a.lstrip().startswith('heatCapacityJoulesPerKelvin:') for a, _ in changed)
            checks += 4
            p = parameters(factor)['sensors'][sensor]
            p0 = parameters(1)['sensors'][sensor]
            assert p['mathematical_full_duty_equilibrium_c'] == p0['mathematical_full_duty_equilibrium_c']
            assert p['target_hold_duty'] == p0['target_hold_duty']
            assert abs(p['ideal_full_power_target_seconds']*factor-p0['ideal_full_power_target_seconds']) < 1e-12
            checks += 3
            # Independent exact exponential recurrence at unchanged 10ms, not actual C# execution.
            t = 25.0
            crossing = None
            for step in range(1, math.ceil(p['ideal_full_power_target_seconds']/.01)+3):
                eq = p['mathematical_full_duty_equilibrium_c']
                t = eq+(t-eq)*math.exp(-p['conductance_w_per_k']*.01/p['capacity_j_per_k'])
                analytic = eq+(25-eq)*math.exp(-p['conductance_w_per_k']*step*.01/p['capacity_j_per_k'])
                assert abs(t-analytic) < 1e-8
                if crossing is None and t >= p['target_c']: crossing=step*.01
            assert crossing is not None
            assert 0 <= crossing-p['ideal_full_power_target_seconds'] < .010000001
            checks += 2
            rows.append(dict(factor=factor, sensor=sensor, first_crossing_10ms_s=crossing, **p))
    # Original native ADC thresholds, never substituted, relaxed or written.
    guards = {}
    for board, sensor, expected in [('nozzle-renode','nozzle',(962,32593,8,4)), ('at32-renode','bed',(15205,32309,8,4))]:
        record=json.loads((ROOT/board/'docs/verified-adc-configuration.json').read_text())['adc_objects'][0]
        observed=tuple(record[k] for k in ['minimum_sum','maximum_sum','sample_count','error_limit'])
        assert observed == expected
        guards[sensor]=dict(zip(['minimum_sum','maximum_sum','sample_count','error_limit'],observed))
        code=468 if sensor=='nozzle' else 3444
        assert observed[0] <= code*observed[2] <= observed[1]
        checks += 2
    result=dict(scope='Analytic/static preparation, not actual C# or native validation',
        checks=checks, factors=list(FACTORS), invalid_factors_rejected=len(bad), comparisons=rows,
        unchanged_native_adc_guards=guards, native_firmware_run=False,
        native_watchdog_timing='not recovered; compatibility unknown',
        recommendation='4x first native functional experiment as requested; 2x fallback only after a preserved 4x failure and explicit review; 10x stress only; wait for current native safe-zero/off/cooling teardown')
    (OUT/'analytic-static.json').write_text(json.dumps(result,indent=2)+'\n')
    with (OUT/'parameter-comparison.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(f'ANALYTIC STATIC PASS: {checks} checks, {len(rows)} plant/factor comparisons')
    return result

def fixture(factor):
    nozzle=profile_text('nozzle', factor).replace('AT32.','PrinterNozzle.').replace('adc1','nozzleAdc').replace('gpioB','nozzlePort')
    bed=profile_text('bed', factor).replace('AT32.','PrinterMain.').replace('adc1','bedAdc').replace('gpioA','bedPort')
    return '''nozzleAdc: PrinterNozzle.AT32ADC @ sysbus 0x40012400
nozzlePort: PrinterNozzle.AT32GPIO @ sysbus 0x40010c00
bedAdc: PrinterMain.AT32ADC @ sysbus 0x41012400
bedPort: PrinterMain.AT32GPIO @ sysbus 0x41010800
'''+nozzle+'\n'+bed+f'''
checks: ThermalExperimental.AcceleratedFunctionalThermalTests @ sysbus
    nozzlePort: nozzlePort
    bedPort: bedPort
    nozzleAdc: nozzleAdc
    bedAdc: bedAdc
    nozzle: virtualNozzleNTC
    bed: virtualBedNTC
    nozzleBinding: nativeNozzleHeaterBinding
    bedBinding: syntheticBedHeaterBinding
    accelerationFactor: {factor}
'''

def analyze_trace(folder, factor):
    recovered=json.loads((ROOT/'evidence/recovered-nozzle-thermal/nozzle-thermal-recovered-evidence.json').read_text())
    def nozzle_adc(t):
        if t < -40: return 4095
        if t > 360: return 0
        for segment in recovered['live_converter']['segments']:
            upper,m,c=(segment[k] for k in ['resistance_upper_breakpoint_ohms','temperature_per_ohm','temperature_intercept_celsius'])
            if t < upper*m+c: continue
            r=(t-c)/m
            return math.floor(4095*r/(4700+r)+.5)
        raise AssertionError('No recovered segment')
    def bed_adc(t):
        r=100000*math.exp(3950*(1/(t+273.15)-1/298.15))
        return math.floor(4095*r/(4700+r)+.5)
    rows=list(csv.DictReader((folder/'actual-plant.csv').open()))
    assert rows and all(float(a['virtual_seconds'])<float(b['virtual_seconds']) for a,b in zip(rows,rows[1:]))
    for row in rows:
        assert float(row['nozzle_fan_duty'])==0
        for sensor,convert in [('nozzle',nozzle_adc),('bed',bed_adc)]:
            fault=row[sensor+'_fault']
            expected=4095 if fault=='open' else 0 if fault=='short' else convert(float(row[sensor+'_c']))
            assert int(row[sensor+'_adc']) == expected,(sensor,row,expected)
            assert row[sensor+'_latch']=='False'
    for sensor in ['nozzle','bed']:
        assert {'none','open','short'} <= {r[sensor+'_fault'] for r in rows}
    result=dict(factor=factor,trace_rows=len(rows),independent_sensor_checks=len(rows)*2,
        trace_sha256=sha(folder/'actual-plant.csv'),native_firmware_run=False)
    (folder/'independent-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

def execute_csharp(timeout=30):
    before=protected_inputs()
    destination=OUT/'actual-csharp'
    destination.mkdir(exist_ok=True)
    summary=destination/'summary.json'
    if summary.exists(): summary.unlink()
    with tempfile.TemporaryDirectory(prefix='accelerated-functional-thermal-') as temp:
        temp=pathlib.Path(temp);(temp/'home/.config').mkdir(parents=True)
        compiled=[];compiled_hashes={}
        for i,(path,namespace) in enumerate(SOURCE_INPUTS):
            source=path.read_text()
            if namespace: source=source.replace('Antmicro.Renode.Peripherals.AT32','Antmicro.Renode.Peripherals.'+namespace)
            target=temp/f'{i}-{path.name}';target.write_text(source);compiled.append(target)
            compiled_hashes[str(path.relative_to(ROOT))]=sha(target)
        lines=[f'include @{path}' for path in compiled]
        for factor in FACTORS:
            folder=destination/f'{factor}x';folder.mkdir(exist_ok=True)
            for old in folder.glob('*'):
                if old.is_file(): old.unlink()
            platform=fixture(factor);(folder/'compiled-fixture.repl').write_text(platform)
            path=temp/f'{factor}x.repl';path.write_text(platform)
            def run(seconds): return 'emulation RunFor "'+format(seconds,'.12g')+'"'
            lines += [f'mach create "accelerated-functional-{factor}x-NO-CPU"',f'machine LoadPlatformDescription @{path}',
                'sysbus.checks Prepare',run(1),'sysbus.checks EndPwmBeginFull',run(1),
                'sysbus.checks CheckInitialHeatRate',run(150/factor-1),'sysbus.checks EndFullBeginCooling',run(20/factor),
                'sysbus.checks CheckCoolingBeginOpen',run(1),'sysbus.checks CheckOpenResetShort',run(1),
                'sysbus.checks CheckResetAndBeginRecovery',run(1),'sysbus.checks CheckRecoveryAndBeginLong',
                run(115/factor),'sysbus.checks CheckOutOfTable',run(1100/factor),'sysbus.checks Finish',run(1),
                'sysbus.checks CheckPostLatchEdges',f'sysbus.checks WriteResults "{folder}/actual-plant"',
                f'sysbus.nativeNozzleHeaterBinding WriteStatus "{folder}/nozzle-binding.json"',
                f'sysbus.syntheticBedHeaterBinding WriteStatus "{folder}/bed-binding.json"','mach clear']
        lines += ['quit'];script='\n'.join(lines)+'\n';(temp/'test.resc').write_text(script)
        (destination/'executed-script.resc').write_text(script)
        env=dict(os.environ,HOME=str(temp/'home'),XDG_CONFIG_HOME=str(temp/'home/.config'),TMPDIR=str(temp))
        started=time.monotonic()
        try:
            result=subprocess.run([str(ROOT/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(temp/'test.resc')],
                env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout)
            output=result.stdout
        except subprocess.TimeoutExpired as error:
            output=error.stdout or ''
            if isinstance(output,bytes): output=output.decode(errors='replace')
            (destination/'unit-tests.log').write_text(output)
            raise RuntimeError('Bounded CPU-free test timed out; no aggregate pass claimed') from error
        wall=time.monotonic()-started
        (destination/'unit-tests.log').write_text(output)
        clean=re.sub(r'\x1b\[[0-9;]*m','',output)
        assert result.returncode==0,clean[-15000:]
        assert not re.search(r'error CS\d|Error while|Could not compile|Unhandled exception|There was an error|Errors during compilation|\[ERROR\]|No such command',clean),clean[-15000:]
        stages=['PREPARED','GPIO PWM PASS','INITIAL RATE PASS','TARGET CROSSING PASS','COOLING PASS','FAULT RESET PASS',
                'RESET RECOVERY PREPARED','RESET RECOVERY PASS','OUT OF TABLE PASS','LONG NEGATIVES PASS','TESTS PASS:']
        results=[]
        for factor in FACTORS:
            folder=destination/f'{factor}x'
            report=json.loads((folder/'actual-plant.json').read_text())
            assert len(report['completed_stages'])==len(stages),report
            assert all(any(s.startswith('ACCELERATED FUNCTIONAL THERMAL '+stage) for s in report['completed_stages']) for stage in stages),report
            assert report['assertions']>=150 and report['dropped_rows']==0,report
            assert not report['native_firmware_run'] and not report['direct_duty_used'] and not report['temperature_injection_used']
            results.append(dict(factor=factor,result=report,analysis=analyze_trace(folder,factor)))
        assert protected_inputs()==before,'A protected input changed during validation'
        aggregate=dict(scope='Actual unchanged C# models and GPIO/ADC in CPU-free Renode only. No native firmware, native PID, watchdog, regulation or hardware validity.',
            wall_seconds=wall,results=results,protected_source_sha256=before,compiled_source_sha256=compiled_hashes,
            protected_inputs_unchanged=True,model_update_microseconds=10000,native_firmware_run=False)
        summary.write_text(json.dumps(aggregate,indent=2)+'\n')
        print(f'ACTUAL UNCHANGED C# PASS: {sum(r["result"]["assertions"] for r in results)} assertions across {len(results)} factors; {wall:.3f}s wall')
        return aggregate

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-csharp',action='store_true',help='Explicitly start one small CPU-free model suite; never starts native firmware')
    parser.add_argument('--timeout',type=float,default=30)
    args=parser.parse_args()
    if not 0 < args.timeout <= 30: parser.error('Keep the explicit model-test budget between 0 and 30 seconds')
    OUT.mkdir(exist_ok=True)
    check_profiles_and_theory()
    if args.execute_csharp: execute_csharp(args.timeout)
    else: print('Actual C# not executed by this command; use --execute-csharp only in an approved lightweight test slot.')
