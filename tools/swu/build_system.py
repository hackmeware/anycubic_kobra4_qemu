"""Reconstruct the hash-bound R9 diagnostic system, never execute guest files."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path
from inspect_squash import Squash
HERE=Path(__file__).resolve().parent
ORIGINAL='f4c0032b5d201ca43ce5b220e7a1fb90a4ffcc8120bb67839486b970e75ffcc4'
def sha(p):
 with open(p,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def build(source,out,mksquashfs):
 source=Path(source).resolve();out=Path(out).absolute()
 if sha(source)!=ORIGINAL:raise ValueError('unsupported system image hash')
 out.mkdir(mode=0o700);tree=out/'tree';tree.mkdir(mode=0o700)
 sq=Squash(source);rows=sq.inventory()
 expected=json.loads((HERE/'system-original-inventory.json').read_text())
 keys=('path','type','mode','size','sha256','target')
 def normalized(rs):return [{k:r[k] for k in keys if k in r and not(k=='size' and r['type']=='dir')} for r in rs]
 if normalized(rows)!=normalized(expected):raise ValueError('original system manifest mismatch')
 # The exact hash-bound image has no devices, hard links, sockets or FIFOs.
 # Create all directories/files first. Guest absolute/relative symlinks only last.
 for r in rows:
  p=tree/r['path']
  if r['type']=='dir':
   if r['path']:p.mkdir(mode=0o700)
  elif r['type']=='file':
   with p.open('xb') as f:
    for chunk in sq.chunks(r):f.write(chunk)
  elif r['type']!='symlink':raise ValueError('unsupported inode')
 for name,ref in [('emulation-init.sh','original-diagnostic-emulation-init.sh.txt'),('etc/init.d/S80_wifi_connect','diagnostic-S80_wifi_connect.txt')]:
  p=tree/name;p.write_bytes((HERE/ref).read_bytes());p.chmod(0o755)
 expected_new=json.loads((HERE/'system-r9-inventory.json').read_text())
 for r in rows:
  if r['type']=='symlink':os.symlink(r['target'],tree/r['path'])
 for r in reversed(expected_new):
  p=tree/r['path']
  if r['type']!='symlink':p.chmod(r['mode'])
  os.utime(p,(r['mtime'],r['mtime']),follow_symlinks=False)
 output=out/'system-diagnostic.img'
 subprocess.run([str(mksquashfs),str(tree),str(output),'-noappend','-comp','xz','-no-xattrs','-all-root','-mkfs-time','1793824590','-processors','1','-no-progress'],check=True,timeout=120)
 actual=Squash(output).inventory()
 if normalized(actual)!=normalized(expected_new):raise ValueError('rebuilt diagnostic content mismatch')
 report={'profile':'kobra-r9-diagnostic-rebuilt-v1','input_sha256':ORIGINAL,'output_sha256':sha(output),'output_bytes':output.stat().st_size,'regular_file_bytes_types_modes_match_r9':True,'ownership':'all root','xattrs':'removed intentionally','boot_tested':False,'changes':['emulation-init.sh diagnostic PID1 (does not start vendor daemons)','S80_wifi_connect skips hardware SDIO init'],'warning':'Synthetic diagnostic filesystem only; not for physical flashing.'}
 (out/'SYSTEM-BUILD.json').write_text(json.dumps(report,indent=2)+'\n');return report
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--out',required=True);p.add_argument('--mksquashfs',required=True);a=p.parse_args();print(json.dumps(build(a.source,a.out,a.mksquashfs),indent=2))
