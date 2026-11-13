#!/usr/bin/env python3
"""Create a fresh diagnostic run plan; --execute explicitly starts two MCUs and Linux.
Not a full calibration runner. Private inputs and matching external runtimes required.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import signal
import shutil
from prepare_diagnostic import prepare, sha
import instance_disk
import persistence_hooks
import atexit, uuid
from run_limits import RunLimits,DEFAULT

def write_process_observer(path, persistence=None, r9=False, limits=DEFAULT, command_journal=False):
    # Observe only subprocesses created by this new run; historical code untouched.
    text="""import json,os,pathlib,resource,runpy,signal,subprocess,sys,time
journal=pathlib.Path(__file__).with_name('PROCESS-EXITS.jsonl')
Original=subprocess.Popen
class ObservedPopen(Original):
    def __init__(self,*a,**kw):
        self._recorded=False;self._began=time.monotonic()
        super().__init__(*a,**kw)
    def _record(self,code):
        if code is None or self._recorded:return
        self._recorded=True
        usage=resource.getrusage(resource.RUSAGE_CHILDREN)
        argv=self.args if isinstance(self.args,(list,tuple)) else [self.args]
        row={'pid':self.pid,'argv':[str(v) for v in argv],'returncode':code,
             'signal':(-code if code<0 else None),'elapsed_host_seconds':time.monotonic()-self._began,
             'cumulative_children_user_cpu_seconds':usage.ru_utime,
             'cumulative_children_system_cpu_seconds':usage.ru_stime}
        with journal.open('a') as f:f.write(json.dumps(row)+'\\n');f.flush()
    def poll(self):
        code=super().poll();self._record(code);return code
    def wait(self,*a,**kw):
        code=super().wait(*a,**kw);self._record(code);return code
subprocess.Popen=ObservedPopen
script=pathlib.Path(sys.argv[1]).resolve();sys.argv=sys.argv[1:]
sys.path.insert(0,str(script.parent));runpy.run_path(str(script),run_name='__main__')
"""
    if persistence is not None:
        text=persistence_hooks.observer_preamble(persistence)+text
        text=text.replace('        super().__init__(*a,**kw)',
            "        kw['pass_fds']=tuple(sorted(set(kw.get('pass_fds',())) | set(persistence_pass_fds(persistence_plan))))\n        super().__init__(*a,**kw)")
    if r9:
        text=text.replace("sys.path.insert(0,str(script.parent));runpy.run_path(str(script),run_name='__main__')", "sys.path.insert(0,str(script.parent))\nsys.path.insert(0,"+repr(str(Path(__file__).parent))+ ")\nimport r9_clock_guard\nfrom run_limits import RunLimits\nr9_clock_guard.install(pathlib.Path(__file__).parent,RunLimits("+str(limits.stop_seconds)+"))\nrunpy.run_path(str(script),run_name='__main__')")
    if command_journal:
        text=text.replace("runpy.run_path(str(script),run_name='__main__')", "import monitor_command_journal\nmonitor_command_journal.install(pathlib.Path(__file__).parent)\nrunpy.run_path(str(script),run_name='__main__')")
    path.write_text(text)


def owned_tcp_listeners(proc=Path('/proc')):
    """Read-only socket inventory; callers use a verified PRIVATE PID namespace."""
    import socket,struct
    owners={}
    for entry in proc.iterdir():
        if not entry.name.isdigit():continue
        try:
            program=(entry/'cmdline').read_bytes().split(b'\0',1)[0].decode(errors='replace')
            for fd in (entry/'fd').iterdir():
                try:target=os.readlink(fd)
                except OSError:continue
                if target.startswith('socket:[') and target.endswith(']'):
                    owners.setdefault(target[8:-1],set()).add((int(entry.name),program))
        except OSError:continue
    rows=[]
    for filename,family in [('tcp',socket.AF_INET),('tcp6',socket.AF_INET6)]:
        try:lines=(proc/'net'/filename).read_text().splitlines()[1:]
        except OSError:continue
        for line in lines:
            fields=line.split()
            if len(fields)<10 or fields[3]!='0A' or fields[9] not in owners:continue
            addr,port=fields[1].split(':')
            raw=struct.pack('=I',int(addr,16)) if family==socket.AF_INET else struct.pack('=4I',*[int(addr[i:i+8],16) for i in range(0,32,8)])
            address=socket.inet_ntop(family,raw)
            for pid,program in sorted(owners[fields[9]]):
                rows.append({'pid':pid,'program':program,'address':address,'port':int(port,16),
                             'family':'ipv4' if family==socket.AF_INET else 'ipv6','socket_inode':fields[9]})
    return rows


def network_commands(helper,mode):
    generator=helper.parent/'generate_guest_commands.py'
    spec=importlib.util.spec_from_file_location('kobra_guest_command_generator',generator)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.generate((helper.parent/'udhcpc-hook.sh').read_text(),mode=mode)


def namespace_supervisor(out):
    """PID1 in a NEW private namespace; never inspect or signal host processes."""
    import resource
    out=Path(out).resolve(strict=True)
    if os.getpid()!=1: raise RuntimeError('Private PID namespace required')
    plan=json.loads((out/'RUN-PLAN.json').read_text())
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    cpu_allowance=plan.get('cpu_allowance_seconds',4*plan['hard_limit_seconds']+5)
    resource.setrlimit(resource.RLIMIT_CPU,(cpu_allowance,cpu_allowance+1))
    os.nice(10)
    child=None;ui_probe=None;reason=None;peak=0;stop_started=None;started=time.monotonic();last_sockets=0;seen_listeners={};last_ui_check=0;ui_stop=None
    def stop(*_):
        nonlocal reason
        reason=reason or 'supervisor interrupted'
        (out/'stop-request').touch(exist_ok=True)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        child=subprocess.Popen(plan['argv'],pass_fds=persistence_hooks.pass_fds(plan))
        if plan.get('ui'):
            ui_probe=subprocess.Popen([sys.executable,'-B',str(Path(__file__).with_name('ui_integration.py')),str(out)])
        while child.poll() is None:
            rss=0
            for entry in Path('/proc').iterdir():
                if not entry.name.isdigit():continue
                try:
                    for line in (entry/'status').read_text().splitlines():
                        if line.startswith('VmRSS:'):rss+=int(line.split()[1])*1024
                except (OSError,ValueError):pass
            peak=max(peak,rss);elapsed=time.monotonic()-started
            if (plan.get('network','off')!='off' or plan.get('ui')) and elapsed-last_sockets>=1:
                import ipaddress
                listeners=owned_tcp_listeners();last_sockets=elapsed
                for row in listeners:
                    key=(row['pid'],row['socket_inode'],row['address'],row['port'])
                    if key not in seen_listeners:seen_listeners[key]=dict(row,first_seen_host_seconds=elapsed)
                    if not ipaddress.ip_address(row['address']).is_loopback:
                        reason=reason or 'unexpected non-loopback owned listener'
                        (out/'stop-request').touch(exist_ok=True)
                report={'pid_namespace_only':True,'current':listeners,'observed':list(seen_listeners.values()),
                        'requested_forward_ports':plan.get('forward_ports',[]),'elapsed_host_seconds':elapsed}
                pending=out/'OWNED-LISTENERS.json.pending';pending.write_text(json.dumps(report,indent=2)+'\n')
                pending.replace(out/'OWNED-LISTENERS.json')
            if plan.get('stop_when_ui_observed') and ui_stop is None and elapsed-last_ui_check>=2:
                from ui_integration import evidence,should_stop
                last_ui_check=elapsed;observed=evidence(out,plan,live=True)
                if should_stop(observed):
                    ui_stop={'trigger':'native UI channel plus nonuniform guest frame and owned loopback viewer observed','host_seconds':elapsed,'observation':observed,'full_duration_pass':False,'calibration_proven':False}
                    (out/'UI-STOP-TRIGGER.json').write_text(json.dumps(ui_stop,indent=2)+'\n')
                    (out/'stop-request').touch(exist_ok=True)
            if ui_stop is not None and elapsed-ui_stop['host_seconds']>20:
                reason=reason or 'UI observation stop cleanup deadline'
                break
            if rss>plan['max_namespace_rss_bytes'] or elapsed>plan['cooperative_limit_seconds']:
                reason=reason or ('memory limit' if rss>plan['max_namespace_rss_bytes'] else 'time limit')
                (out/'stop-request').touch(exist_ok=True)
            if reason is not None and stop_started is None:stop_started=time.monotonic()
            if elapsed>plan['hard_limit_seconds'] or (stop_started is not None and time.monotonic()-stop_started>10):break
            time.sleep(.1)
    finally:
        if ui_probe is not None and ui_probe.poll() is None:
            ui_probe.terminate()
            try:ui_probe.wait(timeout=2)
            except subprocess.TimeoutExpired:ui_probe.kill();ui_probe.wait(timeout=2)
        if child is not None and child.poll() is None:
            child.terminate()
            try:child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                try:child.wait(timeout=2)
                except subprocess.TimeoutExpired:reason='owned child cleanup not confirmed'
        usage=resource.getrusage(resource.RUSAGE_CHILDREN)
        result={'returncode':None if child is None else child.poll(),'stop_reason':reason,'ui_observation_stop':ui_stop,
                'cpu_allowance_seconds_per_process':cpu_allowance,
                'children_user_cpu_seconds':usage.ru_utime,'children_system_cpu_seconds':usage.ru_stime,
                'host_seconds':time.monotonic()-started,'peak_namespace_rss_bytes':peak,
                'pid_namespace':os.readlink('/proc/self/ns/pid'),
                'network_namespace':os.readlink('/proc/self/ns/net'),
                'owned_child_exited':child is not None and child.poll() is not None,
                'ui_probe_returncode':None if ui_probe is None else ui_probe.poll(),
                'ui_probe_exited':None if ui_probe is None else ui_probe.poll() is not None}
        (out/'SUPERVISOR.json').write_text(json.dumps(result,indent=2)+'\n')
    return 0 if child is not None and child.returncode==0 and reason is None else 1


def guest_userspace_ready(console):
    marker=b'RV1106_OFFLINE_USERSPACE_READY'
    try:
        with Path(console).open('rb') as stream:
            tail=b''
            for chunk in iter(lambda:stream.read(65536),b''):
                data=tail+chunk
                if marker in data:return True
                tail=data[-len(marker):]
    except FileNotFoundError:return False
    return False


def diagnostic_exit_code(result):
    if (result['subprocess_returncode']!=0 or not result['input_unchanged']
        or result['outer_stop_reason'] is not None or not result['supervisor_evidence_present']):return 1
    if result.get('persistence_finalized') is False:return 7
    if result.get('r9_sensor_contract_verified') is False:return 8
    if not result['guest_userspace_ready']:return 3
    if result.get('network_configuration_ready') is False or result.get('loopback_forwards_verified') is False:return 4
    if result.get('ui',{}).get('fault_observed'):return 6
    if result.get('ui') and not all(result['ui'].get(k) for k in ('ui_connection_ready','printer_ready','frame_verified','loopback_viewer_verified')):return 5
    return 0


def verify_r9_sensor_contract(out,plan):
    try:
        limits=RunLimits.from_record(plan['r9_run_limits'])
        sp=importlib.util.spec_from_file_location('r9_sensor_status',Path(plan['r9_sensor_validator']))
        sm=importlib.util.module_from_spec(sp);sp.loader.exec_module(sm)
        sensor=json.loads((Path(out)/'logs/sensor-final.json').read_text())
        step=json.loads((Path(out)/'logs/renode-step.json').read_text())
        if (step.get('source')!='renode-shared-mcu-step' or step.get('paused') is not True or step.get('enabled') is not True or step.get('time_went_backwards') is not False or type(step.get('virtual_time_ns')) is not int or step['virtual_time_ns']!=sensor.get('virtual_time_ns') or step['virtual_time_ns']>=limits.stop_ns):
            raise ValueError('R9 sensor final must match paused shared boundary below limit')
        ready=sm.check(sensor,step['virtual_time_ns'],limits)
        return {'r9_sensor_contract_verified':True,'r9_sensor_ready':ready,'r9_run_limits':limits.record()}
    except (OSError,ValueError,KeyError,IndexError) as e:
        return {'r9_sensor_contract_verified':False,'r9_sensor_contract_error':str(e)}


def execute_bounded(out,plan,inputs,hashes,lease=None):
    unshare=shutil.which('unshare')
    if not unshare:raise RuntimeError('Linux unshare required; no uncontained fallback')
    cmd=[unshare,'--user','--map-root-user','--pid','--fork','--kill-child=SIGKILL','--mount-proc']
    if plan['network']=='off' and not plan.get('ui'):cmd+=['--net']
    cmd += [sys.executable,'-B',str(Path(__file__).resolve()),'--namespace-supervisor',str(out)]
    (out/'SUPERVISOR-COMMAND.json').write_text(json.dumps(cmd,indent=2)+'\n')
    env={'PATH':'/usr/bin:/bin','HOME':str(out/'home'),'XDG_CONFIG_HOME':str(out/'home/.config'),
         'XDG_CACHE_HOME':str(out/'home/cache'),'DOTNET_CLI_HOME':str(out/'home'),
         'TMPDIR':str(out/'tmp'),'PYTHONDONTWRITEBYTECODE':'1','LANG':'C.UTF-8'}
    child=None;reason=None;started=time.monotonic()
    try:
        with (out/'launcher.log').open('wb') as log:
            child=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,pass_fds=persistence_hooks.pass_fds(plan))
            announced=False
            while child.poll() is None:
                if plan.get('ui') and not announced and (out/'logs/vnc-endpoint.json').is_file():
                    ep=json.loads((out/'logs/vnc-endpoint.json').read_text())
                    print('Local VNC: '+str(ep['host'])+':'+str(ep['port'])+' (no authentication; local processes can view/control).',flush=True);announced=True
                if time.monotonic()-started>plan['hard_limit_seconds']+15:
                    reason='outer watchdog';break
                time.sleep(.5)
    finally:
        # Only this Popen is signalled. unshare kills its own PID1 on wrapper exit;
        # Linux then terminates any remaining children of that private namespace.
        if child is not None and child.poll() is None:
            (out/'stop-request').touch(exist_ok=True)
            child.terminate()
            try:child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill();child.wait(timeout=3)
        unchanged=all(sha(inputs/n)==h for n,h in hashes.items())
        result={'returncode':None if child is None else child.returncode,'input_unchanged':unchanged,
                'outer_stop_reason':reason,'host_seconds':time.monotonic()-started,
                'namespace_wrapper_exited':child is not None and child.poll() is not None,
                'supervisor_evidence_present':(out/'SUPERVISOR.json').is_file(),
                'calibration_proven':False,
                'subprocess_returncode':None if child is None else child.returncode,
                'guest_userspace_ready':guest_userspace_ready(out/'logs/console.bin')}
        result['network_configuration_ready']=None
        result['loopback_forwards_verified']=None
        if plan['network']!='off':
            try:console=(out/'logs/console.bin').read_text(errors='replace')
            except FileNotFoundError:console=''
            result['network_configuration_ready']='K4_NET_CONFIG_READY' in [line.strip() for line in console.splitlines()]
            requested=plan.get('forward_ports',[])
            if requested:
                try:listeners=json.loads((out/'OWNED-LISTENERS.json').read_text())['observed']
                except (FileNotFoundError,ValueError,KeyError):listeners=[]
                result['loopback_forwards_verified']=all(any(row['address']=='127.0.0.1' and row['port']==port for row in listeners) for port in requested)
        if plan.get('ui'):
            from ui_integration import evidence
            result['ui']=evidence(out,plan)
        result['early_ui_observation_stop']=(out/'UI-STOP-TRIGGER.json').is_file()
        result['full_requested_observation_completed']=False if result['early_ui_observation_stop'] or (out/'logs/observation-stop.json').exists() or result['subprocess_returncode']!=0 else None
        if result['full_requested_observation_completed'] is None and (out/'logs/clock-coordinator.json').is_file():
            try:
                clock=json.loads((out/'logs/clock-coordinator.json').read_text())
                result['full_requested_observation_completed']=clock.get('error') is None and clock['wall_seconds']>=plan['requested_observation_seconds']
            except (KeyError,ValueError):pass
        if plan.get('r9_run_limits'):result.update(verify_r9_sensor_contract(out,plan))
        result['persistence_finalized']=None
        if lease is not None:
            try:
                state=persistence_hooks.finish_exclusive(lease,plan['persistence'])
                result['persistence_finalized']=True
                result['persistent_disk_sha256']=state['disk_sha256']
                result['guest_sync_confirmed']=False
            except (OSError,RuntimeError,ValueError) as e:
                result['persistence_finalized']=False
                result['persistence_error']=str(e)
        result['starter_returncode']=diagnostic_exit_code(result)
        (out/'EXIT.json').write_text(json.dumps(result,indent=2)+'\n')
    return result['starter_returncode']

def profile_settings(name,inputs,out):
    if name=='two-mcu-independent':
        return {'argv':[],'startup_seconds':60,'motor':False,'quantum_seconds':None}
    if name=='r9-calibration':
        return {'argv':['--motor-image',str(inputs/'motor.bin')], 'startup_seconds':300,'motor':True,'quantum_seconds':0.000001}
    if name!='three-mcu-scalar':raise ValueError('Unknown diagnostic profile')
    return {'argv':['--motor-image',str(inputs/'motor.bin'),'--shared-mcus',
                    '--motor-setup-commands',str(out/'motor-setup.commands'),
                    '--clock-coupled','--clock-source','qom-deadline','--clock-lockstep',
                    '--qemu-icount-shift','0','--renode-bootstrap','legacy'],
            'startup_seconds':300,'motor':True,'quantum_seconds':0.000001}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('project','inputs','qemu-runtime','renode','network-helper','output'):
        p.add_argument('--'+name,required=True)
    p.add_argument('--host-runtime-profile',choices=['original','no-history-autosave'],default='original',help='Explicit host-only AntShell autosave optimization; command audit remains append-only')
    p.add_argument('--network',choices=['off','isolated','internet'],default='off')
    p.add_argument('--http-port',type=int);p.add_argument('--mqtt-port',type=int)
    p.add_argument('--seconds',type=int,default=30)
    p.add_argument('--synthetic-thermal-rate',type=int,choices=[1,4],default=None,help='R9 only: hypothetical heating AND cooling rate, default1; NOT hardware PID transferable')
    p.add_argument('--virtual-limit-seconds',type=int,default=None,help='R9 only: absolute shared-time stop (default719, maximum86400), not wall time')
    p.add_argument('--profile',choices=['two-mcu-independent','three-mcu-scalar','r9-calibration'],default='two-mcu-independent',help='Three-MCU uses existing shared addon, scalar QOM deadline lockstep; not full calibration')
    p.add_argument('--ui',action='store_true',help='Optional offline native UI with localhost VNC; no automatic touch. Shares host network namespace but guest NIC remains disabled.')
    p.add_argument('--stop-when-ui-observed',action='store_true',help='Test-only early stop on native UI channel, guest frame and owned loopback evidence; does not suppress faults or prove full duration')
    p.add_argument('--ui-tools',help='Reviewed source-only UI helper directory (default sibling ../ui)')
    p.add_argument('--execute',action='store_true')
    p.add_argument('--instance',help='Private persistent instance directory; requires --execute')
    p.add_argument('--recover-instance',action='store_true',help='Explicitly preserve and resume an unclean instance, never reset it')
    a=p.parse_args()
    if a.host_runtime_profile!="original" and a.profile!="r9-calibration":p.error("host runtime candidate requires explicit R9 profile")
    if a.synthetic_thermal_rate is not None and a.profile!="r9-calibration":p.error("--synthetic-thermal-rate requires r9-calibration")
    if a.virtual_limit_seconds is not None and a.profile!="r9-calibration":p.error("--virtual-limit-seconds requires r9-calibration")
    try:limits=RunLimits(719 if a.virtual_limit_seconds is None else a.virtual_limit_seconds)
    except ValueError as e:p.error(str(e))
    if a.profile=="r9-calibration" and limits.stop_seconds<=1:p.error("R9 virtual limit must exceed the 1s bootstrap")
    if a.instance and not a.execute:p.error("--instance requires --execute; no disk is created for dry-run")
    if a.recover_instance and not a.instance:p.error("--recover-instance requires --instance")
    if a.stop_when_ui_observed and not a.ui:p.error('--stop-when-ui-observed requires --ui')
    if a.ui and a.profile not in ('three-mcu-scalar','r9-calibration'):p.error('UI currently requires explicit --profile three-mcu-scalar; default headless profile is unchanged')
    if a.ui and (a.network!='off' or a.http_port is not None or a.mqtt_port is not None):p.error('UI requires guest networking off and no forwards')
    if not 1<=a.seconds<=86400:p.error('diagnostic observation must be 1..86400 seconds; only bounded 300-second profiles have been tested')
    project=Path(a.project).resolve(strict=True);inputs=Path(a.inputs).resolve(strict=True)
    runtime=Path(a.qemu_runtime).resolve(strict=True);renode=Path(a.renode).resolve(strict=True)
    helper=Path(a.network_helper).resolve(strict=True);out=Path(a.output).absolute()
    if out.exists() or out.is_symlink():p.error('output must be new; never reuse a run directory')
    spec=importlib.util.spec_from_file_location('kobra_network',helper)
    net=importlib.util.module_from_spec(spec);spec.loader.exec_module(net)
    # Capability/profile check occurs before creating run files, without emulator execution.
    selected=profile_settings(a.profile,inputs,out)
    probe=['-M','rv1106','-kernel','preflight','-monitor','none']
    if selected['motor']:
        probe[1]='rv1106,virtual-deadline-enabled=on'
        probe+=['-S','-qmp','pipe:'+str(out/'qmp-preflight'),'-icount','shift=0,align=off,sleep=off']
    net.command(runtime,probe,a.network,a.http_port,a.mqtt_port)
    names=['offline-emmc.img','mcu.bin','nozzle.bin','kernel-zImage','kernel-board-dtb.dtb','disk-layout.json']
    if selected['motor']:names.append('motor.bin')
    hashes={name:sha(inputs/name) for name in names}
    link=project/'rv1106-at32-link'
    required=[link/'scripts/run_link.py',link/'tests/main-virtual-ntc.commands',link/'tests/nozzle-virtual-ntc.commands',renode]
    if selected['motor']:
        required += [project/'printer-shared-mcu/tools/generate.py',project/'printer-shared-mcu/bootstrap.resc.in',
                     project/'printer-shared-mcu/peripherals/VirtualTimeTelemetry.cs',
                     link/'scripts/shared_mcu.py',link/'scripts/lockstep_coordinator.py',
                     link/'scripts/event_clock_client.py',project/'motor-renode/scripts/load.resc']
    for path in required:
        if not path.is_file():p.error('missing prerequisite: '+str(path))
    ui_tools=None;ui_run=None;ui_commands=None
    if a.ui:
        from ui_integration import commands
        ui_tools=Path(a.ui_tools).resolve(strict=True) if a.ui_tools else (Path(__file__).resolve().parent.parent/'ui').resolve(strict=True)
        ui_run='ui-'+uuid.uuid4().hex;ui_commands=commands(ui_tools,ui_run)
        for name in ['vnc_view.py','live_view.py','run_live.py']:
            if not (project/'rv1106-linux-display'/name).is_file():p.error('Missing display source '+name)
    r9=None
    if a.profile=='r9-calibration':
        import r9_profile
        r9=r9_profile.plan(project,out/'logs',limits,thermal_rate=a.synthetic_thermal_rate or 1)
    out.mkdir(mode=0o700)
    import host_runtime_profile
    renode,host_profile=host_runtime_profile.prepare(renode,out,a.host_runtime_profile)
    if r9:
        for name,lines in r9['commands'].items():
            (out/(name+'.commands')).write_text('\n'.join(lines)+'\n')
        (out/'R9-SOURCE-PLAN.json').write_text(json.dumps(r9,indent=2)+'\n')
    elif selected['motor']:
        (out/'motor-setup.commands').write_text('# Existing shared-addon diagnostic: fixed TMC/electrical motor, no calibration.\nemulation SetGlobalQuantum "0.000001"\n')
    prepare(project,inputs,out/'boot',helper if a.network!='off' else None)
    lease=None;cap=None;disk=inputs/'offline-emmc.img'
    if a.instance:
        binding=persistence_hooks.profile_binding(hashes,a.profile,project,runtime,renode,helper,ui_tools)
        if a.host_runtime_profile!='original':binding['host-runtime-profile']=__import__('hashlib').sha256(a.host_runtime_profile.encode()).hexdigest()
        if r9:binding['r9-run-limits']=__import__('hashlib').sha256(json.dumps(limits.record(),sort_keys=True).encode()).hexdigest()
        if r9 and r9['thermal_rate_factor']!=1:binding['r9-thermal-rate']=__import__('hashlib').sha256(json.dumps({'factor':r9['thermal_rate_factor'],'synthetic':True},sort_keys=True).encode()).hexdigest()
        lease=instance_disk.open_instance(a.instance,disk,binding,recover=a.recover_instance)
        atexit.register(lease.close)
        cap=lease.begin(uuid.uuid4().hex);disk=lease.disk
    observer=out/'run-link-observer.py';write_process_observer(observer,cap,r9 is not None,limits,command_journal=a.host_runtime_profile!='original')
    wrapper=out/'qemu-wrapper.py'
    wrapper.write_text('#!'+sys.executable+'\nimport importlib.util,os,sys\n'
        's=importlib.util.spec_from_file_location("network",'+repr(str(helper))+');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n'
        'cmd=m.command('+repr(str(runtime))+',sys.argv[1:],'+repr(a.network)+','+repr(a.http_port)+','+repr(a.mqtt_port)+')\n'+persistence_hooks.wrapper_transform(cap)+'os.execv(cmd[0],cmd)\n')
    wrapper.chmod(0o700)
    command=[sys.executable,'-B',str(observer),str(link/'scripts/run_link.py'),'--qemu',str(wrapper),'--renode',str(renode),
        '--rv-image',str(out/'boot/linux-test.elf'),'--memory','128','--cpu','cortex-a7,has_el3=off',
        '--disk',str(disk),'--mcu-image',str(inputs/'mcu.bin'),
        '--mcu-base','0x08004000','--mcu-hext','24000000','--rv-uart','3',
        '--nozzle-image',str(inputs/'nozzle.bin'),'--virtual-baud','576000',
        '--mcu-setup-commands',str(link/'tests/main-virtual-ntc.commands'),
        '--nozzle-setup-commands',str(link/'tests/nozzle-virtual-ntc.commands'),
        '--renode-host-jit','single-tier','--clock-client','scalar','--timeout',str(a.seconds),'--log-dir',str(out/'logs'),'--stop-request',str(out/'stop-request')]
    command+=selected['argv']
    if r9:
        # Remove diagnostic setup/JIT options rather than relying on duplicate CLI precedence.
        for flag in ('--mcu-setup-commands','--nozzle-setup-commands','--renode-host-jit','--clock-client'):
            i=command.index(flag);del command[i:i+2]
        model_args=list(r9['model_arguments'])
        model_args[model_args.index('--renode-host-jit')+1]='single-tier'
        command+=model_args
        for flag,name in [('mcu-setup','main-setup'),('nozzle-setup','nozzle-setup'),('motor-setup','motor-setup'),('mcu-final','main-final'),('nozzle-final','nozzle-final')]:
            command+=['--'+flag+'-commands',str(out/(name+'.commands'))]
    if a.ui:
        (out/'ui.commands').write_text(ui_commands)
        command+=['--console-commands',str(out/'ui.commands'),'--console-ready','RV1106_OFFLINE_USERSPACE_READY','--vnc','--vnc-port','0']
    if a.network!='off':
        commands=out/'network.commands'
        commands.write_text('mount -t squashfs -o ro /dev/mmcblk0p10 /oem\n'+network_commands(helper,a.network))
        command+=['--console-commands',str(commands)]
    for name in ('home','tmp'):(out/name).mkdir(mode=0o700)
    plan={'host_runtime_profile':a.host_runtime_profile,'host_runtime_manifest':str(out/'HOST-RUNTIME-MANIFEST.json') if a.host_runtime_profile!='original' else None,'monitor_command_journal':str(out/'monitor-commands.jsonl') if a.host_runtime_profile!='original' else None,'requested_observation_seconds':a.seconds,'argv':command,'input_sha256':hashes,'network':a.network,'forward_ports':[v for v in (a.http_port,a.mqtt_port) if v is not None],'profile':a.profile,
          'persistence':cap,
          'disk_writes':('private instance disk; guest cache sync NOT confirmed' if cap else 'QEMU snapshot overlay only; discarded on exit'),'motor':selected['motor'],'ui':a.ui,'stop_when_ui_observed':a.stop_when_ui_observed,'ui_run_id':ui_run,'ui_tools':str(ui_tools) if ui_tools else None,'calibration':False,
          'host_network_namespace':'shared for localhost viewer; guest NIC disabled' if a.ui else ('private' if a.network=='off' else 'shared for SLIRP'),
          'vnc_warning':'No authentication: local processes can view/control. Never publicly forward. No automatic touch replay.' if a.ui else None,
          'network_guest_tested':False,'executed':a.execute,
          'cooperative_limit_seconds':selected['startup_seconds']+a.seconds+10,'hard_limit_seconds':selected['startup_seconds']+a.seconds+20,
          'global_quantum_seconds':selected['quantum_seconds'],'motor_plant':'electromechanical-driver' if r9 else 'electrical','nozzle_tmc_model':'autobaud' if r9 else 'fixed',
          'r9_sensor_validator':str(link/'experimental/native-ui-resonance/sensor_status.py') if r9 else None,'r9_model_integrated':r9 is not None,'shared_virtual_limit_ns':limits.stop_ns if r9 else None,'r9_run_limits':limits.record() if r9 else None,'automatic_calibration_started':False,
          'profile_has_prior_boot_evidence':a.profile=='two-mcu-independent','physical_calibration_proven':False,
          'cpu_allowance_seconds':4*(selected['startup_seconds']+a.seconds+20)+5,
          'cpu_budget_scope':'per-process CPU time;4x wall allowance accommodates multicore, separate wall/RSS guards unchanged',
          'max_namespace_rss_bytes':4*1024**3,'namespace_required':True}
    (out/'RUN-PLAN.json').write_text(json.dumps(plan,indent=2)+'\n')
    if not a.execute:
        print(json.dumps(plan,indent=2));return
    print('Run evidence: '+str(out),flush=True)
    print('Profile: '+a.profile+'; guest networking: '+a.network+'; UI: '+str(a.ui)+'. This is not full calibration.',flush=True)
    if a.ui:print('Waiting for Linux/UI and local VNC endpoint; observation '+str(a.seconds)+' seconds, hard wall '+str(plan['hard_limit_seconds'])+' seconds.',flush=True)
    code=execute_bounded(out,plan,inputs,hashes,lease)
    print('Diagnostic exit '+str(code)+'; see EXIT.json (0 ready, 1 process failure, 3 no Linux, 4 network incomplete, 5 UI incomplete, 6 native UI fault, 7 persistence finalization failure, 8 R9 sensor contract failure).',flush=True)
    raise SystemExit(code)

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--namespace-supervisor':
        raise SystemExit(namespace_supervisor(sys.argv[2]))
    main()
