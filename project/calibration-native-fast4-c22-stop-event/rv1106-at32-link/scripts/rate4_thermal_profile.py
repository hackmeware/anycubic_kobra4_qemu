"""Explicit cold-setup-only hypothetical thermal rate4; no clock or firmware changes."""
import json,copy,re
from pathlib import Path
import cartridge_thermal_profile_selection as base
PROFILE='synthetic-cartridge-4x-rate4-diagnostic'
EXPERIMENT='printer-shared-mcu/experimental/synthetic-cartridge-4x-rate4-diagnostic'
PINS={'nozzle': '03ae2327c097ffe1fb1cf34ffe993bea3381c97830bc969f4a84861214551581', 'bed': 'a4883b0566efed2fba21ae4fbb3f2cc440b3190321a7b9e1887a54cc642b1c87'}
def verify(root):
    for b,d in PINS.items():
        p=root/EXPERIMENT/(b+'.repl')
        if base.sha(p)!=d:raise ValueError('Rate4 source changed: '+b)
        old=(root/base.EXPERIMENT/(b+'.repl')).read_text()
        before,after=(20,5) if b=='nozzle' else (600,150)
        key='heatCapacityJoulesPerKelvin: '+str(before)+'\n'
        if old.count(key)!=1 or p.read_text()!=old.replace(key,'heatCapacityJoulesPerKelvin: '+str(after)+'\n'):raise ValueError('Rate4 changes must be C-only')
def transform_info(info):
    info=copy.deepcopy(info);info['selection']=PROFILE
    info['parameters']['nozzle']['heat_capacity_j_per_k']=5
    info['parameters']['bed']['heat_capacity_j_per_k']=150
    info['thermal_rate_diagnostic']={'factor':4,'baseline':base.PROFILE,'hypothetical':True,'physical_equivalence':False,'pid_transferable':False}
    for b,d in PINS.items():info['source_sha256'][EXPERIMENT+'/'+b+'.repl']=d
    return info
def apply(root,generated,result):
    verify(root)
    manifest_path=generated/'manifest.json';manifest=json.loads(manifest_path.read_text())
    for b,ns in [('nozzle','PrinterNozzle'),('bed','PrinterMain')]:
        source=root/EXPERIMENT/(b+'.repl');dest=generated/'thermal-profile'/(b+'.repl')
        text=source.read_text().replace('Antmicro.Renode.Peripherals.AT32','Antmicro.Renode.Peripherals.'+ns)
        dest.write_text(re.sub(r'\bAT32\.',ns+'.',text))
        matches=[e for e in manifest if e['generated']==str(dest.relative_to(generated))]
        if len(matches)!=1:raise ValueError('Exclusive thermal writer required')
        matches[0].update(source=str(source.relative_to(root)),source_sha256=base.sha(source),generated_sha256=base.sha(dest))
    for e in manifest:
        if e.get('experimental_thermal_profile')==base.PROFILE:e['experimental_thermal_profile']=PROFILE
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    result['profile']=transform_info(result['profile'])
    result['profile']['files']={str(p.relative_to(generated)):base.sha(p) for p in sorted((generated/'thermal-profile').iterdir())}
    return result
