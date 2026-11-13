#!/usr/bin/env python3
"""Copy bounded complete-line GPIO prefixes into one admitted checkpoint slot.

The per-run store owns one immutable budget ledger. Failed/interrupted slots are
retained and consumed; there is no overwrite, pruning or retry into a used slot.
The enclosing native owner still owns all non-GPIO disk/process/runtime limits.
"""
import argparse
import hashlib
import json
from pathlib import Path
from gpio_capture import NAMES, bound, checkpoint, read_json, require, validate_plan


def write_metadata(path, data):
    require(len(data)<=65536,'Checkpoint metadata byte bound')
    with path.open('xb') as file:file.write(data)


def capture(run, store, plan, number):
    validate_plan(plan)
    bound(number,1,plan['checkpoint_copies'],'checkpoint slot')
    canonical=(json.dumps(plan,sort_keys=True,separators=(',',':'))+'\n').encode()
    if not store.exists():
        store.mkdir(parents=True,exist_ok=False)
        write_metadata(store/'budget.json',canonical)
    require(not store.is_symlink(),'Symlink checkpoint store')
    require(read_json(store/'budget.json') == plan,'Checkpoint store budget changed')
    allowed={'budget.json'} | {f'checkpoint-{n:04d}' for n in range(1,plan['checkpoint_copies']+1)}
    require(all(p.name in allowed and not p.is_symlink() for p in store.iterdir()),'Unexpected checkpoint store entry')
    target=store/f'checkpoint-{number:04d}'
    target.mkdir(exist_ok=False)
    report={'schema':1,'final':False,'atomic_cross_file_state':False,'all_prefixes_copied':False,
            'budget_sha256':hashlib.sha256(canonical).hexdigest(),'slot':number,'files':{}}
    try:
        for name in NAMES:
            report['files'][name]=checkpoint(run/name,target/name,plan['ports'][name]['maximum_bytes'])
        report['all_prefixes_copied']=True
    except Exception as error:
        report['error']=type(error).__name__+': '+str(error)[:2048]
        raise
    finally:
        write_metadata(target/'SNAPSHOT.json',(json.dumps(report,indent=2)+'\n').encode())
    return report

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path);parser.add_argument('store',type=Path)
    parser.add_argument('plan',type=Path);parser.add_argument('number',type=int)
    args=parser.parse_args()
    print(json.dumps(capture(args.run,args.store,read_json(args.plan),args.number),indent=2))
