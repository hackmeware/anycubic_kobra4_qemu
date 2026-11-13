"""Hash-profile controlled app import and new synthetic ext4 images. No guest execution."""
import argparse,hashlib,json,os,shutil,subprocess,tarfile,uuid
from pathlib import Path
from inspect_ext import Ext
HERE=Path(__file__).resolve().parent
def sha(p):
 with open(p,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def build(parts,out,tools):
 out=Path(out).absolute();out.mkdir(mode=0o700);tree=out/'app-tree';tree.mkdir(mode=0o700)
 archive=out/'app-source.tar.gz'
 if sum(Path(x).stat().st_size for x in parts)not in (43286575,71905840):raise ValueError('unsupported app archive size')
 with archive.open('xb') as dest:
  for part in parts:
   with open(part,'rb') as src:shutil.copyfileobj(src,dest)
 if sha(archive) not in ('b568083e56f2e906b329257bbc869fbf026d0c1b990a2780beff2505a598473b','e8845e5d8af475578f3e0f860f9990dc7b581620ad5cc07b50a5730a2e799b66'):raise ValueError('unsupported app archive hash')
 # All source members must exactly match the inspected project archive manifest.
 # No tar extraction API, no link creation until all ordinary files are complete.
 original={r['path']:r for r in json.loads((HERE/'original-app-tree-inventory.json').read_text())}
 target={r['path']:r for r in json.loads((HERE/'app-inventory.json').read_text())['entries']}
 seen=set();links=[]
 with tarfile.open(archive,'r:gz') as tf:
  for m in tf:
   name=m.name.removeprefix('./').rstrip('/')
   if name!='app' and not name.startswith('app/'):continue
   r=original.get(name)
   if r is None or name in seen:raise ValueError('unexpected/duplicate app member')
   seen.add(name);kind='dir' if m.isdir() else 'file' if m.isfile() else 'symlink' if m.issym() else 'special'
   if kind!=r['type'] or m.mode!=r['mode'] or m.size!=r['size']:raise ValueError('app member metadata mismatch')
   rel=name[4:] if name.startswith('app/') else ''
   if name!='app' and not name.startswith('app/'):raise ValueError('app prefix')
   if any(x in ('.','..','') for x in rel.split('/')) and rel:raise ValueError('unsafe app member')
   p=tree/rel
   if kind=='dir':
    if rel:p.mkdir(mode=0o700)
   elif kind=='file':
    with tf.extractfile(m) as src,p.open('xb') as dest:shutil.copyfileobj(src,dest)
    if sha(p)!=r['sha256']:raise ValueError('app payload mismatch')
   elif kind=='symlink':
    if m.linkname!=r['target']:raise ValueError('app symlink mismatch')
    links.append((p,m.linkname))
   else:raise ValueError('unsupported app member')
 if seen!=set(original):raise ValueError('missing app member')
 p=tree/'start.sh';b=p.read_bytes();old=b'wpa_supplicant -Dnl80211 -i wlan0 -c /app/etc/wpa_supplicant.conf -B\nudhcpc -i wlan0 -b &'
 new=b'echo "Offline emulation: wpa_supplicant skipped"\necho "Offline emulation: WLAN DHCP skipped"'
 if b.count(old)!=1:raise ValueError('start script patch precondition')
 p.write_bytes(b.replace(old,new))
 if sha(p)!=target['start.sh']['sha256']:raise ValueError('start script patch result')
 for p,t in links:os.symlink(t,p)
 for rel,r in reversed(list(target.items())):
  if rel=='lost+found':continue
  p=tree/rel
  if r['type']!='symlink':p.chmod(r['mode']&0o7777)
  os.utime(p,(r['mtime'],r['mtime']),follow_symlinks=False)
 tools=Path(tools).resolve();env=dict(os.environ,E2FSPROGS_FAKE_TIME='1793824591')
 report={}
 for name,size in [('app',256*1024*1024),('userdata',16*1024*1024),('data',64*1024*1024)]:
  image=out/(name+'.ext4')
  with image.open('xb') as f:f.truncate(size)
  command=[str(tools/'usr/sbin/mke2fs'),'-q','-F','-t','ext4','-b','1024','-I','256','-U',str(uuid.uuid5(uuid.NAMESPACE_URL,'kobra-rebuilt-v1/'+name)),'-O','^orphan_file,^metadata_csum,^64bit','-E','lazy_itable_init=0,lazy_journal_init=0']
  if name=='app':command+=['-d',str(tree)]
  subprocess.run(command+[str(image)],check=True,env=env,timeout=120)
  actual=Ext(image,0,size).inventory();expected=target if name=='app' else {r['path']:r for r in json.loads((HERE/(name+'-inventory.json')).read_text())['entries']}
  if set(r['path'] for r in actual)!=set(expected):raise ValueError('ext4 paths mismatch')
  commands=[]
  for r in actual:
   e=expected[r['path']]
   for field in ('type','sha256','target'):
    if r.get(field)!=e.get(field):raise ValueError('ext4 content mismatch '+r['path'])
   for field in ('uid','gid','mtime'):
    commands.append('set_inode_field <'+str(r['ino'])+'> '+field+' '+str(e[field]))
  script=out/(name+'-metadata.debugfs');script.write_text('\n'.join(commands)+'\n')
  subprocess.run([str(tools/'usr/sbin/debugfs'),'-w','-f',str(script),str(image)],check=True,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=60)
  after=Ext(image,0,size).inventory()
  for r in after:
   e=expected[r['path']]
   for field in ('type','mode','uid','gid','sha256','target'):
    if r.get(field)!=e.get(field):raise ValueError('ext4 final mismatch '+field+' '+r['path'])
  check=subprocess.run([str(tools/'usr/sbin/e2fsck'),'-fn',str(image)],env=env,capture_output=True,text=True,timeout=60)
  (out/(name+'-fsck.txt')).write_text(check.stdout+check.stderr)
  if check.returncode:raise ValueError('ext4 consistency check failed')
  report[name]={'bytes':size,'sha256':sha(image),'paths':len(after),'content_mode_uid_gid_matches_r9':True,'metadata_identical_to_r9':False,'fsck_readonly_clean':True}
 report['boot_tested']=False;report['profile']='kobra-rebuilt-v1';report['warning']='Synthetic guest images only. Never flash physical hardware.'
 (out/'APP-BUILD.json').write_text(json.dumps(report,indent=2)+'\n');return report
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--app-part',action='append',required=True);p.add_argument('--out',required=True);p.add_argument('--tools-root',required=True);a=p.parse_args();print(json.dumps(build(a.app_part,a.out,a.tools_root),indent=2))
