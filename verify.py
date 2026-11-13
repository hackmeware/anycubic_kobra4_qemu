#!/usr/bin/env python3
"""Verify distribution integrity only, not boot readiness. Never launches code or opens a network."""
import argparse,hashlib,json,pathlib,sys

def main():
 p=argparse.ArgumentParser(description=__doc__);a=p.parse_args();root=pathlib.Path(__file__).resolve().parent;m=json.loads((root/'FILE-MANIFEST.json').read_text());bad=[]
 for r in m['files']:
  rel=pathlib.PurePosixPath(r['path'])
  if rel.is_absolute() or '..' in rel.parts:raise SystemExit('Unsafe manifest path')
  q=root/rel
  if any((root/pathlib.Path(*rel.parts[:i])).is_symlink() for i in range(1,len(rel.parts)+1)):
   bad.append(r['path']);continue
  if q.is_symlink() or not q.is_file():bad.append(r['path']);continue
  h=hashlib.sha256()
  with q.open('rb') as f:
   for b in iter(lambda:f.read(1048576),b''):h.update(b)
  if q.stat().st_size!=r['bytes'] or h.hexdigest()!=r['sha256']:bad.append(r['path'])
 expected={r['path'] for r in m['files']}|{'FILE-MANIFEST.json'}
 extras=[]
 for q in root.rglob('*'):
  rel=q.relative_to(root)
  if any(v in ('.git','__pycache__') for v in rel.parts):continue
  if q.is_symlink() or (q.is_file() and rel.as_posix() not in expected):extras.append(rel.as_posix())
 bad.extend(extras)
 print(json.dumps({'file_integrity':'pass' if not bad else 'fail','files_checked':len(m['files']),'mismatches':bad,'distribution_scope':'Private firmware-free source and restored host runtimes; local .git and __pycache__ excluded','readiness':'Integrity only; see README and evidence for separately tested boot scope'},indent=2))
 return 1 if bad else 0
if __name__=='__main__':sys.exit(main())
