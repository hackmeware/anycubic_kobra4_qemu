"""Console flag patch logic tests, with no guest execution required."""
import importlib.util
import pathlib
import unittest

p = pathlib.Path(__file__).resolve().parents[1] / 'tools/run_console.py'
spec = importlib.util.spec_from_file_location('console', p)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class QMP:
    def __init__(self, gd=0xccffdf0):
        self.calls = []; self.gd = gd
    def command(self, cmd, args=None):
        self.calls.append(cmd)
        if cmd == 'human-monitor-command':
            return 'R08=00000000 R09=%08x R10=00000000' % self.gd


class QTest:
    def __init__(self, flags=0x22c3):
        self.flags = flags; self.commands = []; self.reply = ''
    def send(self, command):
        self.commands.append(command)
        if command.startswith('readl'):
            self.reply = 'OK 0x%x' % self.flags
        else:
            self.flags = int(command.split()[-1], 16); self.reply = 'OK'
    def read(self):
        return self.reply


class Console(unittest.TestCase):
    def test_clear_only_console_bit(self):
        qmp, qtest = QMP(), QTest()
        m.enable_console(qmp, qtest)
        self.assertEqual(qtest.flags, 0x2283)
        self.assertEqual(qmp.calls, ['stop', 'human-monitor-command', 'cont'])
        self.assertEqual(qtest.commands[1], 'writel 0xccffdf4 0x2283')

    def test_already_enabled_no_write(self):
        qmp, qtest = QMP(), QTest(0x2283)
        m.enable_console(qmp, qtest)
        self.assertEqual(len(qtest.commands), 1)

    def test_bad_pointer_and_early_boot_refused(self):
        for gd, flags in [(0, 0x22c3), (m.RAM, 0x22c3), (0xccffdf1, 0x22c3), (0xccffdf0, 0x40)]:
            qmp, qtest = QMP(gd), QTest(flags)
            with self.assertRaises(m.DebugError):
                m.enable_console(qmp, qtest)
            self.assertEqual(qtest.flags, flags)
            self.assertEqual(qmp.calls[-1], 'cont')


if __name__ == '__main__':
    unittest.main()
