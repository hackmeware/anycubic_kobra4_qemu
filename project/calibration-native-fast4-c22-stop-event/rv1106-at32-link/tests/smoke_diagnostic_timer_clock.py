"""Opt-in isolated simulator test. Native applications/MCU peers never start."""
import argparse
import json
import os
import pathlib
import select
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
from diagnostic_timer_clock import DiagnosticTimerClock, QMPStream, ClockError, StreamPair, bootstrap_fixture, DiagnosticQMP

p=argparse.ArgumentParser();p.add_argument('--enable-diagnostic-instrumentation',action='store_true')
a=p.parse_args()
if not a.enable_diagnostic_instrumentation:p.error('Explicit diagnostic instrumentation opt-in required')
root=pathlib.Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='timer-clock-smoke-') as tmp:
    qpipe=pathlib.Path(tmp)/'qmp'
    for suffix in ('.in','.out'): os.mkfifo(str(qpipe)+suffix)
    args=[str(root/'rv1106-qemu/bin/qemu-system-arm-display'),'-M','rv1106','-m','128M',
          '-cpu','cortex-a7,has_el3=off','-kernel',str(root/'rv1106-linux-display-128diag/linux-test.elf'),
          '-drive',f'if=sd,index=0,file={root}/inputs/offline-emmc.img,format=raw,snapshot=on',
          '-display','none','-serial','stdio','-monitor','none','-qmp',f'pipe:{qpipe}']
    proc=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    q=None
    try:
        guest_in=proc.stdin.fileno();guest_out=proc.stdout.fileno()
        transcript=bytearray()
        def until(marker, timeout=10):
            deadline=time.monotonic()+timeout
            while marker not in transcript:
                if time.monotonic()>deadline:raise ClockError('Guest console marker timeout: '+repr(marker))
                if select.select([guest_out],[],[],.1)[0]:
                    data=os.read(guest_out,65536)
                    if not data:raise ClockError('Guest exited')
                    transcript.extend(data)
        q=DiagnosticQMP.from_pipes(qpipe,opt_in=True)
        until(b'/ # ')
        if b'original vendor startup has not been run' not in transcript:raise ClockError('Not verified offline shell')
        clock=q.clock
        offline_banner=transcript.decode(errors='replace')
        def exchange(command, marker, timeout):
            transcript.clear()
            os.write(guest_in,command.encode())
            until(('\r\n'+marker+'\r\n').encode(),timeout)
            return transcript.decode(errors='replace')
        bootstrap_fixture(q,clock,exchange,offline_banner)
        paused0=clock.now();time.sleep(.1);paused1=clock.now()
        assert paused0==paused1, (paused0,paused1)
        q.call('cont');time.sleep(.12);q.call('stop')
        advanced=clock.now(require_progress=True)
        assert advanced>paused1
        time.sleep(.1);assert clock.now()==advanced
        # Reset must invalidate, even though this model preserves timer registers.
        try:
            q.call('system_reset')
            clock.now()
        except ClockError:reset_rejected=True
        else:raise AssertionError('Reset not rejected')
        print(json.dumps({'diagnostic_only':True,'native_apps_started':False,
                          'clock_frequency_modified':False,'paused_ns':[paused0,paused1],
                          'resumed_delta_ns':advanced-paused1,'reset_rejected':reset_rejected},indent=2))
    finally:
        if q:q.close()
        proc.terminate();_,stderr=proc.communicate(timeout=5)
        if proc.returncode not in (0,-15): print(stderr.decode(errors="replace"),file=sys.stderr)
