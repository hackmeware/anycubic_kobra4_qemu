"""Reconstructed readiness adapter; not full C22 fault review."""
import re

STAMP = r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}'
NATIVE = re.compile(r'^\[(' + STAMP + r')\] \[(\w+)\] \[([^\]\r\n]+)\] (.*)$')
CHANNEL = re.compile(r'channel:main_channel,state:GRPC_CHANNEL_(IDLE\(0\)|CONNECTING\(1\)|READY\(2\)|TRANSIENT_FAILURE\(3\)|SHUTDOWN\(4\))')


def readiness(text, run_name):
    """Only complete normalized lines; echoed shell commands cannot match."""
    if not re.fullmatch(r'ui-[a-z0-9][a-z0-9-]{7,55}', run_name):
        raise ValueError('Startup gate belongs to another run')
    state = {'begin': False, 'backend': False, 'launch_begin': False, 'launched': False, 'done': False,
             'listener_log': False, 'backend_ready_log': False,
             'channel_ready': False, 'main_ready': False, 'printer_ready': False}
    channel_stamp = main_stamp = printer_stamp = None
    saw_printer_ready = False
    # File tail forwarding can deliver backend records after the gate marker.
    # Both original backend records must still occur after the fresh begin.
    for line in text[:text.rfind('\n') + 1].splitlines():
        if line.startswith('C18_UI_'):
            if line == 'C18_UI_GATE_BEGIN run=' + run_name:
                if state['begin']: raise ValueError('Repeated startup begin')
                state['begin'] = True
            elif line.startswith('C18_UI_STARTUP_ABORT '):
                raise ValueError('Guest startup barrier aborted: ' + line)
            elif re.fullmatch(r'C18_UI_BACKEND_VERIFIED run=' + re.escape(run_name) + r' main_pid=[1-9]\d* start_ticks=\d+ socket_inode=[1-9]\d*', line):
                if not state['begin'] or state['backend'] or state['launched']:
                    raise ValueError('Repeated or out-of-order backend verification')
                state['backend'] = True
            elif line == 'C18_UI_LAUNCH_BEGIN run=' + run_name:
                if not state['backend'] or state['launch_begin']: raise ValueError('Repeated/out-of-order UI launch begin')
                state['launch_begin'] = True
            elif re.fullmatch(r'C18_UI_LAUNCHED run=' + re.escape(run_name) + r' ui_pid=[1-9]\d*', line):
                if not state['launch_begin'] or state['launched']:
                    raise ValueError('Repeated or out-of-order UI launch')
                state['launched'] = True
            else:
                raise ValueError('Malformed or other-run startup marker')
            continue
        if line == 'COLD_UI_STARTUP_COMMANDS_DONE':
            if not state['launched'] or state['done']: raise ValueError('Repeated/out-of-order startup completion')
            state['done'] = True
            continue
        match = NATIVE.fullmatch(line)
        if not match: continue
        stamp, severity, source, message = match.groups()
        if source == '103' and severity == 'info' and message == 'Server listening on 127.0.0.1:50051':
            if not state['begin']: raise ValueError('Stale listener evidence precedes this startup')
            state['listener_log'] = True
        if source == '527' and severity == 'info' and re.fullmatch(r'Printer is ready at \d+\.\d+\.', message):
            if not state['begin']: raise ValueError('Stale backend Ready precedes this startup')
            state['backend_ready_log'] = True
        channel = CHANNEL.fullmatch(message)
        if message.startswith('channel:main_channel,') and (channel is None or not source.startswith('_check_channel() in applink_client.cpp:')):
            raise ValueError('Unrecognized native main-channel state')
        if channel and source.startswith('_check_channel() in applink_client.cpp:'):
            if not state['launch_begin']: raise ValueError('UI evidence before current UI launch')
            if channel_stamp is not None and stamp < channel_stamp: raise ValueError('Reordered UI channel evidence')
            channel_stamp = stamp
            if channel[1] == 'READY(2)' and source == '_check_channel() in applink_client.cpp:194' and severity == 'info':
                state['channel_ready'] = True
            elif state['channel_ready']:
                raise ValueError('Native UI main channel regressed')
        if source == '_check_main_channel() in applink_client.cpp:153' and severity == 'info' and message == 'main channel is ready':
            if not state['launch_begin'] or not state['channel_ready'] or stamp < channel_stamp:
                raise ValueError('Main-ready callback lacks preceding channel READY')
            main_stamp = stamp
            state['main_ready'] = True
        if 'applink.PrinterStateResponse:' in message:
            if source != 'operator()() in request.cpp:1523' or severity != 'info':
                raise ValueError('Unrecognized PrinterState evidence')
            response = re.fullmatch(r'req_id:[0-9]+,applink\.PrinterStateResponse:\{state:([a-z_]+),state_message:([^,{}\r\n]*)\}', message)
            if response is None:
                raise ValueError('Malformed/error-bearing native PrinterState response')
            if not state['main_ready'] or stamp < main_stamp:
                raise ValueError('PrinterState precedes positive UI channel readiness')
            if printer_stamp is not None and stamp < printer_stamp: raise ValueError('Reordered PrinterState evidence')
            printer_stamp = stamp
            state['printer_ready'] = response.groups() == ('ready', 'Printer is ready')
            saw_printer_ready = saw_printer_ready or state['printer_ready']
    state['startup_complete'] = saw_printer_ready and all(value for key, value in state.items() if key != 'printer_ready')
    state['ready'] = state['startup_complete'] and state['printer_ready']
    return state


AUXILIARY = {
    ('error','218','Unable to read config file /app/etc/avata_main_mutable.cfg'),
    ('error','123','filament hub config file open failed: No such file or directory'),
    ('error','360','Unable to open config file /app/etc/ace_list.json'),
}
def parse(text,run_name):
    if len(text.encode())>32*1024**2: raise ValueError('Console exceeds bound')
    text=re.sub(r'\x1b\[[0-9;]*m','',text).replace('\r\n','\n')
    if any(ord(c)<32 and c not in '\n\t' or ord(c)==127 for c in text):
        raise ValueError('Unrecognized console control')
    state=readiness(text,run_name)
    records=[]
    for line in text[:text.rfind('\n')+1].splitlines():
        if line.startswith('UI_PREP_ABORT '):raise ValueError('Guest preparation aborted')
        if line.startswith('UI_DEVICES_VERIFIED ') and line!='UI_DEVICES_VERIFIED run='+run_name:
            raise ValueError('Wrong device run marker')
        match=NATIVE.fullmatch(line)
        if match: records.append((line,*match.groups()))
    ready=[stamp for line,stamp,severity,source,message in records if severity=='info' and source=='527' and re.fullmatch(r'Printer is ready at \d+\.\d+\.',message)]
    first=min(ready) if ready else None
    errors=[];limitations=[];faults=[]
    for line,stamp,severity,source,message in records:
        record={'line':line,'stamp':stamp,'severity':severity,'source':source,'message':message}
        if severity in ('error','critical','fatal'):errors.append(record)
        if (severity,source,message) in AUXILIARY and (first is None or stamp<first):limitations.append(record)
        elif severity in ('error','critical','fatal') or re.search(r'\b(shutdown|fault|emergency)\b|\b(?:MCU|sensor)\b.*\b(error|failed|timeout)\b',message,re.I):faults.append(record)
    return {**state,'ui_connection_ready':all(state[k] for k in ('begin','backend','launch_begin','launched','done','listener_log','backend_ready_log','channel_ready','main_ready')),'native_errors':errors,'startup_limitations':limitations,'unclassified_errors':faults,'fault_observed':bool(faults),'first_backend_ready_stamp':first,'full_c22_fault_review_performed':False}
