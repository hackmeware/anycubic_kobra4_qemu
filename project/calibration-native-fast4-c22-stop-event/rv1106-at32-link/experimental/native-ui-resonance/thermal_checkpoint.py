#!/usr/bin/env python3
"""Read-only, source-time dual-heater guard and immutable evidence checkpoint.

This does not operate a printer, send native commands, stop an emulator, certify
PID completion, or open a launch gate. An owner must stop on a failed assessment.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat

PACKAGE = Path(__file__).resolve().parent
MAX_BYTES = 32 * 1024 * 1024
MAX_ROWS = 100000
MAX_AGE_US = 200000
# Static early-stop ceilings for the separately proposed initial-response test.
# Neither native PID targets nor successful PID/cooling are inferred.
CAPS = {'bed': 120.0, 'nozzle': 260.0}
CANONICAL_SHA256 = '4f24b723e18e0c7165731a2df1ee7685a175707b4f030198d376873e5dbf9b6f'
HEADERS = {'bed': 'time_us,virtual_time_ns,event,changed_pin,changed_level,pa0_level,pa0_config,pa0_latch,physical_temperature_c,published_adc_code,sensor_curve,sensor_fault,model_overtemperature,model_heater_latched_off,last_heater_duty,last_fan_duty,thermal_updates', 'nozzle': 'time_us,event,changed_pin,changed_level,pb8_level,pb9_level,pb8_config,pb9_config,pb8_latch,pb9_latch,physical_temperature_c,published_adc_code,sensor_curve,sensor_fault,curve_out_of_range,model_overtemperature,model_heater_latched_off,last_heater_duty,last_fan_duty,thermal_updates'}
ANSI = re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]')
ERROR = re.compile(rb'There was an error|No such command or device:|Unhandled exception|\[(?:ERROR|FATAL)\]|\bDisposed\.')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_regular(path, maximum=MAX_BYTES):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as f:
        initial = os.fstat(f.fileno())
        if not stat.S_ISREG(initial.st_mode) or initial.st_size > maximum:
            raise ValueError('Not a bounded regular evidence file: ' + path.name)
        raw = f.read(initial.st_size)
        after = os.stat(path, follow_symlinks=False)
        if (after.st_dev, after.st_ino) != (initial.st_dev, initial.st_ino) or after.st_size < initial.st_size or len(raw) != initial.st_size:
            raise ValueError('Evidence replaced or truncated during read: ' + path.name)
        return raw


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def integer(value, label):
    require(re.fullmatch(r'[0-9]+', str(value)) is not None, 'Invalid integer: ' + label)
    return int(value)


def number(value, label):
    value = float(value)
    require(math.isfinite(value), 'Non-finite ' + label)
    return value


def verify_profile(profile):
    raw = (PACKAGE / 'canonical-thermal-profile.json').read_bytes()
    require(sha(raw) == CANONICAL_SHA256, 'Canonical thermal contract changed')
    canonical = json.loads(raw)
    if profile.get("selection") == "synthetic-cartridge-4x-rate4-diagnostic":
        import rate4_thermal_profile
        canonical = rate4_thermal_profile.transform_info(canonical)
    for key, expected in canonical.items():
        require(profile.get(key) == expected, 'Wrong selected thermal profile field: ' + key)
    contract = profile.get('pid_first_composition', {})
    require(contract.get('baseline_factor') == 1 and contract.get('native_launch_gate_open') is False,
            'Missing exact baseline-1x PID composition declaration')


def parse_trace(raw, heater, boundary_us, final=False):
    require(raw and (not final or raw.endswith(b'\n')), heater + ' missing/truncated final CSV')
    complete = raw[:raw.rfind(b'\n') + 1]
    require(complete.split(b'\n',1)[0].decode('ascii') == HEADERS[heater], heater + ' unexpected CSV header')
    rows = list(csv.DictReader(io.StringIO(complete.decode('ascii'))))
    require(0 < len(rows) < MAX_ROWS, heater + ' empty/capped stream')
    previous_stamp = previous_updates = 0
    periodic = []
    heater_edges = 0
    all_edges = 0
    max_temp = -math.inf
    previous_levels = None
    rise_seen = False
    response_chain_observed = False
    pin = 'pa0' if heater == 'bed' else 'pb8'
    for i, row in enumerate(rows):
        require(None not in row and all(v is not None for v in row.values()), heater + ' malformed CSV row')
        stamp = integer(row['time_us'], 'source time')
        updates = integer(row['thermal_updates'], 'update counter')
        require(stamp >= previous_stamp and updates >= previous_updates, heater + ' backward clock/counter')
        require(stamp <= boundary_us, heater + ' telemetry ahead of confirmed source boundary')
        require(stamp - previous_stamp <= MAX_AGE_US, heater + ' missing telemetry interval')
        require(abs(updates - stamp // 10000) <= 1, heater + ' automatic physics tick count inconsistent')
        if heater == 'bed':
            require(integer(row['virtual_time_ns'], 'bed epoch') == stamp * 1000, 'bed source epoch mismatch')
        temperature = number(row['physical_temperature_c'], 'physical temperature')
        require(25 <= temperature < (150 if heater == 'bed' else 400), heater + ' impossible model temperature')
        max_temp = max(max_temp, temperature)
        adc = integer(row['published_adc_code'], 'ADC code')
        require(0 < adc < 4095, heater + ' ADC rail/fault')
        if heater == 'bed':
            resistance = 100000 * math.exp(3950 * (1/(temperature+273.15)-1/298.15))
            expected_adc = math.floor(4095*resistance/(4700+resistance)+0.5)
            require(adc == expected_adc, 'bed temperature/ADC divider mismatch')
        require(0 <= number(row['last_heater_duty'], 'heater duty') <= 1, heater + ' invalid heater duty')
        require(number(row['last_fan_duty'], 'fan duty') == 0, heater + ' unexpected fan coupling')
        pins = ('pa0',) if heater == 'bed' else ('pb8','pb9')
        levels = {}
        for gpio in pins:
            require(row[gpio+'_level'] in ('0','1') and row[gpio+'_latch'] in ('0','1'), heater + ' invalid resolved GPIO/latch')
            require(0 <= integer(row[gpio+'_config'], 'GPIO configuration') <= 15, heater + ' invalid GPIO configuration')
            levels[gpio] = row[gpio+'_level']
            if previous_levels is not None and levels[gpio] != previous_levels[gpio]:
                require(row['event']=='edge' and row['changed_pin']==gpio.upper(), heater + ' unrecorded GPIO level change')
        require(row['sensor_fault'] == 'none' and row['model_overtemperature'] == '0' and row['model_heater_latched_off'] == '0', heater + ' thermal safety/fault indication')
        curve = 'B3950 100k 4700ohm illustrative divider' if heater == 'bed' else 'NTC ZM3863 HNS112HC4570G0'
        require(row['sensor_curve'] == curve, heater + ' unexpected sensor curve')
        if heater == 'nozzle':
            require(row['curve_out_of_range'] == '0', 'nozzle curve range fault')
        if row['event'] != 'edge':
            require(row['changed_pin']=='' and row['changed_level']=='', heater + ' non-edge row contains edge metadata')
        if row['event'] == 'sample':
            require(stamp % 100000 == 0 and (not periodic or stamp-periodic[-1] == 100000), heater + ' missing/repeated periodic sample')
            periodic.append(stamp)
        elif row['event'] == 'edge':
            all_edges += 1
            require(row['changed_pin'] in (('PA0',) if heater == 'bed' else ('PB8','PB9')), heater + ' unexpected GPIO event')
            if row['changed_pin'] == pin.upper():
                heater_edges += 1
                if row['changed_level']=='1':rise_seen=True
            changed=row['changed_pin'].lower()
            require(row['changed_level'] == row[changed+'_level'], heater + ' resolved edge mismatch')
            require(previous_levels is not None and previous_levels[changed] != row[changed+'_level'], heater + ' repeated/nonalternating edge')
        else:
            require((i == 0 and row['event'] == 'snapshot:stream_started'), heater + ' reset/clear/unexpected snapshot')
        if rise_seen and number(row['last_heater_duty'], 'duty')>0 and temperature>25 and adc < (3911 if heater=='bed' else 4023):
            response_chain_observed=True
        previous_stamp, previous_updates = stamp, updates
        previous_levels = levels
    first = rows[0]
    require(first['event'] == 'snapshot:stream_started' and first['time_us'] == '0' and first['thermal_updates'] == '0', heater + ' missing zero-epoch stream start')
    require(first['physical_temperature_c'] == '25' and first['published_adc_code'] == ('3911' if heater == 'bed' else '4023') and first['last_heater_duty']=='0' and first[pin+'_level']=='0', heater + ' initial ambient/binding state not established')
    require(boundary_us-previous_stamp <= MAX_AGE_US, heater + ' stale physical trace')
    require(len(periodic) == previous_stamp // 100000, heater + ' incomplete periodic history')
    return {'rows':len(rows),'samples':len(periodic),'all_edges':all_edges,'heater_edges':heater_edges,
            'latest_source_us':previous_stamp,'source_age_us':boundary_us-previous_stamp,
            'maximum_temperature_c':max_temp,'early_stop_required':max_temp>=CAPS[heater],
            'early_stop_temperature_c':CAPS[heater],
            'response_chain_observed':response_chain_observed,'causal_equation_replay_verified':False,
            'latest':rows[-1],'complete_prefix_bytes':len(complete),
            'complete_prefix_sha256':sha(complete)}, rows, complete


def final_status(raw, summary, boundary_us):
    s=json.loads(raw)
    for key in ('dropped_rows','stream_dropped_rows','stream_error_count'):
        require(s.get(key)==0, 'Final telemetry loss/error: '+key)
    for key in ('capacity_reached','stream_capacity_reached','stream_write_outcome_uncertain','streaming','stream_requested'):
        require(s.get(key) is False, 'Final telemetry incomplete: '+key)
    require(s.get('last_stream_error') == '', 'Final stream error string')
    require(s.get('stream_rows_written')==summary['rows'], 'Final stream counter mismatch')
    require(s.get('observed_periodic_samples')==summary['samples'] and s.get('observed_edges')==summary['all_edges'], 'Final observer counter mismatch')
    require(s.get('rows')==summary['rows']+1, 'Final buffered row counter mismatch')
    require(s.get('last_export_time_us')==boundary_us, 'Final export source boundary mismatch')


def binding_status(raw, heater, summary):
    b=json.loads(raw)
    for key in ('direct_duty_override_used','temperature_override_used'):
        require(b.get(key) is False, 'Override used/unknown: '+key)
    require(b.get('reset_observations')==0,'Thermal binding reset observed')
    if heater=='bed':
        require(b.get('binding')=='resolved main PA0 to thermal input 0, active high' and b.get('hypothetical_fixture') is True, 'Wrong bed binding')
        require(b.get('initial_level') is False and b.get('current_resolved_level') == (summary['latest']['pa0_level']=='1'), 'Bed resolved binding state mismatch')
        require(b.get('forwarded_edges')==summary['heater_edges'], 'Bed binding edge count mismatch')
    else:
        require(b.get('heater_connected') is True and b.get('pb9_fan_connected') is False, 'Wrong nozzle binding/fan')
        require(b.get('initial_resolved_pb8_level') is False and b.get('current_resolved_pb8_level') == (summary['latest']['pb8_level']=='1'), 'Nozzle resolved binding mismatch')
        require(b.get('forwarded_gpio_edges')==summary['heater_edges'], 'Nozzle binding edge count mismatch')


def verify_final_ack(raw, run, captured=None):
    ack=json.loads(raw)
    require(ack.get('status')=='complete' and ack.get('batches'), 'Final export acknowledgement incomplete')
    thermal=False
    windows=[]
    exports=[]
    for index,batch in enumerate(ack['batches']):
        require(batch.get('status')=='complete' and batch.get('log')=='renode.log', 'Final batch incomplete/wrong shared log')
        begin,end=batch.get('begin_marker',''),batch.get('end_marker','')
        require(re.fullmatch(r'FINAL_EXPORT_(main|nozzle|motor)_[a-f0-9]{32}_BEGIN',begin) is not None and end==begin[:-5]+'END','Invalid final markers')
        start=integer(batch['log_start_offset'],'log start'); stop=integer(batch['log_end_offset'],'log end')
        require(0 < stop-start <= 1024*1024 and (not windows or start>=windows[-1][1]),'Invalid final log window')
        windows.append((start,stop))
        fd=os.open(run/'renode.log',os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as f:
            require(stat.S_ISREG(os.fstat(f.fileno()).st_mode),'Final log not regular')
            f.seek(start); segment=f.read(stop-start)
        require(len(segment)==stop-start,'Final log window missing')
        capture_name='final-export-window-'+str(index).zfill(3)+'.bin'
        if captured is not None:captured[capture_name]=segment
        exports.append({'capture_file':capture_name,'source_start':start,'source_end':stop,'sha256':sha(segment)})
        lines=[ANSI.sub(b'',l).strip(b'\r') for l in segment.split(b'\n')]
        require(not ERROR.search(b'\n'.join(lines)),'Final monitor error')
        require(lines.count(begin.encode())==1 and lines.count(end.encode())==1 and lines.index(begin.encode())<lines.index(end.encode()),'Final response markers not ordered/unique')
        bounded=lines[lines.index(begin.encode())+1:lines.index(end.encode())]
        if b'THERMAL_PID_FINAL_BEGIN' in bounded or b'THERMAL_PID_FINAL_END' in bounded:
            require(not thermal and bounded.count(b'THERMAL_PID_FINAL_BEGIN')==bounded.count(b'THERMAL_PID_FINAL_END')==1,'Duplicate/missing thermal final envelope')
            require(bounded.index(b'THERMAL_PID_FINAL_BEGIN')<bounded.index(b'THERMAL_PID_FINAL_END'),'Thermal final envelope reversed')
            thermal=True
    require(thermal,'No acknowledged dual-thermal export envelope')
    return {'complete':True,'batches':len(windows),'thermal_envelope_confirmed':True,'log_windows':exports}


def checkpoint(run, output, epoch, final=False, previous=None):
    run=run.resolve(); output=output.resolve()
    require(not output.exists(), 'Checkpoint output already exists')
    captured={}; report={'schema':1,'run_directory':str(run),'epoch':epoch,'mode':'final' if final else 'live',
        'passed':False,'native_calibration_complete':False,'launch_gate_open':False,'failures':[],
        'scope':'Independent model telemetry only; native Ready, homing, targets, PID state and real sensor provenance need separate evidence.'}
    def read(name):
        captured[name]=read_regular(run/name);return captured[name]
    try:
        step_raw=read('renode-step.json');step=json.loads(step_raw)
        require(step.get('source')=='renode-shared-mcu-step' and step.get('epoch')==epoch and step.get('paused') is True and step.get('time_went_backwards') is False,'Wrong/unconfirmed source epoch/boundary')
        ns=integer(step['virtual_time_ns'],'source boundary');require(ns%1000==0,'Non-microsecond source boundary')
        boundary=ns//1000;report['source_time_ns']=ns
        verify_profile(json.loads(read('thermal-profile.json')))
        prior=json.loads((previous/'checkpoint.json').read_text()) if previous else None
        if prior:
            require(prior['epoch']==epoch and prior['run_directory']==str(run) and prior['source_time_ns']<=ns,'Prior checkpoint run/epoch/time mismatch')
        report['heaters']={}
        for heater in ('bed','nozzle'):
            name=heater+'-thermal-live.csv';raw=read(name)
            summary,rows,complete=parse_trace(raw,heater,boundary,final)
            captured[name]=complete
            if prior:
                old=prior['heaters'][heater]
                require(sha(complete[:old['complete_prefix_bytes']])==old['complete_prefix_sha256'],'Previously checkpointed thermal prefix changed')
            report['heaters'][heater]=summary
            if final:
                final_status(read(heater+'-thermal-live-status.json'),summary,boundary)
                buffer_raw=read(heater+'-thermal.csv')
                require(buffer_raw.endswith(b'\n') and buffer_raw.split(b'\n',1)[0].decode('ascii')==HEADERS[heater], 'Final buffer schema/truncation error')
                buffered=list(csv.DictReader(io.StringIO(buffer_raw.decode('ascii'))))
                require(len(buffered)==len(rows)+1 and buffered[0]['event']=='snapshot:observer_attached' and buffered[1:]==rows,'Final buffered/live trace divergence')
                binding_status(read(heater+'-heater-binding.json'),heater,summary)
        if final:
            report['final_ack']=verify_final_ack(read('final-export.json'),run,captured)
        require(read_regular(run/'renode-step.json')==step_raw,'Source boundary changed during checkpoint')
        report['passed']=True
        report['early_stop_required']=any(h['early_stop_required'] for h in report['heaters'].values())
        report['within_initial_response_bound']=not report['early_stop_required']
    except (OSError,ValueError,KeyError,TypeError,UnicodeError) as error:
        report['failures'].append(type(error).__name__+': '+str(error))
    output.mkdir(parents=True,exist_ok=False)
    for name,raw in captured.items():
        with (output/name).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    report['captured_sha256']={name:sha(raw) for name,raw in captured.items()}
    with (output/'checkpoint.json').open('x') as f:
        json.dump(report,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    fd=os.open(output,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    fd=os.open(output.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--epoch',required=True);p.add_argument('--final',action='store_true');p.add_argument('--previous',type=Path)
    a=p.parse_args();r=checkpoint(a.run,a.output,a.epoch,a.final,a.previous)
    print(json.dumps(r,indent=2));raise SystemExit(0 if r['passed'] and not r.get('early_stop_required',False) else 2)


if __name__=='__main__':main()
