"""Pure positive-readiness veto; never replaces the existing strict fault review.

Evidence is the current run's append-only console, original backend/UI logs,
and one guest barrier marker attesting a captured-child-owned kernel listener.
No network, RPC, process control, emulator imports or synthetic native records.
"""
import hashlib
import math
import re

CONTRACT = 'c22-native-ui-startup-v1'
RUN_NAME = 'native-fast4-86400s-c23'
MAX_CONSOLE = 32 * 1024 * 1024
PHASE_SOURCE_NS = 30_000_000_000
PHASE_HOST_S = 3600.0
STAMP = r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}'
NATIVE = re.compile(r'^\[(' + STAMP + r')\] \[(\w+)\] \[([^\]\r\n]+)\] (.*)$')
CHANNEL = re.compile(r'channel:main_channel,state:GRPC_CHANNEL_(IDLE\(0\)|CONNECTING\(1\)|READY\(2\)|TRANSIENT_FAILURE\(3\)|SHUTDOWN\(4\))')


def parse(text, run_name):
    """Only complete normalized lines; echoed shell commands cannot match."""
    if run_name != RUN_NAME:
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


class StartupReadiness:
    def __init__(self, run, *, host_start):
        if run.name != RUN_NAME: raise ValueError('Wrong startup run name')
        self.run = str(run)
        self.host_start = host_start
        self.previous = b''
        self.epoch = None
        self.last_source = None
        self.last_host = host_start
        self.ui_start_host = self.ui_start_source = None
        self.failure = None
        self.receipt = None

    def observe(self, raw, text, *, host_now, source_ns, epoch, final=False):
        if self.failure is not None: raise ValueError('Latched startup gate: ' + self.failure)
        try:
            return self._observe(raw, text, host_now=host_now, source_ns=source_ns, epoch=epoch, final=final)
        except Exception as error:
            self.failure = str(error)
            raise

    def _observe(self, raw, text, *, host_now, source_ns, epoch, final):
        if type(raw) is not bytes or len(raw) > MAX_CONSOLE or not raw.startswith(self.previous):
            raise ValueError('Startup console replaced/truncated/oversize')
        if not isinstance(epoch, str) or not re.fullmatch('[0-9a-f]{32}', epoch) or self.epoch not in (None, epoch):
            raise ValueError('Wrong or replaced startup epoch')
        if (type(source_ns) is not int or source_ns < 0 or self.last_source is not None and source_ns < self.last_source or
                type(host_now) not in (float, int) or not math.isfinite(host_now) or host_now < self.last_host):
            raise ValueError('Invalid/backward startup clocks')
        state = parse(text, RUN_NAME)
        # Check deadlines before admitting newly arrived evidence. Late records
        # cannot revive a previously closed phase, even in one complete sample.
        prior = self.receipt or {}
        if not prior.get('backend', False) and (source_ns >= PHASE_SOURCE_NS or host_now - self.host_start >= PHASE_HOST_S):
            raise TimeoutError('Backend startup readiness deadline')
        if self.ui_start_source is not None and not prior.get('startup_complete', False):
            if source_ns - self.ui_start_source >= PHASE_SOURCE_NS or host_now - self.ui_start_host >= PHASE_HOST_S:
                raise TimeoutError('Native UI readiness deadline')
        if state['backend'] and self.ui_start_source is None:
            self.ui_start_source, self.ui_start_host = source_ns, host_now
        if final and not state['startup_complete']: raise ValueError('Final native UI readiness absent')
        self.previous = raw
        self.epoch, self.last_source, self.last_host = epoch, source_ns, host_now
        self.receipt = {**state, 'contract': CONTRACT, 'run': self.run, 'epoch': epoch,
                        'observed_source_ns': source_ns, 'console_bytes': len(raw),
                        'console_sha256': hashlib.sha256(raw).hexdigest(), 'failure': None}
        return self.receipt


def require_report(record, run, epoch, *, after_native_pid=False):
    """Additional veto only; caller must still run the unchanged console gate."""
    proof = record.get('ui_startup_readiness', {})
    native = record.get('native_console_review', {})
    if (proof.get('contract') != CONTRACT or proof.get('run') != str(run) or proof.get('epoch') != epoch or
            proof.get('startup_complete' if after_native_pid else 'ready') is not True or proof.get('channel_ready') is not True or proof.get('failure') is not None or
            proof.get('observed_source_ns') != record.get('last_shared_mcu_ns') or
            proof.get('console_bytes') != native.get('console_bytes') or
            proof.get('console_sha256') != native.get('console_sha256')):
        raise ValueError('Native UI channel/PrinterState readiness is not verified for current run')
