import tempfile
from pathlib import Path
import unittest
from prepare_diagnostic import prepare

class GuardTests(unittest.TestCase):
    def test_existing_output_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with self.assertRaisesRegex(ValueError,'new directory'):
                prepare(root,root,root)
    def test_unknown_recipe_refused_before_output(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);recipe=root/'rv1106-linux-display-128diag/prepare.py'
            recipe.parent.mkdir();recipe.write_text('raise Exception("must not execute")')
            with self.assertRaisesRegex(ValueError,'recipe mismatch'):
                prepare(root,root,root/'new')
            self.assertFalse((root/'new').exists())
    def test_symlink_output_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out=root/'link';out.symlink_to(root/'missing')
            with self.assertRaisesRegex(ValueError,'new directory'):
                prepare(root,root,out)

if __name__=='__main__':unittest.main()
