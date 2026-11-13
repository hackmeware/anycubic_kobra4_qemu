"""Inert command generation only; never reads firmware or captured dump files."""
import ast
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent
PROFILE = HERE.parents[2]
RELATIVE = 'rv1106-at32-link/scripts/z_probe_selection.py'
CANDIDATE = HERE.parents[1] / 'scripts/z_probe_selection.py'
REMOVED_SOURCE = """             f'dump_file 0x20000000 0x5000 @{out}/final-nozzle-sram.bin',
             f'dump_file 0xE000ED28 0x8 @{out}/final-nozzle-fault-words.bin',
             'sysbus ReadDoubleWord 0xE000ED28', 'sysbus ReadDoubleWord 0xE000ED2C',
"""


def source_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FinalCommandsTests(unittest.TestCase):
    def test_exact_source_change_is_only_the_four_requested_command_deletions(self):
        original = (PROFILE / RELATIVE).read_text()
        candidate = CANDIDATE.read_text()
        self.assertEqual(original.count(REMOVED_SOURCE), 1)
        self.assertEqual(candidate, original.replace(REMOVED_SOURCE, ''))

    def test_every_other_function_constant_and_setup_ast_is_identical(self):
        def remainder(path):
            tree = ast.parse(path.read_bytes())
            tree.body = [node for node in tree.body if not isinstance(node, ast.FunctionDef) or node.name != 'final_commands']
            return ast.dump(tree, include_attributes=False)
        self.assertEqual(remainder(CANDIDATE), remainder(PROFILE / RELATIVE))

    def test_generated_final_commands_differ_by_exactly_four_deletions(self):
        old = source_module(PROFILE / RELATIVE, 'old_z_final_only')
        new = source_module(CANDIDATE, 'new_z_final_only')
        for out in (Path('/tmp/inert-c6'), Path('/tmp/inert c6'), Path('relative-inert')):
            with self.subTest(out=str(out)):
                args = SimpleNamespace(z_probe_profile='synthetic-functional', log_dir=out)
                before = old.final_commands(args).splitlines(keepends=True)
                after = new.final_commands(args).splitlines(keepends=True)
                removed = [f'dump_file 0x20000000 0x5000 @{out}/final-nozzle-sram.bin\n',
                           f'dump_file 0xE000ED28 0x8 @{out}/final-nozzle-fault-words.bin\n',
                           'sysbus ReadDoubleWord 0xE000ED28\n',
                           'sysbus ReadDoubleWord 0xE000ED2C\n']
                self.assertEqual([line for line in before if line not in after], removed)
                self.assertEqual(after, [line for line in before if line not in removed])
                self.assertEqual(len(before) - len(after), 4)
                self.assertFalse(any('dump_file' in line or 'ReadDoubleWord' in line for line in after))

    def test_disabled_profile_remains_empty_and_no_output_files_are_created(self):
        old = source_module(PROFILE / RELATIVE, 'old_z_disabled')
        new = source_module(CANDIDATE, 'new_z_disabled')
        args = SimpleNamespace(z_probe_profile='none', log_dir=Path('/tmp/never-used-c6'))
        self.assertEqual(old.final_commands(args), '')
        self.assertEqual(new.final_commands(args), '')


if __name__ == '__main__':
    unittest.main()
