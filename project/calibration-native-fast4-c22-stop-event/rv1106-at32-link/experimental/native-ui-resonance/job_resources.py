"""Fixed c12 host-only sampled artifact admission. Never opens local IPC endpoints."""
from pathlib import Path
import os,re,stat,shutil
JOB_BYTES=20*1024**3
FREE_FLOOR_BYTES=2*1024**3
MAX_FILES=20000
MAX_IPC=32
PROFILE_ROOT=Path(__file__).resolve().parents[3]
NATIVE_RUN=PROFILE_ROOT/'runs/native-fast4-86400s-c23'
OWNER_ROOT=PROFILE_ROOT.parent/'sensor_run_check/native-fast4-c22-stop-event/run-c23'
EVIDENCE_ROOT=OWNER_ROOT.parent
RUNTIME_TMP=PROFILE_ROOT/'runtime-private/tmp'
MAX_ATOMIC_DISAPPEARANCES=128
ATOMIC_REFRESH_ATTEMPTS=2
NATIVE_FIXED_TEMPS={'native-calibration-attempt.json.tmp':'native-calibration-attempt.json',
    'vnc-endpoint.json.tmp':'vnc-endpoint.json',
    'ui-pid-intent.json.pending':'ui-pid-intent.json',
    'ui-pid-input-outcome.json.pending':'ui-pid-input-outcome.json'}
OWNER_FIXED_TARGETS=frozenset(('owner-lease.json','owner-heartbeat.json','owner-watch-progress.json',
    'owner-watch-final.json',*[f'native-fast4-86400s-c23-{suffix}.json' for suffix in ('latest','post-audit','supervision','outer')]))

def atomic_destination(path):
    """Exact active publisher locations, not a generic temporary-file exemption."""
    if path.parent==NATIVE_RUN:
        if path.name in NATIVE_FIXED_TEMPS:return path.with_name(NATIVE_FIXED_TEMPS[path.name])
        match=re.fullmatch(r'(renode-step|virtual-time|sensor-status|sensor-final)\.json\.[0-9a-f]{32}\.tmp',path.name)
        if match:return path.with_name(match[1]+'.json')
    if path.parent==OWNER_ROOT and path.name.endswith('.tmp') and path.name[:-4] in OWNER_FIXED_TARGETS:
        return path.with_name(path.name[:-4])
    if path.parent==OWNER_ROOT/'owner-checkpoints' and re.fullmatch(r'[1-9][0-9]{0,19}\.json\.tmp',path.name):
        return path.with_name(path.name[:-4])
    return None

def validate_runtime_paths(profile,run,owner):
    """Fail before launch if any exact publisher root missed identity relocation."""
    profile,run,owner=map(Path,(profile,run,owner))
    expected=(profile,run,owner,owner.parent,profile/'runtime-private/tmp')
    actual=(PROFILE_ROOT,NATIVE_RUN,OWNER_ROOT,EVIDENCE_ROOT,RUNTIME_TMP)
    if actual!=expected:
        raise ValueError('Runtime sampler publisher roots differ from actual planned paths')
    expected_owner_targets=frozenset(('owner-lease.json','owner-heartbeat.json','owner-watch-progress.json',
        'owner-watch-final.json',*[run.name+'-'+suffix+'.json' for suffix in ('latest','post-audit','supervision','outer')]))
    if OWNER_FIXED_TARGETS!=expected_owner_targets:
        raise ValueError('Runtime sampler owner publisher names differ from actual run')
    for name in expected_owner_targets:
        if atomic_destination(owner/(name+'.tmp'))!=owner/name:
            raise ValueError('Runtime sampler atomic owner publication is not exactly bound')
    if atomic_destination(owner/'owner-checkpoints/1.json.tmp')!=owner/'owner-checkpoints/1.json':
        raise ValueError('Runtime sampler checkpoint publication is not exactly bound')
    return {name:str(value) for name,value in zip(
        ('profile','native_run','owner_root','evidence_root','runtime_tmp'),actual)}

def artifact_limit(name):
    if name in ('sensor-status.json','sensor-final.json','sensor-final.json.cleanup.json','sensor-profile.json'):return 65536
    if name=='console.bin':return 32*1024**2
    if name in ('bed-thermal-live.csv','nozzle-thermal-live.csv','bed-thermal.csv','nozzle-thermal.csv'):return 32*1024**2
    if '-gpio' in name and name.endswith('-edges.csv'):return 256*1024**2
    if name in ('clock-coordinator.json','z-sensor.csv'):return 512*1024**2
    if name=='z-force-query.csv':return 256*1024**2
    if name=='physical-state.csv':return 64*1024**2
    return 1024**3
LINK_DIRECTORY=re.compile(r'rv-at32-link-[A-Za-z0-9_-]{8}\Z')
CLR_PIPE=re.compile(r'clr-debug-pipe-([1-9][0-9]*)-([1-9][0-9]*)-(in|out)\Z')
FIFO_NAMES=frozenset(('qmp.in','qmp.out','qemu-monitor.in','qemu-monitor.out'))
PTY_NAMES=frozenset(('uart','nozzle-uart'))
VERIFIED_ROOTS={}
VERIFIED_PTY={}
VERIFIED_CLR={} # Accepted endpoint inode and exact already-sampled owned PID/start identity only.

def private_directory(path):
    info=path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:
        raise ValueError('IPC parent is not an owned private directory: '+str(path))
    identity=(info.st_dev,info.st_ino)
    if str(path) in VERIFIED_ROOTS and VERIFIED_ROOTS[str(path)]!=identity:raise ValueError('Owned IPC directory replaced')
    if len(VERIFIED_ROOTS)>=MAX_IPC+2 and str(path) not in VERIFIED_ROOTS:raise ValueError('Owned IPC directory count limit')
    VERIFIED_ROOTS[str(path)]=identity

def local_ipc(path,info,owned_processes=()):
    """Metadata-only exact names, parent chain, type, owner and permissions."""
    try:relative=path.relative_to(RUNTIME_TMP)
    except ValueError:raise ValueError('Nonregular artifact outside private runtime TMP: '+str(path))
    if len(relative.parts)!=2 or not LINK_DIRECTORY.fullmatch(relative.parts[0]):
        raise ValueError('Unexpected IPC artifact location: '+str(path))
    for parent in (RUNTIME_TMP.parent,RUNTIME_TMP,path.parent):private_directory(parent)
    if info.st_uid!=os.getuid() or info.st_nlink!=1:
        raise ValueError('IPC artifact owner/link count mismatch: '+str(path))
    mode=stat.S_IMODE(info.st_mode);name=path.name
    item={'path':str(path),'uid':info.st_uid,'gid':info.st_gid,'mode':oct(mode),'inode':[info.st_dev,info.st_ino],'content_read':False}
    if stat.S_ISFIFO(info.st_mode):
        if CLR_PIPE.fullmatch(name) and mode==0o700:
            match=CLR_PIPE.fullmatch(name);identity=(int(match[1]),int(match[2]));inode=(info.st_dev,info.st_ino)
            if str(path) in VERIFIED_CLR and VERIFIED_CLR[str(path)]!=(identity,inode):raise ValueError('Previously verified CLR endpoint replaced')
            live={(r['pid'],r['starttime_ticks']) for r in owned_processes if type(r.get('pid'))is int and type(r.get('starttime_ticks'))is int}
            if identity not in live and VERIFIED_CLR.get(str(path))!=(identity,inode):raise ValueError('CLR endpoint is not bound to a sampled owned process')
            if len(VERIFIED_CLR)>=MAX_IPC and str(path) not in VERIFIED_CLR:raise ValueError('Verified CLR identity limit')
            VERIFIED_CLR[str(path)]=(identity,inode);item.update(kind='dotnet_debug_fifo',owned_pid=identity[0],owned_starttime_ticks=identity[1],currently_sampled_owned=identity in live)
        elif name in FIFO_NAMES and mode in (0o600,0o644):item['kind']='native_qmp_or_monitor_fifo'
        else:raise ValueError('Unknown FIFO name or mode: '+str(path))
    elif stat.S_ISSOCK(info.st_mode):
        raise ValueError('Unix sockets are not part of this observed fixed runtime route: '+str(path))
    elif stat.S_ISLNK(info.st_mode):
        if name not in PTY_NAMES:raise ValueError('Unexpected runtime symlink: '+str(path))
        target=os.readlink(path)
        if not re.fullmatch(r'/dev/pts/(?:0|[1-9][0-9]*)',target):raise ValueError('Unexpected UART PTY target')
        try:endpoint=os.stat(target,follow_symlinks=False)
        except FileNotFoundError:
            if VERIFIED_PTY.get(str(path))!=((info.st_dev,info.st_ino),target):raise ValueError('Unverified dangling UART PTY link')
            item.update(kind='renode_uart_pty_link',target=target,endpoint_vanished=True)
            return item
        if not stat.S_ISCHR(endpoint.st_mode) or endpoint.st_uid!=os.getuid() or stat.S_IMODE(endpoint.st_mode) not in (0o600,0o620):
            raise ValueError('UART PTY target type/owner/mode mismatch')
        if str(path) in VERIFIED_PTY and VERIFIED_PTY[str(path)]!=((info.st_dev,info.st_ino),target):raise ValueError('Previously verified UART link replaced')
        if len(VERIFIED_PTY)>=MAX_IPC and str(path) not in VERIFIED_PTY:raise ValueError('Verified PTY identity limit')
        VERIFIED_PTY[str(path)]=((info.st_dev,info.st_ino),target)
        item.update(kind='renode_uart_pty_link',target=target,target_inode=[endpoint.st_dev,endpoint.st_ino],target_rdev=endpoint.st_rdev)
    else:raise ValueError('Unexpected nonregular mutable artifact: '+str(path))
    return item

def inventory(roots,owned_processes=()):
    count=regular_count=total=0;largest={};ipc=[];vanished=[];link_roots={}
    # Carry only previously verified exact private link-root identities into this sample.
    # TemporaryDirectory teardown can remove a root before this scan re-registers it.
    link_roots={Path(name):identity for name,identity in VERIFIED_ROOTS.items()
                if Path(name).parent==RUNTIME_TMP and LINK_DIRECTORY.fullmatch(Path(name).name)}
    seen=set();sizes={};atomic_vanished=[]
    def count_entry(path):
        nonlocal count
        if path not in seen:
            seen.add(path);count+=1
            if count>MAX_FILES:raise ValueError('Job artifact/file-count budget exceeded')
    def regular(path,info):
        nonlocal regular_count,total
        target=atomic_destination(path)
        if info.st_size>artifact_limit((target or path).name):raise ValueError('Per-artifact byte budget exceeded: '+str(path))
        # Conservative per-path maxima retain both observed names across a rename.
        # This is bounded sampling, not an atomic directory or byte-completeness proof.
        count_entry(path)
        previous=sizes.get(path)
        if previous is None:regular_count+=1;previous=0
        size=max(previous,info.st_size);sizes[path]=size;total+=size-previous
        if total>JOB_BYTES:raise ValueError('Job artifact/file-count budget exceeded')
        if size>16*1024**2:largest[str(path)]=size
    def refresh_atomic(path,target,fd):
        if len(atomic_vanished)>=MAX_ATOMIC_DISAPPEARANCES:raise ValueError('Atomic disappearance sample limit exceeded')
        # Never read bytes or follow links. An absent mandatory destination is NOT forgiven.
        for attempt in range(1,ATOMIC_REFRESH_ATTEMPTS+1):
            try:current=os.stat(target.name,dir_fd=fd,follow_symlinks=False);break
            except FileNotFoundError:
                if attempt==ATOMIC_REFRESH_ATTEMPTS:raise
        allowed_links=(1,2) if path.suffix=='.pending' else (1,)
        if not stat.S_ISREG(current.st_mode) or current.st_uid!=os.getuid() or current.st_nlink not in allowed_links:
            raise ValueError('Atomic publisher destination type/owner/link mismatch: '+str(target))
        regular(target,current)
        receipt={'path':str(path),'destination':str(target),'enumerated_regular_hint':True,
            'size_at_disappearance_observed':False,'destination_bytes_observed':current.st_size,
            'destination_inode':[current.st_dev,current.st_ino],'refresh_attempts':attempt,
            'content_read':False,'recreated_temporary_observed':False}
        # Fixed temp names can already be reused. Count and validate that extant file too.
        try:recreated=os.stat(path.name,dir_fd=fd,follow_symlinks=False)
        except FileNotFoundError:pass
        else:
            if not stat.S_ISREG(recreated.st_mode) or recreated.st_uid!=os.getuid() or recreated.st_nlink not in allowed_links:
                raise ValueError('Recreated atomic temporary type/owner/link mismatch: '+str(path))
            regular(path,recreated);receipt['recreated_temporary_observed']=True
            receipt['recreated_temporary_bytes']=recreated.st_size
        atomic_vanished.append(receipt)
    def vanished_runtime(path):
        for root,identity in link_roots.items():
            if path==root or root in path.parents:
                for parent in (RUNTIME_TMP.parent,RUNTIME_TMP):private_directory(parent)
                try:
                    current=root.stat(follow_symlinks=False)
                    if (current.st_dev,current.st_ino)!=identity:raise ValueError('Runtime temporary root replaced')
                    private_directory(root)
                except FileNotFoundError:pass
                vanished.append(str(path));return True
        return False
    for root in roots:
        if not root.exists():continue
        initial=root.stat(follow_symlinks=False)
        if not stat.S_ISDIR(initial.st_mode):raise ValueError('Artifact root is not a real directory')
        stack=[(root,(initial.st_dev,initial.st_ino))]
        while stack:
            directory,expected=stack.pop()
            try:
                fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            except FileNotFoundError:
                if vanished_runtime(directory):continue
                raise
            with os.scandir(fd) as entries:
                try:
                    current=os.fstat(fd)
                    if (current.st_dev,current.st_ino)!=expected:raise ValueError('Artifact directory replaced during inventory')
                    for item in entries:
                        path=directory/item.name;count_entry(path)
                        target=atomic_destination(path)
                        # DirEntry uses no-follow directory type metadata when available.
                        # If unavailable/missing, no regular-file proof means no exception.
                        regular_hint=item.is_file(follow_symlinks=False) if target else False
                        try:s=item.stat(follow_symlinks=False)
                        except FileNotFoundError:
                            if target and regular_hint:
                                refresh_atomic(path,target,fd);continue
                            if vanished_runtime(path):continue
                            raise
                        if stat.S_ISDIR(s.st_mode):
                            if directory==RUNTIME_TMP and LINK_DIRECTORY.fullmatch(item.name):
                                try:
                                    for parent in (RUNTIME_TMP.parent,RUNTIME_TMP,path):private_directory(parent)
                                except FileNotFoundError:
                                    if vanished_runtime(path):continue
                                    raise
                                link_roots[path]=(s.st_dev,s.st_ino)
                            stack.append((path,(s.st_dev,s.st_ino)));continue
                        if not stat.S_ISREG(s.st_mode):
                            try:ipc.append(local_ipc(path,s,owned_processes))
                            except FileNotFoundError:
                                if vanished_runtime(path):continue
                                raise
                            if len(ipc)>MAX_IPC:raise ValueError('Local IPC count budget exceeded')
                            continue
                        regular(path,s)
                finally:os.close(fd)
    free=min(shutil.disk_usage(p if p.exists() else p.parent).free for p in roots)
    if free<FREE_FLOOR_BYTES:raise ValueError('Free disk below2GiB safety floor')
    return {'sampled_bytes':total,'regular_file_count':regular_count,'artifact_entry_count':count,
            'atomic_directory_snapshot':False,'sampled_accounting':'maximum observed bytes per path; renames may conservatively count both names',
            'vanished_atomic_entries':atomic_vanished,'vanished_atomic_entry_count':len(atomic_vanished),
            'atomic_disappearance_limit':MAX_ATOMIC_DISAPPEARANCES,'atomic_refresh_attempts_limit':ATOMIC_REFRESH_ATTEMPTS,
            'vanished_runtime_entries':vanished,'vanished_runtime_entry_count':len(vanished),
            'local_ipc_count':len(ipc),'local_ipc_limit':MAX_IPC,'local_ipc_entries':ipc,
            'free_bytes':free,'job_limit_bytes':JOB_BYTES,'free_floor_bytes':FREE_FLOOR_BYTES,
            'largest_artifacts':largest,'kernel_quota_enforced':False}
