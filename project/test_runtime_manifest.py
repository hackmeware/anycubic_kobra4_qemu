"""Exercise actual production verifier offline; no main or emulator calls."""
import importlib.util,sys,json,hashlib,tempfile,unittest,shutil
from pathlib import Path
sys.dont_write_bytecode=True
T=Path(__file__).resolve().parent;P=T/'calibration-native-fast4-c22-stop-event';R=P/'rv1106-at32-link/experimental/native-ui-resonance';spec=importlib.util.spec_from_file_location('runner_under_test',R/'runner.py');runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
class ProductionManifest(unittest.TestCase):
 def test_full_real_runtime_manifest(self):
  result=runner.verify_manifest(P);self.assertEqual(result['entry_count'],5489);(T/'RUNTIME-VERIFICATION.json').write_text(json.dumps(result,indent=2)+'\n')
 def test_negative_fixture_real_verifier(self):
  original_hash=runner.MANIFEST_SHA256;original_controls=runner.PINNED_CONTROLS
  try:
   with tempfile.TemporaryDirectory() as d:
    root=Path(d);doc=json.loads((R/'execution-manifest.json').read_text());mandatory={runner.OBSERVER_RELATIVE,runner.PROTOCOL_RELATIVE,runner.VALIDATOR_RELATIVE,runner.READY_REFERENCE_RELATIVE};generator='at32-renode/peripherals/a.cs';names=mandatory|{generator,'data/value'}
    h=hashlib.sha256(b'x').hexdigest();doc['files']={n:h for n in names};doc['symlinks']={};doc['absent_targets']=[];runner.PINNED_CONTROLS={}
    for folder in doc['generator_membership']:
     (root/folder).mkdir(parents=True);doc['generator_membership'][folder]=[generator] if folder=='at32-renode/peripherals' else []
    for name in names:
     f=root/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(b'x')
    manifest=root/runner.MANIFEST_RELATIVE;manifest.parent.mkdir(parents=True,exist_ok=True)
    def save():
     manifest.write_text(json.dumps(doc));runner.MANIFEST_SHA256=hashlib.sha256(manifest.read_bytes()).hexdigest()
    save();self.assertEqual(runner.verify_manifest(root)['entry_count'],len(names))
    for suffix in ['.cs','.repl','.resc']:
     extra=root/'at32-renode/peripherals'/('extra'+suffix);extra.write_bytes(b'x')
     with self.assertRaisesRegex(ValueError,'Generator input added'):runner.verify_manifest(root)
     extra.unlink()
    f=root/generator;f.unlink()
    with self.assertRaises(ValueError):runner.verify_manifest(root)
    f.write_bytes(b'y')
    with self.assertRaises(ValueError):runner.verify_manifest(root)
    f.write_bytes(b'x');data=root/'data';data.rename(root/'real');data.symlink_to(root/'real',target_is_directory=True)
    with self.assertRaisesRegex(ValueError,'symlink'):runner.verify_manifest(root)
    data.unlink();(root/'real').rename(data)
    # Membership cannot omit a still-pinned matching source.
    doc['generator_membership']['at32-renode/peripherals']=[];save()
    with self.assertRaises(ValueError):runner.verify_manifest(root)
    doc['generator_membership']['at32-renode/peripherals']=[generator];save()
    excluded=doc['archive_exclusions'];doc['archive_exclusions']={};save()
    with self.assertRaises(ValueError):runner.verify_manifest(root)
    doc['archive_exclusions']=excluded;doc['files'][next(iter(excluded))]=h;save()
    with self.assertRaises(ValueError):runner.verify_manifest(root)
  finally:runner.MANIFEST_SHA256=original_hash;runner.PINNED_CONTROLS=original_controls
if __name__=='__main__':unittest.main()
