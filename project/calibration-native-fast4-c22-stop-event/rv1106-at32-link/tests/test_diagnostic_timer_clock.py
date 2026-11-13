"""Pure unit tests; optional real QEMU smoke test lives in separate file."""
import io
import pathlib
import sys
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
from diagnostic_timer_clock import BASE, MASK64, ClockError, DiagnosticTimerClock, QMPStream, bootstrap_fixture

class FakeQMP:
    def __init__(self):
        self.count = MASK64
        self.load = MASK64
        self.control = 1
        self.pristine = True
        self.running = False
    def call(self, command, arguments=None):
        if command == 'query-status': return {'running': self.running}
        if command in ('stop','cont'):
            self.running=command=='cont';return {}
        parts = arguments['command-line'].split()
        count = int(parts[1][1:-2]); address = int(parts[2], 16)
        words = []
        for a in range(address, address + 4 * count, 4):
            offset = a - (BASE + 5 * 32)
            value = {0: self.load & 0xffffffff, 4: self.load >> 32,
                     8: self.count & 0xffffffff, 12: self.count >> 32,
                     16: self.control}.get(offset, 0)
            words.append(0 if self.pristine else value)
        return f'{address:016x}:' + ''.join(f' 0x{x:08x}' for x in words) + '\r\n'

class TimerTests(unittest.TestCase):
    def make(self):
        q = FakeQMP(); c = DiagnosticTimerClock(q, opt_in=True)
        script = c.bootstrap_commands(); self.assertIn('DIAGNOSTIC_TIMER_READY', script)
        q.pristine = False; c.arm(); return q, c
    def test_requires_opt_in(self):
        with self.assertRaises(ClockError): DiagnosticTimerClock(FakeQMP())
    def test_refuses_used_bank(self):
        q = FakeQMP(); q.pristine = False
        with self.assertRaises(ClockError): DiagnosticTimerClock(q, opt_in=True).bootstrap_commands()
    def test_requires_paused_bootstrap(self):
        q = FakeQMP(); q.running = True
        with self.assertRaises(ClockError): DiagnosticTimerClock(q, opt_in=True).bootstrap_commands()
    def test_ticks_and_pause(self):
        q,c=self.make(); q.count-=24000
        self.assertEqual(c.now(), 1000000); self.assertEqual(c.now(),1000000)
    def test_stale(self):
        q,c=self.make()
        with self.assertRaises(ClockError): c.now(require_progress=True)
    def test_reversal(self):
        q,c=self.make();q.count-=24000;c.now();q.count+=1
        with self.assertRaises(ClockError): c.now()
    def test_invariants(self):
        for attr,value in [('control',0),('load',MASK64-1)]:
            q,c=self.make();setattr(q,attr,value)
            with self.assertRaises(ClockError): c.now()
    def test_malformed_read_latches(self):
        q,c=self.make()
        q.call=lambda *args,**kwargs: 'garbage'
        with self.assertRaises(ClockError):c.now()
        self.assertTrue(c.failed)
    def test_rollover_retries(self):
        q,c=self.make()
        original=c._words
        highs=iter([0xffffffff,0xfffffffe,0xfffffffe,0xfffffffe])
        def words(address,count):
            if address==c.base+12:return [next(highs)]
            if address==c.base+8:return [0xfffffff0]
            return original(address,count)
        c._words=words
        self.assertGreater(c.now(),0)
    def test_bootstrap_rejects_app(self):
        q=FakeQMP();c=DiagnosticTimerClock(q,opt_in=True)
        def exchange(*args):return 'PID USER COMMAND\n123 root avata_main\n'
        with self.assertRaises(ClockError):
            bootstrap_fixture(q,c,exchange,'original vendor startup has not been run')
        self.assertFalse(c.prepared)
    def test_bootstrap_rejects_missing_banner(self):
        q=FakeQMP();c=DiagnosticTimerClock(q,opt_in=True)
        with self.assertRaises(ClockError):bootstrap_fixture(q,c,None,'')
        self.assertFalse(c.prepared)
    def test_qmp_reset(self):
        class Duplex:
            def __init__(self):self.input=io.BytesIO(b'{"QMP":{}}\n{"return":{},"id":1}\n{"event":"RESET"}\n')
            def readline(self):return self.input.readline()
            def write(self,b):pass
            def flush(self):pass
        q=QMPStream(Duplex())
        with self.assertRaises(ClockError): q.call('query-status')
        with self.assertRaises(ClockError): q.call('query-status')

if __name__ == '__main__': unittest.main()
