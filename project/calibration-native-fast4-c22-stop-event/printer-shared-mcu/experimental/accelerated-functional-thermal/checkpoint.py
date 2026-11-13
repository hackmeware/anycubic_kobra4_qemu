#!/usr/bin/env python3
"""Create a source/text-only checkpoint; never saves or restores machine state."""
import argparse, io, json, tarfile
from pathlib import Path
from generate import BASE, ROOT, sha
from checks import protected_inputs, SOURCE_INPUTS

def checkpoint(label):
    if not label or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in label):
        raise ValueError('Use a lowercase alphanumeric/hyphen checkpoint label')
    dest=BASE/'checkpoints';dest.mkdir(exist_ok=True)
    archive=dest/f'accelerated-functional-{label}-source.tar.gz'
    if archive.exists(): raise FileExistsError('Checkpoint labels are immutable: '+str(archive))
    prefix=BASE.relative_to(ROOT)
    files={}
    for path in sorted(BASE.rglob('*')):
        if not path.is_file() or any(part in ('checkpoints','__pycache__','dependency-snapshot') for part in path.relative_to(BASE).parts): continue
        if path.suffix not in ('.py','.cs','.repl','.md','.json','.csv','.log','.resc'): continue
        files[str(path.relative_to(BASE))]=path.read_bytes()
    dependency_paths=[p for p,_ in SOURCE_INPUTS if not p.is_relative_to(BASE)]
    dependency_paths += [BASE.parent/'synthetic-calibration-thermal'/name for name in ['nozzle.repl','bed.repl']]
    for path in dependency_paths:
        files['dependency-snapshot/'+str(path.relative_to(ROOT))]=path.read_bytes()
    manifest=dict(label=label,scope='Source and text evidence only; no firmware, native machine state, integration or default switch',
                  protected_input_sha256=protected_inputs())
    files['checkpoint.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    import hashlib
    files['PACKAGE-SHA256SUMS']=(''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n' for name,data in sorted(files.items()))).encode()
    with tarfile.open(archive,'w:gz') as out:
        for name,data in sorted(files.items()):
            entry=tarfile.TarInfo(str(prefix/name));entry.size=len(data);entry.mode=0o644;entry.mtime=0
            out.addfile(entry,io.BytesIO(data))
    (dest/(archive.name+'.sha256')).write_text(sha(archive)+'  '+archive.name+'\n')
    report=dict(archive=str(archive.relative_to(ROOT)),sha256=sha(archive),bytes=archive.stat().st_size,files=len(files),manifest=manifest)
    (dest/(label+'.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='manifest'},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--label',required=True);checkpoint(p.parse_args().label)
