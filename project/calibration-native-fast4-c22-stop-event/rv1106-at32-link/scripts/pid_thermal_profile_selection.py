"""Strict baseline-1x thermal composition for the observed PID-first UI route.

No launcher, native command, runtime mutation, clock or firmware changes here.
Known passive c8 setup/final commands are accepted as whole exact templates,
not through an expanded general monitor-command allowlist.
"""
import copy
import hashlib
import json
import os
import types
from pathlib import Path
import re

import cartridge_thermal_profile_selection as baseline
import rate4_thermal_profile as rate4

CONTRACT = Path(__file__).with_name('native-long-contract')
ROOT = Path(__file__).resolve().parents[2]
PROFILE = baseline.PROFILE
CONTRACT_SHA256 = {'source-delta.json': '3b4bb03ba25481c5f9bde58a380b0f797ec41ba576d1a75072fa64bbe0731fa0', 'source-pins.json': '5d5c60eab58b0a6d23ea7b75dcc3f1e5d2dc990ed8cf181149decb8598bf4e46', 'templates/main-final.commands': '7b1118be393f4b51df0d62f1cddea7e156e8a44ca5b93525a4926b06fb5e5914', 'templates/main-setup.commands': 'a9cdb4020414c50dd09a9d0d466c6e1aac5cb4647318dcda0057272c37750b50', 'templates/motor-setup.commands': '1340571357a0885c8ea04c5daa79786f676a169484f51cc4d34726950d6dfcba', 'templates/nozzle-final.commands': '591de3c0313a6dedad9fea231df248500fac73d6b83bd243cd2258f7d21afa8b', 'templates/nozzle-setup.commands': 'a0a53e1b865bbb05d0d78fe8ceb63603e09f4e1002446b4fa0d09da566747db4'}


def verify_contract():
    legacy=Path(__file__).with_name("thermal-pid-contract")/"source-pins.json"
    if baseline.sha(legacy)!="bdc41ed66a3513bc3ce166057464f7857c12d12be00eada25cab843eb88043aa":raise ValueError("Historical PID source pins changed")
    for relative, expected in CONTRACT_SHA256.items():
        path = CONTRACT / relative
        if not path.is_file() or baseline.sha(path) != expected:
            raise ValueError("PID thermal exact contract changed: " + relative)


def add_arguments(parser):
    parser.add_argument('--thermal-profile', choices=['none', PROFILE, rate4.PROFILE], default='none',
                        help='4x virtual nozzle cartridge; synthetic PID, never hardware transferable')



# Separately reviewed path-only c9 relocation. Original source-pins.json stays
# sealed and unchanged. No other generator bytes or profile names are accepted.
CAPTURE_RELOCATION = ('rv1106-at32-link/experimental/native-ui-resonance/prepare_capture_commands.py', 'be709eb3e385c8ef61b20b2cc4f3b226c37e02cb7ad54c32e03aad37399f4c74', '61502b1f80772f61a049cc1eb331f2f38883fc7fd24017252bee5c4dec5fb755')


def source_digest_matches(relative, expected, observed, root_name):
    if observed == expected:
        return True
    return (root_name == 'calibration-thermal-pid-c9' and
            (relative, expected, observed) == CAPTURE_RELOCATION)


def safe_path(path):
    value = str(Path(path).resolve())
    if any(c.isspace() or c in '\"@${}' for c in value):
        raise ValueError('Unsafe path in exact thermal PID setup')
    return value


def render(name, root, run):
    verify_contract()
    text = (CONTRACT / 'templates' / (name + '.commands')).read_text()
    return text.replace('${RUN_DIR}', safe_path(run)).replace('${PROFILE_ROOT}', safe_path(root)).splitlines()


def verify_sources(root):
    if root.name!="calibration-native-fast4-c22-stop-event":raise ValueError("Exact c10 profile required")
    verify_contract()
    pins = json.loads((CONTRACT / 'source-pins.json').read_text())
    observed = {}
    for relative, expected in pins.items():
        path = root / relative
        actual = baseline.sha(path) if path.is_file() else None
        if not source_digest_matches(relative, expected, actual, root.name):
            raise ValueError('PID thermal component changed; independent review required: ' + relative)
        observed[relative] = actual
    # Original thermal component gate is preserved, not rewritten or bypassed.
    baseline.verify_sources(root)
    return observed


def original_args(args):
    result = copy.copy(args)
    if result.thermal_profile == rate4.PROFILE: result.thermal_profile = PROFILE
    # Final commands are validated by exact full-template equality below.
    result.mcu_final_commands = result.nozzle_final_commands = None
    return result


def validate(args):
    if args.thermal_profile == 'none':
        return baseline.validate(args)
    if args.thermal_profile not in (PROFILE, rate4.PROFILE):
        raise ValueError('PID route permits explicit synthetic cartridge 4x only')
    baseline.validate(original_args(args))
    verify_sources(ROOT)
    if args.thermal_profile == rate4.PROFILE: rate4.verify(ROOT)
    for board, path in [('main', args.mcu_final_commands), ('nozzle', args.nozzle_final_commands)]:
        if path is None or path.read_text().splitlines() != render(board + '-final', ROOT, args.log_dir):
            raise ValueError('Exact PID thermal final diagnostic template required: ' + board)


def prepare_setup(root, args, main, nozzle, motor):
    if args.thermal_profile == 'none':
        return baseline.prepare_setup(root, args, main, nozzle, motor)
    if root.resolve() != ROOT:
        raise ValueError('PID thermal helper loaded from a different profile root')
    validate(args)
    for board, commands in [('main', main), ('nozzle', nozzle), ('motor', motor)]:
        if commands != render(board + '-setup', root, args.log_dir):
            raise ValueError('Exact PID thermal setup template required: ' + board)
    # Exercise original exclusive-ADC/quantum/geometry checks on the same thermal
    # portion. Extra public observers were matched against full pinned templates.
    minimum_main = ['include @scripts/virtual-bed-ntc.resc']
    minimum_nozzle = ['include @scripts/virtual-nozzle-recovered-ntc.resc',
                     'include @scripts/virtual-tmc2209.resc',
                     'include @scripts/passive-tmc-timing-observer.resc',
                     'emulation SetGlobalQuantum "0.000001"']
    minimum_motor = [line for line in motor if line.startswith((
        'sysbus.electromechanicalPlant ConfigureRelativeContact ',
        'sysbus.electromechanicalPlant StartContactTrace '))]
    baseline.prepare_setup(root, original_args(args), minimum_main, minimum_nozzle, minimum_motor)
    # Drop exactly the known cold ADC writers. All other accepted lines retain
    # their original order. No second heater or sensor/ADC writer is introduced.
    return ([line for line in main if line not in minimum_main],
            [line for line in nozzle if line != minimum_nozzle[0]], motor)


def select(root, generated, args):
    if args.thermal_profile == 'none':
        return baseline.select(root, generated, args)
    validate(args)
    result = baseline.select(root, generated, original_args(args), publish=False)
    if args.thermal_profile == rate4.PROFILE: result = rate4.apply(root, generated, result)
    info = result['profile']
    info['pid_first_composition'] = {
        'intended_profile': 'calibration-native-fast4-c22-stop-event',
        'baseline_factor': 1,
        'setup_policy': 'exact c10 long-run passive capture templates; sole unchanged thermal ADC writers',
        'contract_source_sha256': verify_sources(root),
        'helper_sha256': baseline.sha(Path(__file__)),
        'template_sha256': {p.name: baseline.sha(p) for p in sorted((CONTRACT / 'templates').iterdir())},
        'historical_controller_gate_reused': False,
        'native_launch_gate_open': False,
        'physical_pid_accuracy_claimed': False,
    }
    publish_profile(root, args.log_dir, info)
    return result


def publish_profile(root, log_dir, info):
    """Validate complete bytes, then publish once with atomic no-overwrite linking.

    The exclusive staged regular file remains as immutable publication evidence.
    There is no transient target, rename/disappearance exception or second writer.
    A failed/uncertain publication is terminal; this function never retries it.
    """
    path = root / 'rv1106-at32-link/experimental/native-ui-resonance/thermal_checkpoint.py'
    validator = types.ModuleType('selected_thermal_contract')
    validator.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), validator.__dict__)
    validator.verify_profile(info)
    raw = (json.dumps(info, indent=2) + '\n').encode('utf-8')
    if len(raw) > 65536:
        raise ValueError('Selected thermal metadata exceeds 64KiB publication bound')
    staged = log_dir / 'thermal-profile.json.pending'
    target = log_dir / 'thermal-profile.json'
    fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())
    # No overwrite even if a prior actor unexpectedly created the final target.
    os.link(staged, target, follow_symlinks=False)
    directory = os.open(log_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def final_commands(args):
    if args.thermal_profile == 'none':
        return baseline.final_commands(args)
    validate(args)
    # c8 acknowledge_batch retains these public response markers within the
    # existing bounded final batch. Both heaters export before its END response.
    result = ('echo "THERMAL_PID_FINAL_BEGIN"\n' + baseline.final_commands(original_args(args))
            + 'echo "THERMAL_PID_FINAL_END"\n')
    if getattr(args, 'lis_profile', 'none') != 'none':
        from native_dual_lis_selection import validate as validate_lis
        validate_lis(ROOT,args)
        result += 'mach set \"main\"\necho \"LIS_SENSOR_FINAL_BEGIN\"\n' + 'sysbus.nativeDualLis Close \"'+str(args.log_dir/'sensor-final.json')+'\"\necho \"LIS_SENSOR_FINAL_END\"\n'
    return result
