#!/usr/bin/env python3
"""Independent sensor/analytic checks of the actual CPU-free C# trace, not a simulator."""
import csv,hashlib,json,math,pathlib
base=pathlib.Path(__file__).resolve().parent;root=base.parents[2];out=base/'results'
recovered_path=root/'evidence/recovered-nozzle-thermal/nozzle-thermal-recovered-evidence.json'
recovered=json.loads(recovered_path.read_text())
def nozzle_adc(t):
    if t < -40:return 4095
    if t > 360:return 0
    for s in recovered['live_converter']['segments']:
        upper,m,c=(s[k] for k in ['resistance_upper_breakpoint_ohms','temperature_per_ohm','temperature_intercept_celsius'])
        if t < upper*m+c:continue
        resistance=(t-c)/m
        return math.floor(4095*resistance/(4700+resistance)+.5)
    raise AssertionError('No recovered segment for temperature')
def bed_adc(t):
    resistance=100000*math.exp(3950*(1/(t+273.15)-1/298.15))
    return math.floor(4095*resistance/(4700+resistance)+.5)
rows=list(csv.DictReader((out/'actual-plant.csv').open()))
assert rows and all(float(a['virtual_seconds'])<float(b['virtual_seconds']) for a,b in zip(rows,rows[1:]))
sensor_checks=0
for row in rows:
    assert float(row['nozzle_fan_duty'])==0,'Unbound PB9 cannot create a fan duty'
    for sensor,converter in [('nozzle',nozzle_adc),('bed',bed_adc)]:
        fault=row[sensor+'_fault']
        expected=4095 if fault=='open' else 0 if fault=='short' else converter(float(row[sensor+'_c']))
        assert int(row[sensor+'_adc'])==expected,(sensor,row,expected)
        sensor_checks+=1
for sensor in ['nozzle','bed']:
    assert {'none','open','short'} <= {r[sensor+'_fault'] for r in rows}
    assert all(r[sensor+'_latch']=='False' for r in rows),'Primary fixtures must remain untripped'
bytime={float(r['virtual_seconds']):r for r in rows}
assert float(bytime[151]['nozzle_c'])>230 and float(bytime[151]['bed_c'])>60
assert float(bytime[171]['nozzle_c'])<float(bytime[151]['nozzle_c'])
assert float(bytime[171]['bed_c'])<float(bytime[151]['bed_c'])
theory={}
for name,power,capacity,loss,target,code in [('nozzle',60,20,.2,230,nozzle_adc(230)),('bed',200,600,1.5,60,bed_adc(60))]:
    native=json.loads((root/('nozzle-renode' if name=='nozzle' else 'at32-renode')/'docs/verified-adc-configuration.json').read_text())['adc_objects'][0]
    assert native['minimum_sum']<=code*native['sample_count']<=native['maximum_sum']
    theory[name]={'power_w':power,'capacity_j_per_k':capacity,'conductance_w_per_k':loss,'ambient_c':25,
        'target_c':target,'target_adc_code':code,'initial_full_power_rate_c_per_s':power/capacity,
        'unclamped_full_duty_equilibrium_c':25+power/loss,'time_constant_s':capacity/loss,
        'full_power_time_from_ambient_s':-capacity/loss*math.log(1-(target-25)*loss/power),
        'steady_target_duty':(target-25)*loss/power,'target_inside_original_adc_guard':True}
report={'scope':'Independent analysis of CPU-free actual C# trace and recovered conversion data. No native high-temperature success claim.',
        'trace_rows':len(rows),'sensor_readings_checked':sensor_checks,'theory':theory,
        'recovered_curve_evidence_sha256':hashlib.sha256(recovered_path.read_bytes()).hexdigest(),
        'trace_sha256':hashlib.sha256((out/'actual-plant.csv').read_bytes()).hexdigest(),
        'native_firmware_run':False,'fan_thermal_coupling_modeled':False}
(out/'analysis.json').write_text(json.dumps(report,indent=2)+'\n')
print(f'INDEPENDENT THERMAL ANALYSIS PASS: {len(rows)} rows, {sensor_checks} sensor checks')
