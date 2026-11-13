"""Opt-in persistence capability wiring. No guest or emulator execution here."""
import fcntl, hashlib, json, os
from pathlib import Path
import instance_disk as d


def bound_tree(root):
    root=d.clean_path(root); h=hashlib.sha256()
    if root.is_file(): return d.digest(root)
    for p in sorted(root.rglob('*')):
        if '__pycache__' in p.parts: continue
        if p.is_symlink(): raise d.InstanceError('profile trees must not contain symlinks')
        if p.is_file():
            h.update(str(p.relative_to(root)).encode()+b'\0'+d.digest(p).encode()+b'\n')
    return h.hexdigest()


def profile_binding(hashes, profile_name, project, runtime, renode, helper, ui_tools=None):
    profile=dict(hashes)
    profile['selected-profile']=hashlib.sha256(profile_name.encode()).hexdigest()
    for name,path in [('project',project),('qemu-runtime',runtime),('renode-runtime',renode.parent),('network-tools',helper.parent),('starter-tools',Path(__file__).parent)]:
        profile[name]=bound_tree(path)
    ui=Path(ui_tools) if ui_tools is not None else Path(__file__).parent.parent/"ui"
    if ui.exists():profile["ui-tools"]=bound_tree(ui)
    return profile


def pass_fds(plan):
    cap=plan.get('persistence')
    if cap is None:return ()
    d.inherited_lease(cap['instance'],cap['lock_fd'],cap['instance_id'],cap['run_id'])
    return d.inherited_pass_fds(cap['lock_fd'])


def observer_preamble(cap):
    if cap is None:return ''
    return ('import sys\nsys.path.insert(0,'+repr(str(Path(__file__).parent))+')\n'
            'from persistence_hooks import pass_fds as persistence_pass_fds\n'
            'persistence_plan='+repr({'persistence':cap})+'\n')


def wrapper_transform(cap):
    if cap is None:return ''
    return ('sys.path.insert(0,'+repr(str(Path(__file__).parent))+')\n'
            'from instance_disk import persistent_qemu_argv\n'
            'cmd=persistent_qemu_argv(cmd,'+','.join(repr(cap[k]) for k in ('instance','lock_fd','instance_id','run_id'))+')\n')


def finish_exclusive(lease, cap):
    """All inherited descriptors must be gone before finalizing, not only PID1.

    An independently opened lock conflicts even with descendants sharing the
    original flock. No automatic recovery or waiting that could mask a writer.
    """
    root=lease.root;source=lease.source
    lease.close()
    fd=os.open(root/'writer.lock',os.O_RDWR|os.O_NOFOLLOW)
    final=d.Lease(root,fd,source)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e:raise d.InstanceBusy('inherited writer still owns lock; leave active state') from e
        m=final.verify()
        if m['instance_id']!=cap['instance_id']:raise d.InstanceError('instance changed before finalize')
        return final.finish(cap['run_id'],writer_exited=True,guest_sync_confirmed=False)
    finally:final.close()
