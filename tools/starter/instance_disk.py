"""Linux private persistent disks. No firmware; no VM/MCU state serialization.

Trusted same-user local launcher, not a hostile same-UID security boundary.
Every writer must inherit Lease.fd. Never call LOCK_UN on an inherited lease.
"""
import fcntl, hashlib, json, os, re, stat, time, uuid
from pathlib import Path

class InstanceError(RuntimeError): pass
class InstanceBusy(InstanceError): pass
class RecoveryRequired(InstanceError): pass

def clean_path(value):
    p=Path(value)
    if '..' in p.parts: raise InstanceError('parent traversal forbidden')
    p=p.absolute()
    if any(x.is_symlink() for x in (p,*p.parents)): raise InstanceError('symlink forbidden')
    if any(c in str(p) for c in ',\n\r\0'): raise InstanceError('unsafe QEMU path')
    return p

def private_dir(p):
    s=p.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077: raise InstanceError('directory must be private and owned')

def regular(p,private=False):
    s=p.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1: raise InstanceError('single-link regular file required')
    if private and (s.st_uid!=os.getuid() or s.st_mode&0o077): raise InstanceError('private owned file required')
    return s

def digest(p):
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode): raise InstanceError('regular file required')
        return hashlib.file_digest(f,'sha256').hexdigest()

def profile_checked(profile):
    if not isinstance(profile,dict) or not profile or not all(isinstance(k,str) and re.fullmatch(r'[\w.-]{1,100}',k,flags=re.ASCII) and isinstance(v,str) and re.fullmatch('[0-9a-f]{64}',v) for k,v in profile.items()): raise InstanceError('explicit named SHA256 profile required')
    return dict(sorted(profile.items()))

def sync_dir(p):
    fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def copy_new(source,target,expected):
    regular(source)
    with os.fdopen(os.open(source,os.O_RDONLY|os.O_NOFOLLOW),'rb') as src:
        with os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as dst:
            before=os.fstat(src.fileno());h=hashlib.sha256()
            while b:=src.read(1024*1024):dst.write(b);h.update(b)
            dst.flush();os.fsync(dst.fileno());after=os.fstat(src.fileno())
    if h.hexdigest()!=expected or (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns) or digest(source)!=expected: raise InstanceError('source changed; partial copy retained, not usable')
    sync_dir(target.parent)

def read_state(root):
    p=root/'state.json';s=regular(p,True)
    if s.st_size>1024*1024:raise InstanceError('manifest too large')
    with os.fdopen(os.open(p,os.O_RDONLY|os.O_NOFOLLOW)) as f:m=json.load(f)
    if not isinstance(m,dict) or m.get('schema')!=1 or not re.fullmatch('[0-9a-f]{32}',str(m.get('instance_id',''))):raise InstanceError('invalid manifest')
    if m.get('phase') not in ('active','quiescent') or type(m.get('revision')) is not int or m['revision']<0 or type(m.get('source_size')) is not int or m['source_size']<=0:raise InstanceError('invalid state fields')
    for k in ('source_sha256','disk_sha256'):
        if not re.fullmatch('[0-9a-f]{64}',str(m.get(k,''))):raise InstanceError('invalid state hash')
    profile_checked(m.get('profile_sha256'))
    if not isinstance(m.get('disk_identity'),list) or len(m['disk_identity'])!=2 or not all(type(x) is int for x in m['disk_identity']):raise InstanceError('invalid disk identity')
    if type(m.get('guest_sync_confirmed')) is not bool:raise InstanceError('invalid sync status')
    return m

def save_state(root,m):
    m=dict(m);m['revision']=m.get('revision',-1)+1;m['updated_unix_ns']=time.time_ns()
    data=(json.dumps(m,indent=2,sort_keys=True)+'\n').encode()
    if len(data)>1024*1024:raise InstanceError('manifest too large')
    history=root/'history'
    if not history.exists():history.mkdir(mode=0o700)
    private_dir(history)
    def write(p):
        with os.fdopen(os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    write(history/(f"{m['revision']:08d}-"+uuid.uuid4().hex+'.json'));sync_dir(history)
    pending=root/('state-'+uuid.uuid4().hex+'.pending');write(pending)
    if (root/'state.json').exists() or (root/'state.json').is_symlink():regular(root/'state.json',True)
    os.replace(pending,root/'state.json');sync_dir(root)
    return m

class Lease:
    def __init__(self,root,fd,source):self.root=root;self.fd=fd;self.source=source;self.recovery_backup=None
    @property
    def disk(self):return self.root/'disk.raw'
    def close(self):
        if self.fd is not None:os.close(self.fd);self.fd=None
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def verify(self):
        if self.fd is None:raise InstanceError('closed lease')
        clean_path(self.root);private_dir(self.root)
        s=regular(self.root/'writer.lock',True);f=os.fstat(self.fd)
        if (s.st_dev,s.st_ino)!=(f.st_dev,f.st_ino):raise InstanceError('lock descriptor mismatch')
        try:fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e:raise InstanceBusy('active writer') from e
        m=read_state(self.root);s=regular(self.disk,True)
        if [s.st_dev,s.st_ino]!=m['disk_identity'] or s.st_size!=m['source_size']:raise InstanceError('disk identity/size changed')
        return m
    def begin(self,run_id):
        if not isinstance(run_id,str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',run_id):raise InstanceError('invalid run ID')
        m=self.verify()
        if m['phase']!='quiescent' or digest(self.disk)!=m['disk_sha256']:raise RecoveryRequired('state requires recovery')
        m.update(phase='active',run_id=run_id,guest_sync_confirmed=False,guest_sync_evidence=None,writer_exited=False)
        save_state(self.root,m)
        return dict(instance=str(self.root),instance_id=m['instance_id'],disk=str(self.disk),run_id=run_id,lock_fd=self.fd)
    def finish(self,run_id,*,writer_exited,guest_sync_confirmed=False,guest_sync_evidence=None):
        if writer_exited is not True:raise InstanceError('writer exit must be observed before finalize')
        if guest_sync_confirmed and (not isinstance(guest_sync_evidence,str) or not guest_sync_evidence):raise InstanceError('guest sync needs observed evidence')
        m=self.verify()
        if m['phase']!='active' or m.get('run_id')!=run_id:raise InstanceError('wrong active run')
        if self.source is None or digest(self.source)!=m['source_sha256']:raise InstanceError('immutable source unavailable/changed')
        fd=os.open(self.disk,os.O_RDONLY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
        m.update(phase='quiescent',writer_exited=True,guest_sync_confirmed=bool(guest_sync_confirmed),guest_sync_evidence=guest_sync_evidence,disk_sha256=digest(self.disk))
        return save_state(self.root,m)

def open_instance(instance,source,profile,*,recover=False):
    root=clean_path(instance);source=clean_path(source);profile=profile_checked(profile)
    regular(source);source_hash=digest(source);size=source.stat().st_size
    if not size:raise InstanceError('empty source')
    new=not root.exists()
    if new:root.mkdir(mode=0o700)
    private_dir(root)
    fd=os.open(root/'writer.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);lease=Lease(root,fd,source)
    try:
        regular(root/'writer.lock',True)
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e:raise InstanceBusy('another writer holds this instance') from e
        os.set_inheritable(fd,True)
        if new:
            copy_new(source,lease.disk,source_hash);s=regular(lease.disk,True)
            save_state(root,dict(schema=1,instance_id=uuid.uuid4().hex,profile_sha256=profile,source_sha256=source_hash,source_size=size,disk_sha256=source_hash,disk_identity=[s.st_dev,s.st_ino],phase='quiescent',writer_exited=True,guest_sync_confirmed=True,guest_sync_evidence='initial source clone; not filesystem-cleanliness proof',revision=-1))
        m=lease.verify()
        if (m['source_sha256'],m['source_size'],m['profile_sha256'])!=(source_hash,size,profile):raise InstanceError('different source/profile binding')
        current=digest(lease.disk);unclean=m['phase']!='quiescent' or current!=m['disk_sha256']
        if unclean and not recover:raise RecoveryRequired('explicit recovery required; original state will be backed up, never reset')
        if unclean or not m['guest_sync_confirmed']:
            backup_dir=root/'recovery'
            if not backup_dir.exists():backup_dir.mkdir(mode=0o700)
            private_dir(backup_dir);backup=backup_dir/('disk-before-resume-'+uuid.uuid4().hex+'.raw')
            copy_new(lease.disk,backup,current);lease.recovery_backup=str(backup)
            m.update(phase='quiescent',disk_sha256=current,recovery_backup=backup.name,recovery_reason='unclean_or_external_change' if unclean else 'guest_sync_unconfirmed',guest_sync_confirmed=False)
            save_state(root,m)
        return lease
    except BaseException:lease.close();raise

def inherited_lease(instance,fd,instance_id,run_id):
    if type(fd) is not int or fd<3:raise InstanceError('inherited lock FD required')
    lease=Lease(clean_path(instance),fd,None);m=lease.verify()
    if m['instance_id']!=instance_id or m['phase']!='active' or m.get('run_id')!=run_id:raise InstanceError('wrong inherited run')
    os.set_inheritable(fd,True)
    return lease

def persistent_qemu_argv(argv,instance,fd,instance_id,run_id):
    lease=inherited_lease(instance,fd,instance_id,run_id);args=list(argv)
    if args.count('-drive')!=1:raise InstanceError('one owned drive required')
    i=args.index('-drive')+1;expected=f'if=sd,index=0,file={lease.disk},format=raw,snapshot=on'
    if i>=len(args) or args[i]!=expected:raise InstanceError('cannot disable snapshot on another drive/options')
    args[i]=expected[:-2]+'off'
    return args

def inherited_pass_fds(fd,existing=()):
    if type(fd) is not int or fd<3:raise InstanceError('invalid inherited FD')
    os.fstat(fd);return tuple(sorted(set(existing)|{fd}))
