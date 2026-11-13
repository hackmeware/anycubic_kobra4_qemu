#!/usr/bin/env python3
"""Bounded native UI initial thermal response only. No injected RPC, G-code, or scripted touch.

This observer only launches the fixed fixture, reads its passive exports, and
requests stop. The parent navigates actual observed frames over VNC. The explicitly selected dual sensor model is attached only by the paused
production composition; native acquisition remains an evidence gate. No Ready, homing, or calibration report is fabricated.
The unchanged enclosing supervisors own resource and descendant cleanup.
"""
if not __debug__:
    raise SystemExit('Optimized Python is prohibited')

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[3]
ACTIVE_SECONDS = 86368
WORK_SECONDS = 86360
SHARED_STOP_NS = 720_000_000_000
CLEANUP_SECONDS = 8
THERMAL_FRESH_NS = 250_000_000
REPORT_NAME = 'native-calibration-attempt.json'
BASE_RELATIVE = 'rv1106-at32-link/experimental/sensor30-observation/observer.py'
BASE_SHA256 = '04311b970f4f1d250cb4d7ac2cc340275a616f1568a7ace9e81108d0d0723db9'
LAUNCHER_RELATIVE = 'rv1106-at32-link/experimental/native-ui-resonance/run_ui_fixture.sh'
LIS_ERROR = re.compile(r'(?i)(?:\b(?:error|failed|failure|invalid|timeout|fault)\b.*\blis2dw12\b|\blis2dw12\b.*\b(?:error|failed|failure|invalid|timeout|fault)\b)')
# Exact c5/c7 absent-interface evidence, not a general WLAN/error allowlist.
WLAN_MISSING_CONTROL = 'Failed to connect to non-global ctrl_ifname: wlan0  error: No such file or directory'
WLAN_MESSAGES = frozenset(("exec command 'wpa_cli -i wlan0 reconnect' failed, ",
                           "exec command 'wpa_cli -i wlan0 status' failed, ",
                           "exec command 'wpa_cli -i wlan0 scan' failed, "))
WLAN_WORD = re.compile(r'(?i)\b(?:wpa_cli|ctrl_ifname)\b')
ERROR_WORD = re.compile(r'(?i)\b(?:error|failed|failure|fault|timeout|invalid)\b')



def load_base(root):
    path = root / BASE_RELATIVE
    if path.is_symlink():
        raise ValueError('Symlink passive observer dependency')
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != BASE_SHA256:
        raise ValueError('Passive observer source identity mismatch')
    module = types.ModuleType('ui_identification_passive_base')
    module.__file__ = str(path)
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


def fixed_environment(root, cache):
    host_jit = os.environ.get('RENODE_HOST_JIT', 'default')
    if host_jit not in ('default', 'single-tier'):
        raise ValueError('RENODE_HOST_JIT must be default or single-tier')
    clock_opt_in = os.environ.get('C22_STOP_EVENT_OPT_IN', '0')
    if clock_opt_in not in ('0', '1'):
        raise ValueError('C22_STOP_EVENT_OPT_IN must be 0 or 1')
    clock_client = 'stop-event' if clock_opt_in == '1' else 'scalar'
    if os.environ.get('CLOCK_CLIENT', clock_client) != clock_client:
        raise ValueError('CLOCK_CLIENT conflicts with explicit opt-in')
    return {'PATH': '/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin:/usr/bin:/bin',
            'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPYCACHEPREFIX': cache,
            'HOME': str(root / 'at32-runtime/home'),
            'XDG_CONFIG_HOME': str(root / 'at32-runtime/home/.config'),
            **{key: str(root / 'runtime-private' / name) for key, name in (
                ('TMPDIR', 'tmp'), ('TMP', 'tmp'), ('TEMP', 'tmp'), ('XDG_CACHE_HOME', 'cache'),
                ('XDG_DATA_HOME', 'data'), ('XDG_STATE_HOME', 'state'), ('XDG_RUNTIME_DIR', 'xdg-runtime'))},
            'RUN_SECONDS': str(ACTIVE_SECONDS), 'GLOBAL_QUANTUM_US': '1', 'NOZZLE_TMC_MODEL': 'autobaud',
            'LIS_PROFILE': 'rigid-xy39-mainY-nozzleX-proper-rotation-v1',
            'HEADLESS_READY_ONLY': '1', 'THERMAL_PROFILE': 'synthetic-cartridge-4x', 'Z_PROBE_PROFILE': 'synthetic-functional',
            'NATIVE_NOZZLE_HEATER': '0', 'RENODE_HOST_JIT': host_jit, 'CLOCK_CLIENT': clock_client, 'C22_STOP_EVENT_OPT_IN': clock_opt_in, 'ICOUNT_SHIFT': '0',
            'RENODE_BOOTSTRAP': 'legacy', 'PASSIVE_MOTOR_TRACE': '0', 'PASSIVE_PHYSICAL_TRACE': '1',
            'PASSIVE_CONTACT_TRACE': '1', 'RECOVERED_NOZZLE_NTC': '1', 'ASSUMED_XY_DIAG_CABLE': '1',
            'MOTOR_ENABLE_WIRING': 'mcu-control-only', 'PASSIVE_NOZZLE_TRACE': '1',
            'PASSIVE_HOMING_GPIO': '1', 'PASSIVE_TMC_TRACE': '1',
            'Z_BED_RELATIVE_MM': '-10', 'Z_OPPOSITE_STOP_RELATIVE_MM': '252', 'Z_BED_SIDE': 'minimum',
            'Z_STIFFNESS_N_PER_MM': '20', 'Z_DAMPING_NS_PER_MM': '0.05', 'Z_COUNTS_PER_N': '10000',
            'Z_HISTORY_CAPACITY': '4096', 'Z_QUERY_TRACE_ROWS':'1000000', 'Z_SENSOR_TRACE_ROWS':'2000000',
            'QEMU_BINARY': str(root / 'rv1106-at32-link/experimental/clock-snapshot/runtime/run-baseline')}


SENSOR_STATUS_SHA256 = 'a7227dc3ac258c0e09ee5ef15d2ca0f455636c1739b53959a639e879c81d9a22'
INITIAL_RESPONSE_SHA256 = '2a27d62e88090bb6f7be96f5548019df9efb44b71432c7e44ef7e60d21ba7e41'
THERMAL_VALIDATOR_SHA256 = '33d176bacc0c12c3bf916ca55fcc7452beb04320cb7a7ef8d63cbb9815f12573'
NATIVE_PROGRESS_SHA256 = '8cba197eb17932849804eea07ceb51655f65f0d19abdd4ecf64895590ba1cdd8'
GPIO_CAPTURE_SHA256 = '3948ca7c3e98ea79beed2788f1b8f24abaa4f24026f365482c802775cca7284e'
FINAL_CAPTURE_SHA256 = 'caf3762a807dd01d1d5fafb81706f588f184372d2f42d1f9916bcb8930687406'
THERMAL_CANONICAL_SHA256 = '4f24b723e18e0c7165731a2df1ee7685a175707b4f030198d376873e5dbf9b6f'


def load_pinned(path, expected, name):
    if path.is_symlink() or not isinstance(expected,str):
        raise ValueError('Unfrozen thermal experiment dependency')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError('Thermal experiment source identity mismatch: '+path.name)
    module=types.ModuleType(name);module.__file__=str(path)
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module


def deadlines(elapsed, now):
    if (not math.isfinite(elapsed) or elapsed < 0 or elapsed >= WORK_SECONDS or
            now is not None and now >= SHARED_STOP_NS):
        raise TimeoutError('Absolute observer work/shared budget reached')


class Runtime:
    monotonic = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)
    launch = staticmethod(subprocess.Popen)


def run(root, run_name, cache, runtime=None):
    runtime=runtime or Runtime();base=load_base(root);base.verify_classification_baseline()
    here=root/'rv1106-at32-link/experimental/native-ui-resonance'
    criteria=load_pinned(here/'initial_response.py',INITIAL_RESPONSE_SHA256,'initial_response')
    thermal=load_pinned(here/'thermal_checkpoint.py',THERMAL_VALIDATOR_SHA256,'thermal_checkpoint')
    if hashlib.sha256((here/'canonical-thermal-profile.json').read_bytes()).hexdigest()!=THERMAL_CANONICAL_SHA256:
        raise ValueError('Canonical thermal profile identity mismatch')
    wlan=load_pinned(here/'wlan_stream_review.py', '0e6cca8f19b856f415ed2052d2ffd24a44f58559600ae1cbca6c973ec6f974ee', 'wlan_stream_review')
    startup_module=load_pinned(here/'startup_readiness.py', '2ea0cc41c5416821cdb7da076a6084a80a8aee9821a87055232b991d3a24b2e0', 'startup_readiness')
    sensor_check=load_pinned(here/'sensor_status.py',SENSOR_STATUS_SHA256,'sensor_status')
    trace_cache=load_pinned(here/'exact_trace_cache.py', '1c357a3b6d212acf52585ab945ab0ad48ef095bc4169569b5167efb5bcc7b8d2', 'exact_trace_cache')
    state=criteria.InitialResponse(trace_cache.ExactTraceCache(thermal))
    progress=load_pinned(here/'native_progress.py',NATIVE_PROGRESS_SHA256,'native_progress').NativeProgress()
    directory=root/'runs'/run_name
    if directory.exists() or directory.is_symlink():raise ValueError('Fresh run required')
    start=runtime.monotonic();process=None;now=None;previous_console=b''
    startup=startup_module.StartupReadiness(directory,host_start=start)
    review=wlan.UiNativeReview(base);clock=base.Clock();step_previous=None
    clock_progress_host=start;clock_progress_ns=None
    baseline_reports={};intent_first_host=None;sensor_previous=None
    record={'schema_version':1,'phase':'waiting_dual_thermal_baseline','success':False,
        'initial_thermal_response_only':False,'calibration_completed':False,'full_pid_completion_claimed':False,
        'homing_completed':False,'physical_completion_proven':False,'ready_rpc_verified':False,
        'request_count':0,'requests':[],'rpc_commands':False,'gcode_commands':False,'scripted_touch':False,
        'ui_navigation':'parent observed-frame-gated public framebuffer and touch queue only',
        'sensor_model_attached':False,'sensor_attachment_planned':True,'native_sensor_acquisition_proven':False,'thermal_baseline_ready':False,'ready_log_observed':False,
        'startup_marker_observed':False,'native_readiness_verified':False,'final_export_requested':False,
        'emulator_termination_proves_native_heater_off':False,'native_target_zero_or_cooling_verified':False,
        'native_nozzle_curve_provenance':'Retained C# curve bytes are source-pinned. Original nozzle-thermal-recovered-evidence.json is missing; independent native-converter provenance, native interpreted temperature and physical calibration remain unverified.',
        'bounds':{'active_host_s':ACTIVE_SECONDS,'work_host_s':WORK_SECONDS,'shared_ns':SHARED_STOP_NS,
            'cleanup_host_s':CLEANUP_SECONDS,'sampled_heater_ceiling_c':{'nozzle':260,'bed':120},
            'clock_stall_host_s':criteria.CLOCK_STALL_HOST_S,'initial_clock_host_s':criteria.CLOCK_INITIAL_HOST_S,
            'first_duty_after_request_ns':criteria.FIRST_DUTY_NS,'response_after_duty_ns':criteria.RESPONSE_NS,'native_pid_log_after_intent_ns':criteria.PID_LOG_DEADLINE_NS,'input_outcome_host_s':25,'input_outcome_source_ns':1_000_000_000},
        'native_error_review_scope':base.NATIVE_REVIEW_SCOPE}

    def elapsed():return runtime.monotonic()-start

    def save():
        record.update(host_elapsed_seconds=elapsed(),last_shared_mcu_ns=now,
                      native_auxiliary_occurrences=review.occurrences,native_console_review=review.summary(),
                      native_readiness_verified=review.native_readiness_verified,**state.summary(),**progress.summary())
        if directory.is_dir():
            base.atomic_json(directory/REPORT_NAME,record)
            if record.get('thermal_baseline_ready') is True:
                digest=hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()
                baseline_reports[digest]=now
                for old in list(baseline_reports):
                    if now-baseline_reports[old]>criteria.FRESH_NS:del baseline_reports[old]
                while len(baseline_reports)>512:del baseline_reports[next(iter(baseline_reports))]

    def confirmed_boundary(minimum_ns=0):
        nonlocal step_previous
        path=directory/'renode-step.json'
        began=runtime.monotonic()
        while True:
            step=base.safe_json(path)
            if (step.get('schema')!=1 or step.get('source')!='renode-shared-mcu-step' or
                    step.get('enabled') is not True or step.get('paused') is not True or
                    step.get('time_went_backwards') is not False or
                    not isinstance(step.get('epoch'),str) or not step['epoch'] or
                    type(step.get('step_id')) is not int or step['step_id']<0 or
                    type(step.get('virtual_time_ns')) is not int or step['virtual_time_ns']<0):
                raise ValueError('Invalid confirmed shared source boundary')
            if step_previous and (step['epoch']!=step_previous['epoch'] or
                    step['step_id']<step_previous['step_id'] or step['virtual_time_ns']<step_previous['virtual_time_ns'] or
                    step['step_id']==step_previous['step_id'] and step!=step_previous):
                raise ValueError('Replaced/backward source step')
            shared=base.safe_json(directory/'virtual-time.json');published=clock.observe(shared)
            if shared['epoch']!=step['epoch']:raise ValueError('Source and published clock epochs differ')
            if published>=step['virtual_time_ns']>=minimum_ns:
                step_previous=step;return step['virtual_time_ns']
            if runtime.monotonic()-began>=2:
                raise TimeoutError('No confirmed source boundary for captured thermal rows')
            runtime.sleep(.02)

    def sample(*,final=False):
        nonlocal now,previous_console,clock_progress_host,clock_progress_ns,intent_first_host,sensor_previous
        record['thermal_baseline_ready']=False
        raw_by_heater={}
        for heater in ('bed','nozzle'):
            path=directory/(heater+'-thermal-live.csv')
            if path.exists():raw_by_heater[heater]=thermal.read_regular(path)
            elif heater in state.heaters:raise ValueError(heater+' thermal stream disappeared')
        sensor_path=directory/'sensor-status.json'
        sensor=base.safe_json(sensor_path) if sensor_path.exists() else None
        if sensor is None and record['sensor_model_attached']:raise ValueError('LIS status disappeared')
        if (directory/'renode-step.json').exists():
            # Read only complete captured rows, then wait boundedly for their
            # actual source acknowledgement. Never advance or freeze a clock.
            latest=0
            for raw in raw_by_heater.values():
                complete=raw[:raw.rfind(b'\n')+1].splitlines()
                if len(complete)>1:latest=max(latest,thermal.integer(complete[-1].split(b',',1)[0].decode('ascii'),'last source row')*1000)
            if sensor is not None:
                sensor_check.check(sensor,None)
                latest=max(latest,sensor['virtual_time_ns'])
            now=confirmed_boundary(latest)
        if now is not None:
            if now!=clock_progress_ns:clock_progress_ns=now;clock_progress_host=runtime.monotonic()
            elif not final and runtime.monotonic()-clock_progress_host>=criteria.CLOCK_STALL_HOST_S:
                raise criteria.ControlledStop('No source clock progress within 120 host seconds')
        elif not final and elapsed()>=criteria.CLOCK_INITIAL_HOST_S:
            raise criteria.ControlledStop('No confirmed source clock within 300 host seconds')
        sensor_ready=False
        if sensor is not None:
            record['sensor_status']=sensor
            sensor_ready=sensor_check.check(sensor,now)
            if sensor_previous is not None:
                if any(sensor[k]<sensor_previous[k] for k in ('sequence','virtual_time_ns','source_captures','published_pairs','superseded_pairs')) or (sensor['sequence']==sensor_previous['sequence'] and sensor!=sensor_previous):raise ValueError('LIS status replaced/backward')
                if any(sensor[b]['consumed_source_samples']<sensor_previous[b]['consumed_source_samples'] for b in ('main','nozzle')):raise ValueError('LIS consumed source counter regressed')
            sensor_previous=sensor
            record['sensor_model_attached']=True
            record['sensor_status']=sensor
        if now is not None and now>=1000000000 and not sensor_ready:raise ValueError('LIS coherent source/readiness missing at startup')
        path=directory/'console.bin';ready=False;markers=[];text=None
        if path.exists():
            raw=base.safe_bytes(path,base.MAX_CONSOLE)
            if not raw.startswith(previous_console):raise ValueError('Console truncated/rewritten')
            previous_console=raw;text=wlan.native_text(raw.decode('utf-8',errors='replace'),base)
            for line in base.ANSI.sub('',text).splitlines():
                if LIS_ERROR.search(line):
                    record['first_lis2dw12_error']=line
                    raise ValueError('Sensor error before complete calibration: '+line)
            ready=review.observe(raw,host_now=runtime.monotonic(),source_ns=now,final=final)
            markers=re.findall(r'(?m)^COLD_UI_STARTUP_COMMANDS_DONE\r?$',text)
            if len(markers)>1:raise ValueError('Repeated UI startup marker')
        elif previous_console:raise ValueError('Console disappeared')
        if now is not None and step_previous is not None:
            record['ui_startup_readiness']=startup.observe(previous_console,text or '',
                host_now=runtime.monotonic(),source_ns=now,epoch=step_previous['epoch'],final=final)
        intent_path=directory/'ui-pid-intent.json'
        if intent_path.exists():
            intent=base.safe_json(intent_path)
            frame=intent.get('observed_frame',{});action=intent.get('consumed_action',{})
            frame_sha=intent.get('frame_sha256')
            if (intent.get('schema')!=1 or intent.get('run')!=str(directory) or step_previous is None or
                    intent.get('epoch')!=step_previous['epoch'] or intent.get('parent_confirmation_attested') is not True or
                    intent.get('native_request_acceptance_proven') is not False or
                    intent.get('purpose')!='original_ui_calibration_confirmation_native_pid_start' or
                    frame.get('actual_display_pixels') is not True or frame.get('identity',{}).get('run')!=str(directory) or
                    frame.get('identity',{}).get('epoch')!=intent['epoch'] or
                    not isinstance(frame_sha,str) or re.fullmatch('[0-9a-f]{64}',frame_sha) is None or
                    frame.get('frame_sha256')!=frame_sha or action.get('frame_sha256')!=frame_sha or
                    action.get('state')!='consumed_before_send' or action.get('action')!='pointer_down_up' or
                    action.get('x')!=intent.get('x') or action.get('y')!=intent.get('y') or
                    action.get('visible_label')!=intent.get('visible_label')):
                raise ValueError('Invalid observed-frame-bound UI PID intent')
            if state.intent_sha256 is None:
                review.require_clear()
                if not record.get('ui_startup_readiness',{}).get('ready'):raise ValueError('PID intent without native UI readiness')
                baseline_sha=intent.get('baseline_report_sha256')
                if baseline_sha not in baseline_reports or baseline_reports[baseline_sha]!=intent.get('baseline_shared_ns'):
                    raise ValueError('PID intent baseline digest was not emitted by this observer')
                intent_first_host=runtime.monotonic()
            if type(intent.get('source_ns')) is int and intent['source_ns']>now:now=confirmed_boundary(intent['source_ns'])
            state.arm_intent(hashlib.sha256(json.dumps(intent,sort_keys=True).encode()).hexdigest(),
                intent.get('source_ns'),intent.get('baseline_shared_ns'),now)
            outcome_path=directory/'ui-pid-input-outcome.json'
            if outcome_path.exists():
                outcome=base.safe_json(outcome_path)
                if (outcome.get('pid_intent_sha256')!=state.intent_sha256 or
                        outcome.get('down_state')!='queued_not_receipt_proven' or
                        outcome.get('release_state')!='queued_not_receipt_proven' or
                        any(key in outcome for key in ('hold_error','release_error'))):
                    raise ValueError('PID confirmation input outcome uncertain or failed; no retry')
                outcome_sha=hashlib.sha256(json.dumps(outcome,sort_keys=True).encode()).hexdigest()
                if record.get('ui_pid_input_outcome_sha256',outcome_sha)!=outcome_sha:raise ValueError('PID confirmation input outcome changed')
                record['ui_pid_input_outcome_sha256']=outcome_sha
                record['ui_pid_input_completed_not_receipt_proven']=True
            elif record.get('ui_pid_input_completed_not_receipt_proven'):raise ValueError('PID confirmation input outcome disappeared')
            elif final:raise ValueError('Final PID input outcome missing; release/dispatch remains unverified')
            elif runtime.monotonic()-intent_first_host>=25 or now-state.intent_ns>=1_000_000_000:
                raise criteria.ControlledStop('PID input outcome absent after 25 host seconds or 1 source second; dispatch/release unverified')
        elif state.intent_sha256 is not None:raise ValueError('UI PID intent disappeared')
        if text is not None:
            # Only request validation uses Ready independently of tail completeness.
            # New intent/down admission and thermal/phase gates remain strict.
            # A permitted error prefix is undecidable, not accepted or ignored.
            # Defer request review only; traces and original deadlines run below.
            if not review.provisional_tail_fault:
                state.console(base.ANSI.sub('',text),now,
                              ready=bool(review.native_readiness_verified and markers),final=final)
            progress.observe(base.ANSI.sub('',text),state.intent_ns is not None)
        record.update(ready_log_observed=ready,startup_marker_observed=bool(markers))
        profile=directory/'thermal-profile.json'
        if profile.exists():
            thermal.verify_profile(base.safe_json(profile));state.profile_verified=True
        if now is not None and now>=1_000_000_000 and (len(raw_by_heater)!=2 or not state.profile_verified):
            raise ValueError('Required dual thermal streams/profile missing at source startup')
        if len(raw_by_heater)==2 and now is not None:
            state.traces(raw_by_heater,now,final=final)
        record['thermal_baseline_ready']=bool(ready and markers and record.get('ui_startup_readiness',{}).get('ready') is True and len(state.heaters)==2 and
            state.profile_verified and sensor_ready and state.intent_ns is None and not final)
        if not review.admission_clear:record['phase']='waiting_native_console_review'
        elif state.request_line is not None:record['phase']='observing_native_calibration'
        elif state.intent_ns is not None:record['phase']='waiting_native_pid_log'
        elif record['thermal_baseline_ready']:record['phase']='waiting_ui_pid_request'

    def sample_and_save():
        # No UI can bind before the run directory exists.
        if not directory.is_dir():
            sample();deadlines(elapsed(),now);save();return
        with wlan.admission_lock(directory,monotonic=runtime.monotonic,sleep=runtime.sleep):
            try:
                sample();deadlines(elapsed(),now)
            except BaseException:
                record['thermal_baseline_ready']=False
                save()
                raise
            save()

    def stop(reason):
        record['thermal_baseline_ready']=False
        if directory.is_dir():
            if not (directory/'stop-request').exists():base.create_bytes(directory/'stop-request',reason.encode()+b'\n')
            record['final_export_requested']=True

    try:
        process=runtime.launch([str(root/LAUNCHER_RELATIVE),run_name],env=fixed_environment(root,cache))
        while process.poll() is None:
            sample_and_save()
            if (directory/'stop-request').exists():
                record.update(phase='external_controlled_stop',stop_reason='Existing owner/supervisor stop request');break
            runtime.sleep(.1)
        else:record['phase']='launcher_exited'
    except criteria.ControlledStop as exc:
        record.update(phase='calibration_observation_bound_stop',stop_reason=str(exc))
    except (Exception,KeyboardInterrupt) as exc:
        record.update(phase='stopped_on_error',error=type(exc).__name__+': '+str(exc))
    finally:
        stop(record.get('stop_reason','Initial thermal observer stopped; no retries, direct commands, target clearing or cooling claim.'))
        save()
        if process is not None:
            try:record['launcher_exit_code']=process.wait(timeout=min(CLEANUP_SECONDS,max(0,ACTIVE_SECONDS-elapsed())))
            except subprocess.TimeoutExpired:record['cleanup_timeout']=True
            except Exception as exc:record['cleanup_error']=type(exc).__name__+': '+str(exc)
        stopping_phase=record['phase']
        try:sample(final=True)
        except criteria.ControlledStop as exc:record['final_bound_observation']=str(exc)
        except Exception as exc:record['final_observation_error']=type(exc).__name__+': '+str(exc)
        record['phase']=stopping_phase
        if step_previous is not None:
            try:
                assessment=thermal.checkpoint(directory,directory/'thermal-final-assessment',step_previous['epoch'],final=True)
                record['final_thermal_assessment']={key:assessment.get(key) for key in
                    ('passed','within_initial_response_bound','early_stop_required','failures','heaters','final_ack')}
            except Exception as exc:record['final_thermal_assessment_error']=type(exc).__name__+': '+str(exc)
        try:
            final_capture=load_pinned(here/'final_capture.py',FINAL_CAPTURE_SHA256,'final_capture')
            record['final_capture_assessment']=final_capture.assess(directory,here)
        except Exception as exc:record['final_capture_assessment_error']=type(exc).__name__+': '+str(exc)
        try:record['final_sensor_assessment']=sensor_check.assess_final(directory,thermal,None if step_previous is None else step_previous['epoch'])
        except Exception as exc:record['final_sensor_assessment_error']=type(exc).__name__+': '+str(exc)
        record['thermal_baseline_ready']=False
        record['success']=record['calibration_completed']=record['full_pid_completion_claimed']=False
        save()
    return record


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--run-name',required=True)
    parser.add_argument('--seconds',type=int,default=ACTIVE_SECONDS);args=parser.parse_args(argv)
    if args.seconds!=ACTIVE_SECONDS or not re.fullmatch('[a-zA-Z0-9_-]+',args.run_name):
        raise SystemExit('Fixed budget and valid fresh run name required')
    cache=sys.pycache_prefix
    if (not sys.flags.isolated or not sys.dont_write_bytecode or type(cache) is not str or not Path(cache).is_absolute() or Path(cache).exists() or Path(cache).is_symlink() or Path(cache).name!=args.run_name+'-python-cache' or not Path(cache).parent.is_dir() or os.environ.get('PYTHONPYCACHEPREFIX')!=cache):
        raise SystemExit('Fresh isolated disabled-bytecode supervisor cache required')
    record=run(ROOT,args.run_name,cache)
    return 0 if record.get('success') else 2


if __name__=='__main__':raise SystemExit(main())
