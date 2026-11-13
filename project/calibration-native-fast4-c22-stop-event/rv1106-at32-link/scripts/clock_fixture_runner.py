"""Explicit pre-application boot instrumentation for the diagnostic clock gate."""
import re
import time
from diagnostic_timer_clock import DiagnosticQMP, bootstrap_fixture, ClockError

def bootstrap_native_clock(pipe_base, console_path, process, ready_marker,
                           chunk_bytes=64, chunk_delay=.01, line_delay=.1, timeout=30):
    qmp=DiagnosticQMP.from_pipes(pipe_base,opt_in=True)
    def read_console():
        if process.poll() is not None:
            raise ClockError('QEMU exited during diagnostic clock bootstrap')
        return console_path.read_bytes()
    def exchange(command,marker,limit):
        start=len(read_console())
        remaining=command.encode()
        while remaining:
            newline=remaining.find(b'\n')
            count=min(chunk_bytes,newline+1 if newline>=0 else len(remaining))
            part=remaining[:count];remaining=remaining[count:]
            process.stdin.write(part);process.stdin.flush()
            time.sleep(line_delay if part.endswith(b'\n') else chunk_delay)
        deadline=time.monotonic()+limit
        pattern=re.compile(rb'(?:^|\n)'+re.escape(marker.encode())+rb'\r?\n')
        while time.monotonic()<deadline:
            observed=read_console()[start:]
            if pattern.search(observed):
                return observed.decode(errors='replace')
            time.sleep(.01)
        raise ClockError('Diagnostic console exchange timed out: '+marker)
    try:
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            banner=read_console()
            if ready_marker.encode() in banner and b'original vendor startup has not been run' in banner:
                break
            time.sleep(.01)
        else:
            raise ClockError('Verified offline shell did not start before diagnostic bootstrap deadline')
        bootstrap_fixture(qmp,qmp.clock,exchange,banner.decode(errors='replace'),timeout=timeout)
        before=qmp.now();time.sleep(.01)
        if qmp.now()!=before:
            raise ClockError('QEMU diagnostic counter advanced while paused')
        qmp.call('cont');time.sleep(.01);qmp.call('stop')
        qmp.clock.now(require_progress=True)
        paused=qmp.now();time.sleep(.01)
        if qmp.now()!=paused:
            raise ClockError('QEMU diagnostic counter did not remain paused')
        return qmp
    except Exception:
        try:qmp.call('stop')
        except Exception:pass
        qmp.close()
        raise
