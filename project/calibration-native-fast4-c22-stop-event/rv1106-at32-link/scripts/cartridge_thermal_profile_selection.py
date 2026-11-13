"""Fresh equal4x virtual nozzle and bed heaters; immutable original thermal integration retained."""
import copy
import json
from pathlib import Path
import re
import thermal_profile_selection as original
PROFILE = 'synthetic-cartridge-4x'
EXPERIMENT = 'printer-shared-mcu/experimental/synthetic-cartridge-4x'
sha = original.sha

def original_args(args):
    result = copy.copy(args)
    if result.thermal_profile == PROFILE: result.thermal_profile = original.PROFILE
    return result

def validate(args):
    if args.thermal_profile not in ('none', PROFILE): raise ValueError('Only explicit 4x virtual cartridge is supported here')
    return original.validate(original_args(args))

def verify_sources(root):
    hashes = dict(original.verify_sources(root))
    for board,old_w,new_w in [('nozzle',60,240),('bed',200,800)]:
        source=root/EXPERIMENT/(board+'.repl');old=(root/original.EXPERIMENT/(board+'.repl')).read_text()
        key='heaterPowerWatts: '+str(old_w)
        if old.count(key)!=1 or source.read_text()!=old.replace(key,'heaterPowerWatts: '+str(new_w)):
            raise ValueError('Only exactly4x original model heater power may change: '+board)
    for name in ('nozzle.repl','bed.repl','parameters.json'):
        path=root/EXPERIMENT/name;hashes[str(path.relative_to(root))]=sha(path)
    return hashes

def prepare_setup(root, args, main, nozzle, motor):
    validate(args)
    if args.thermal_profile != 'none': verify_sources(root)
    return original.prepare_setup(root, original_args(args), main, nozzle, motor)

def select(root, generated, args, *, publish=True):
    validate(args)
    if args.thermal_profile == 'none': return original.select(root, generated, args, publish=publish)
    hashes = verify_sources(root)
    result = original.select(root, generated, original_args(args), publish=False)
    extra = generated / 'thermal-profile'
    manifest_path=generated/'manifest.json';manifest=json.loads(manifest_path.read_text())
    for board,namespace in [('nozzle','PrinterNozzle'),('bed','PrinterMain')]:
        source=root/EXPERIMENT/(board+'.repl');dest=extra/(board+'.repl')
        text=source.read_text().replace('Antmicro.Renode.Peripherals.AT32','Antmicro.Renode.Peripherals.'+namespace)
        dest.write_text(re.sub(r'\bAT32\.',namespace+'.',text))
        matches=[entry for entry in manifest if entry['generated']==str(dest.relative_to(generated))]
        if len(matches)!=1:raise ValueError('Exactly one generated '+board+' ADC writer required')
        matches[0].update(source=str(source.relative_to(root)),source_sha256=sha(source),generated_sha256=sha(dest))
    for entry in manifest:
        if entry.get('experimental_thermal_profile') == original.PROFILE: entry['experimental_thermal_profile'] = PROFILE
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    info = result['profile']
    info['selection'] = PROFILE
    info['parameters'] = copy.deepcopy(info['parameters'])
    info['parameters']['nozzle']['heater_power_w'] = 240
    info['parameters']['bed']['heater_power_w'] = 800
    info['heater_power_multipliers']={'nozzle':4,'bed':4}
    info['original_model_heater_power_w']={'nozzle':60,'bed':200}
    info['physical_heater_ratings_verified']=False
    info.update(synthetic=True, hardware_transferable=False, pid_values_hardware_transferable=False,
                cartridge_power_multiplier=4, real_pid_validation=False,
                purpose='Virtual-only full native calibration. Synthetic PID values MUST NOT be used on physical hardware.',
                baseline_integration_helper_sha256=info['integration_helper_sha256'],
                integration_helper_sha256=sha(Path(__file__)))
    info['source_sha256'] = hashes
    info['files'] = {str(p.relative_to(generated)): sha(p) for p in sorted(extra.iterdir())}
    if publish:
        (args.log_dir / 'thermal-profile.json').write_text(json.dumps(info,indent=2)+'\n')
    return result

def final_commands(args):
    return original.final_commands(original_args(args))
