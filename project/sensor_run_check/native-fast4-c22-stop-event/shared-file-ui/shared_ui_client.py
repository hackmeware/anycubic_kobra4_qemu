#!/usr/bin/env python3
"""Coordinated c19 display/touch client. Fresh-profile admission required.

Reads only512 VOP configuration bytes and the480x320 visible framebuffer rows
selected by that configuration. No scan, arbitrary address option, monitor,
RPC, G-code, emulator launch or active-profile edits. Touch is the existing
newline JSON route already owned and relayed by run_link.py.
"""
import argparse,ast,fcntl,hashlib,json,math,os,re,stat,sys,time,types
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[3]
PROFILE=ROOT/'calibration-native-fast4-c22-stop-event'
RUN=PROFILE/'runs/native-fast4-86400s-c23'
LIVE=None # Set only from explicit current-run binding after actual launch metadata exists.
EVIDENCE=Path(__file__).resolve().parent
BINDING=EVIDENCE/'current-run-binding.json'
LIVE_PATTERN=re.escape(str(PROFILE/'runtime-private/tmp')) + r'/rv-at32-link-[A-Za-z0-9_-]+'
EPOCH=None
HOLD_NS=100_000_000
HOLD_HOST_SECONDS=20.0
POLL_HOST_SECONDS=0.05
RENDERER_SHA='ba2f2a94e3865b277def37c129ca30667e8239dc6bcee76c9d3d06dc2a28bd28'
RAM_BYTES=128*1024*1024
PPM_HEADER=b'P6\n480 320\n255\n'
PPM_BYTES=len(PPM_HEADER)+480*320*3

def digest(data):return hashlib.sha256(data).hexdigest()
def regular(path,size=None):
    s=path.stat(follow_symlinks=False)
    if not stat.S_ISREG(s.st_mode) or (size is not None and s.st_size!=size):raise ValueError('Unexpected public file type/size: '+path.name)
    return (s.st_dev,s.st_ino)
def read_json(path,limit=1024*1024):
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('Not a regular report')
        raw=os.read(fd,limit+1)
        if len(raw)>limit:raise ValueError('Report exceeds limit')
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError('Invalid report')
        return value
    finally:os.close(fd)
def image_bytes(path):
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size!=PPM_BYTES:raise ValueError('Unexpected observed image size/type')
        raw=os.read(fd,PPM_BYTES+1)
        if len(raw)!=PPM_BYTES or not raw.startswith(PPM_HEADER):raise ValueError('Observed image changed or is incomplete')
        return raw
    finally:os.close(fd)
def create_binding():
    """Read only the fixed c19 run's published paths/epoch; no user path options."""
    if (RUN/'stop-request').exists():raise ValueError('Run already stopping')
    args=read_json(RUN/'qemu-execution.json').get('args',[])
    objects=[args[i+1] for i,value in enumerate(args[:-1]) if value=='-object' and isinstance(args[i+1],str) and args[i+1].startswith('memory-backend-file,')]
    if len(objects)!=1:raise ValueError('Expected exactly one display memory backend')
    match=re.fullmatch(r'memory-backend-file,id=displayram,size=128M,mem-path=(' + LIVE_PATTERN + r')/guest-ram.bin,share=on',objects[0])
    if not match:raise ValueError('Unexpected current-run display backend')
    live=Path(match[1])
    if live.is_symlink() or live.resolve()!=live:raise ValueError('Unexpected display directory alias')
    clock=read_json(RUN/'virtual-time.json');epoch=clock.get('epoch')
    if not isinstance(epoch,str) or not re.fullmatch('[0-9a-f]{32}',epoch):raise ValueError('Invalid current-run clock epoch')
    if clock.get('enabled') is not True or clock.get('time_went_backwards') is not False:raise ValueError('Inactive clock')
    if not 0<=time.time()-(RUN/'virtual-time.json').stat().st_mtime<=3:raise ValueError('Stale public clock')
    pin={'run':str(RUN),'live':str(live),'epoch':epoch,'qemu_execution_sha256':digest(json.dumps(read_json(RUN/'qemu-execution.json'),sort_keys=True).encode()),
         'ram_identity':regular(live/'guest-ram.bin',RAM_BYTES),'vop_identity':regular(live/'live-vop.bin',512),'touch_identity':regular(live/'touch.jsonl')}
    with (EVIDENCE/'current-run-binding.json').open('x') as stream:
        json.dump(pin,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    return pin

def load_binding():
    global LIVE,EPOCH
    pin=read_json(BINDING)
    if pin.get('run')!=str(RUN) or not isinstance(pin.get('live'),str) or not re.fullmatch(LIVE_PATTERN,pin['live']):raise ValueError('Binding belongs to another run')
    live=Path(pin['live'])
    if live.is_symlink() or live.resolve()!=live:raise ValueError('Unexpected display directory alias')
    if not isinstance(pin.get('epoch'),str) or not re.fullmatch('[0-9a-f]{32}',pin['epoch']):raise ValueError('Invalid binding epoch')
    if digest(json.dumps(read_json(RUN/'qemu-execution.json'),sort_keys=True).encode())!=pin.get('qemu_execution_sha256'):raise ValueError('Launch metadata changed after binding')
    for name,size in [('ram',RAM_BYTES),('vop',512),('touch',None)]:
        path=live/{'ram':'guest-ram.bin','vop':'live-vop.bin','touch':'touch.jsonl'}[name]
        if list(regular(path,size))!=pin.get(name+'_identity'):raise ValueError('Bound display/input file replaced')
    LIVE=live;EPOCH=pin['epoch']
    return pin

def running():
    if (RUN/'stop-request').exists():raise ValueError('Run already stopping')
    clock=read_json(RUN/'virtual-time.json')
    if clock.get('epoch')!=EPOCH or clock.get('enabled') is not True or clock.get('time_went_backwards') is not False or not 0<=clock.get('virtual_time_ns',-1)<720_000_000_000:raise ValueError('Wrong/stopped clock')
    if not 0<=time.time()-(RUN/'virtual-time.json').stat().st_mtime<=3:raise ValueError('Stale public clock')
    return clock

def atomic_once(path,value):
    # Link a complete fsynced temporary inode into a never-overwritten name.
    temporary=path.with_name(path.name+'.pending')
    with temporary.open('x') as stream:
        json.dump(value,stream,sort_keys=True,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    try:os.link(temporary,path)
    finally:temporary.unlink()
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)

_WLAN_CONTRACT=None
def wlan_contract():
    global _WLAN_CONTRACT
    if _WLAN_CONTRACT is None:
        path=PROFILE/'rv1106-at32-link/experimental/native-ui-resonance/wlan_stream_review.py'
        if path.is_symlink():raise ValueError('Console review contract symlink')
        raw=path.read_bytes()
        if digest(raw)!='0e6cca8f19b856f415ed2052d2ffd24a44f58559600ae1cbca6c973ec6f974ee':raise ValueError('Console review contract source mismatch')
        import types
        module=types.ModuleType('ui_console_review_contract');module.__file__=str(path)
        exec(compile(raw,str(path),'exec'),module.__dict__)
        _WLAN_CONTRACT=module
    return _WLAN_CONTRACT

# The only new executable dependency is the original parser's pure AST subset.
# Do not import its observer/protocol module: those also define guest queries.
BASE_PARSER_SHA='04311b970f4f1d250cb4d7ac2cc340275a616f1568a7ace9e81108d0d0723db9'
BASELINE_SHA='7fa36cad2dcb78a71d49880c2aeb02c9043252870cde24d9612480c40e3e8c4f'
LIS_ERROR=re.compile(r'(?i)(?:\b(?:error|failed|failure|invalid|timeout|fault)\b.*\blis2dw12\b|\blis2dw12\b.*\b(?:error|failed|failure|invalid|timeout|fault)\b)')

def strict_console_parser():
    folder=PROFILE/'rv1106-at32-link/experimental/sensor30-observation'
    path=folder/'observer.py'
    if path.is_symlink():raise ValueError('Strict console parser source symlink')
    raw=path.read_bytes()
    if digest(raw)!=BASE_PARSER_SHA:raise ValueError('Strict console parser source mismatch')
    wanted={'AUXILIARY','VIDEO','LOG_LINE','ANSI','native_entries','NativeReview'}
    nodes=[];found=set()
    for node in ast.parse(raw,filename=str(path)).body:
        name=node.name if isinstance(node,(ast.ClassDef,ast.FunctionDef)) else None
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):name=node.targets[0].id
        if name in wanted:nodes.append(node);found.add(name)
    if found!=wanted or len(nodes)!=len(wanted):raise ValueError('Unexpected pinned parser structure')
    base=types.ModuleType('c17_pure_console_parser');base.re=re
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),base.__dict__)
    baseline=folder/'evidence/ready-baseline.console.txt'
    if baseline.is_symlink():raise ValueError('Console classification baseline symlink')
    raw=baseline.read_bytes()
    if digest(raw)!=BASELINE_SHA:raise ValueError('Console classification baseline changed')
    text=raw.decode('utf-8',errors='replace')
    if not base.NativeReview().observe(text):raise ValueError('Classification baseline lacks Ready')
    observed={(severity,source,message) for _,_,severity,source,message in base.native_entries(text)}
    if any(('error',source,message) not in observed for message,source in base.AUXILIARY.items()) or ('error',211,base.VIDEO) not in observed:raise ValueError('Pinned classification template missing')
    return base

ECHO_REVIEW_SHA='67a3e6b6ff6b9dfd000c708e3094b67bb05331b2c57e27afcd848c27dd42c062'
SENSOR_STATUS_SHA='a7227dc3ac258c0e09ee5ef15d2ca0f455636c1739b53959a639e879c81d9a22'

def hold_helpers():
    folder=PROFILE/'rv1106-at32-link/experimental/native-ui-resonance'
    modules=[]
    for filename,expected,names in [('echo_review.py',ECHO_REVIEW_SHA,None),('sensor_status.py',SENSOR_STATUS_SHA,{'PROFILE','check'})]:
        path=folder/filename
        if path.is_symlink():raise ValueError('Held-check helper symlink')
        raw=path.read_bytes()
        if digest(raw)!=expected:raise ValueError('Held-check helper source mismatch: '+filename)
        module=types.ModuleType('held_'+filename.replace('.','_'))
        if names is None:code=compile(raw,str(path),'exec')
        else:
            nodes=[]
            for node in ast.parse(raw,filename=str(path)).body:
                name=node.name if isinstance(node,ast.FunctionDef) else None
                if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):name=node.targets[0].id
                if name in names:nodes.append(node)
            if len(nodes)!=len(names):raise ValueError('Unexpected pinned sensor helper')
            code=compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec')
        exec(code,module.__dict__);modules.append(module)
    return modules

_STARTUP_CONTRACT=None

def startup_contract():
    global _STARTUP_CONTRACT
    if _STARTUP_CONTRACT is None:
        path=PROFILE/'rv1106-at32-link/experimental/native-ui-resonance/startup_readiness.py'
        if path.is_symlink():raise ValueError('Startup contract source symlink')
        raw=path.read_bytes()
        if digest(raw)!='2ea0cc41c5416821cdb7da076a6084a80a8aee9821a87055232b991d3a24b2e0':raise ValueError('Startup contract source mismatch')
        module=types.ModuleType('ui_startup_contract');module.__file__=str(path)
        exec(compile(raw,str(path),'exec'),module.__dict__)
        _STARTUP_CONTRACT=module
    return _STARTUP_CONTRACT

class _ConsoleGrowth(Exception):pass

class HeldConsole:
    """Full raw review plus one exact bound echo, only during an existing press.

    No suffix is removed from native review. Unknown tails and all pending or
    fatal evidence veto. Expected partial echo is provisional, time/byte-bounded,
    never admission_clear; a complete bound echo/prompt is required to finish.
    The observer's receipt remains a checked immutable prefix of current bytes.
    """
    def __init__(self,record,clock,x,y):
        self.review=wlan_contract().UiNativeReview(strict_console_parser())
        echo,self.sensor=hold_helpers()
        self.echo=echo.BoundTouchEcho(x,y,record['native_console_review']['console_bytes'])
        self.identity=None;self.failure=None;self.previous_sensor=None;self.last_status=None
        self.check(record,clock)

    @staticmethod
    def stamp(info):return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)

    def check(self,record,clock):
        if self.failure is not None:raise ValueError('Latched held-console failure: '+self.failure)
        try:
            for attempt in range(3):
                try:
                    result=self._check(record,clock);self.last_status=result;return result
                except _ConsoleGrowth:
                    if attempt==2:raise ValueError('Held console kept changing during bounded fresh review')
        except BaseException as error:
            self.failure=type(error).__name__+': '+str(error);raise

    def sensor_safe(self,record,source):
        if (record.get('native_readiness_verified') is not True or record.get('startup_marker_observed') is not True or
            record.get('thermal_profile_verified') is not True or record.get('sensor_model_attached') is not True):raise ValueError('Missing independently verified native/thermal/sensor readiness')
        sensor=record.get('sensor_status',{})
        if not self.sensor.check(sensor,source):raise ValueError('In-flight LIS source/readiness absent')
        previous=self.previous_sensor
        if previous is not None:
            if any(sensor[k]<previous[k] for k in ('sequence','virtual_time_ns','source_captures','published_pairs','superseded_pairs')) or (sensor['sequence']==previous['sequence'] and sensor!=previous):raise ValueError('In-flight LIS status replaced/backward')
            if any(sensor[b]['consumed_source_samples']<previous[b]['consumed_source_samples'] for b in ('main','nozzle')):raise ValueError('In-flight LIS source counter regressed')
        self.previous_sensor=json.loads(json.dumps(sensor,sort_keys=True,allow_nan=False))

    def _check(self,record,clock):
        contract=wlan_contract();receipt=record.get('native_console_review',{})
        partial=receipt.get('incomplete_tail')
        if (receipt.get('contract')!=contract.CONTRACT or type(partial) is not bool or
            receipt.get('admission_clear') is not (not partial) or
            type(receipt.get('pending_count')) is not int or receipt['pending_count']!=0 or
            receipt.get('pending')!=[] or receipt.get('failure') is not None or receipt.get('finalized') is not False):raise ValueError('Native console review blocks in-flight hold')
        count=receipt.get('console_bytes');sha=receipt.get('console_sha256')
        if (type(count) is not int or not 0<=count<=contract.MAX_CONSOLE or not isinstance(sha,str) or re.fullmatch('[a-f0-9]{64}',sha) is None):raise ValueError('Invalid console hold prefix receipt')
        source=record.get('last_shared_mcu_ns')
        if (type(source) is not int or not 0<=clock['virtual_time_ns']-source<=200_000_000 or receipt.get('observed_source_ns')!=source):raise ValueError('Stale/inconsistent held-console source')
        self.sensor_safe(record,source)
        path=RUN/'console.bin';fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            before=os.fstat(fd);identity=(before.st_dev,before.st_ino)
            if not stat.S_ISREG(before.st_mode) or not 0<=before.st_size<=contract.MAX_CONSOLE:raise ValueError('Not a bounded regular held console')
            if self.identity is not None and identity!=self.identity:raise ValueError('Held console file replaced')
            if regular(path)!=identity:raise ValueError('Held console pathname replaced')
            self.identity=identity;chunks=[];remaining=before.st_size
            while remaining:
                data=os.read(fd,min(remaining,1024*1024))
                if not data:raise ValueError('Held console shortened during read')
                chunks.append(data);remaining-=len(data)
            raw=b''.join(chunks)
            grew_during_read=bool(os.read(fd,1)) or self.stamp(os.fstat(fd))!=self.stamp(before)
            if len(raw)<count or digest(raw[:count])!=sha:raise ValueError('Held console observer prefix changed')
            for line in self.review.base.ANSI.sub('',raw.decode('utf-8',errors='replace')).splitlines():
                if LIS_ERROR.search(line):raise ValueError('Sensor error during hold: '+line)
            self.review.observe(raw,host_now=time.monotonic(),source_ns=source)
            if not startup_contract().parse(contract.native_text(raw.decode('utf-8',errors='replace'),self.review.base),RUN.name)['startup_complete' if record.get('native_pid_request_observed') is True else 'ready']:raise ValueError('Current held console lacks native UI readiness')
            status=self.echo.observe(raw,host_now=time.monotonic(),source_ns=clock['virtual_time_ns'])
            if status['status']=='unknown partial':raise ValueError('Unrecognized/expired held transport: '+str(status['reason']))
            if partial:
                prior=self.echo.prefix_status(raw[:count])
                if prior['status'] not in ('known incomplete','complete known prompt'):raise ValueError('Observer partial tail is not this bound touch transport')
            if self.review.partial:
                if status['status'] not in ('known incomplete','complete known prompt') or self.review.pending or self.review.failure or self.review.finalized:raise ValueError('Unreviewed held-console partial tail')
            else:self.review.require_clear()
            current=os.fstat(fd);named=path.stat(follow_symlinks=False)
            if grew_during_read or self.stamp(current)!=self.stamp(before) or self.stamp(named)!=self.stamp(before):
                # Inspect each finite prefix before retrying append-only growth.
                # A fault, pending event, unknown tail or rewrite never retries.
                if (current.st_dev,current.st_ino)==identity and current.st_size>before.st_size and self.stamp(named)==self.stamp(current):raise _ConsoleGrowth()
                raise ValueError('Held console replaced/rewritten during classification')
            return {**status,'observer_known_touch_tail':partial,'whole_console_bytes':len(raw),'whole_console_sha256':digest(raw)}
        finally:os.close(fd)

def thermal_ready(*, hold_console=None):
    if (RUN/'ui-pid-intent.json').exists():raise ValueError('Once-only PID confirmation already armed; no new touch down')
    clock=running();path=RUN/'native-calibration-attempt.json';record=read_json(path)
    if not 0<=time.time()-path.stat().st_mtime<=3:raise ValueError('Stale thermal observation report')
    if hold_console is None:wlan_contract().require_report_clear(record,RUN)
    else:hold_console.check(record,clock)
    startup_contract().require_report(record,RUN,EPOCH)
    if record.get('thermal_baseline_ready') is not True or record.get('phase')!='waiting_ui_pid_request':
        if not (hold_console is not None and hold_console.last_status['observer_known_touch_tail'] and record.get('thermal_baseline_ready') is False and record.get('phase')=='waiting_native_console_review'):raise ValueError('Thermal UI baseline is not ready')
    if record.get('final_export_requested') is not False or record.get('native_pid_request_observed') is not False or 'error' in record:raise ValueError('Observer is stopping, heating or has an error')
    observed=record.get('last_shared_mcu_ns')
    if type(observed) is not int or not 0<=clock['virtual_time_ns']-observed<=200_000_000:raise ValueError('Stale shared observation')
    if record.get('thermal_profile_verified') is not True:raise ValueError('Thermal composition is not verified')
    cold_rows(record)
    return record

def cold_rows(record):
    heaters=record.get('dual_thermal',{})
    for name,adc,pin in [('bed','3911','pa0'),('nozzle','4023','pb8')]:
        summary=heaters.get(name,{});latest=summary.get('latest',{})
        if summary.get('early_stop_required') is not False or not summary.get('rows') or latest.get('sensor_fault')!='none':raise ValueError('No current normal '+name+' observation')
        if type(summary.get('source_age_us')) is not int or not 0<=summary['source_age_us']<=200000:raise ValueError('Stale '+name+' telemetry')
        if any(latest.get(key)!='0' for key in ('last_heater_duty','last_fan_duty','model_overtemperature','model_heater_latched_off',pin+'_level')):raise ValueError('Unexpected thermal activity/fault')
        if name=='nozzle' and latest.get('curve_out_of_range')!='0':raise ValueError('Nozzle curve range fault')
        temperature=float(latest.get('physical_temperature_c','nan'))
        if not math.isfinite(temperature) or abs(temperature-25)>1e-6 or latest.get('published_adc_code')!=adc:raise ValueError('Baseline temperature/ADC changed')

def intent_hold_safe(intent_sha256, *, hold_console=None):
    clock=running();path=RUN/'native-calibration-attempt.json';record=read_json(path)
    if not 0<=time.time()-path.stat().st_mtime<=3 or 'error' in record or record.get('final_export_requested') is not False:raise ValueError('In-flight PID observer stale or stopping')
    observed=record.get('last_shared_mcu_ns')
    if type(observed) is not int or not 0<=clock['virtual_time_ns']-observed<=200_000_000:raise ValueError('Stale in-flight source observation')
    if hold_console is None:wlan_contract().require_report_clear(record,RUN)
    else:hold_console.check(record,clock)
    startup_contract().require_report(record,RUN,EPOCH,after_native_pid=record.get('native_pid_request_observed') is True)
    if record.get('ui_pid_intent_sha256') not in (None,intent_sha256):raise ValueError('Different in-flight UI PID intent')
    for heater in ('bed','nozzle'):
        summary=record.get('dual_thermal',{}).get(heater,{});row=summary.get('latest',{})
        if summary.get('early_stop_required') is not False or row.get('sensor_fault')!='none' or any(row.get(k)!='0' for k in ('model_overtemperature','model_heater_latched_off')):raise ValueError('In-flight thermal fault/bound')
        if heater=='nozzle' and row.get('curve_out_of_range')!='0':raise ValueError('In-flight nozzle curve fault')
        temperature=float(row.get('physical_temperature_c','nan'))
        if not math.isfinite(temperature) or not 25<=temperature<({'bed':120,'nozzle':260}[heater]):raise ValueError('In-flight thermal range')
    return record

class DisplaySurface:
    def __init__(self):
        self.ram=LIVE/'guest-ram.bin';self.vop=LIVE/'live-vop.bin';self.touch=LIVE/'touch.jsonl'
        args=read_json(RUN/'qemu-execution.json').get('args',[])
        expected=f'memory-backend-file,id=displayram,size=128M,mem-path={self.ram},share=on'
        if args.count(expected)!=1 or args[args.index(expected)-1]!='-object':raise ValueError('Not the recorded live display backing')
        self.identity={'ram':regular(self.ram,RAM_BYTES),'vop':regular(self.vop,512),'touch':regular(self.touch),'epoch':EPOCH,'run':str(RUN),'live':str(LIVE)}
        path=PROFILE/'rv1106-linux-display/live_view.py';source=path.read_bytes()
        if digest(source)!=RENDERER_SHA:raise ValueError('Restored renderer identity changed')
        ns={'__name__':'public_display_renderer','__file__':str(path)}
        exec(compile(source,str(path),'exec'),ns)
        self.config=ns['read_config'];self.pixels=ns['pixels']
    def check_identity(self):
        if regular(self.ram,RAM_BYTES)!=self.identity['ram'] or regular(self.vop,512)!=self.identity['vop'] or regular(self.touch)!=self.identity['touch']:raise ValueError('Public display/input file replaced')
    def once(self):
        self.check_identity();cfg=self.config(self.vop,RAM_BYTES)
        w,h,stride,addr,fmt,swap=cfg
        if (w,h)!=(480,320):raise ValueError('Native480x320 framebuffer not configured')
        bpp={0:4,1:3,2:2}[fmt]
        # The unchanged renderer asks for its selected framebuffer span. This
        # proxy fulfills it by reading ONLY visible rows; unread stride padding
        # is zero-filled and is never used in the resulting rendered pixels.
        surface=self
        class VisibleRows:
            def __getitem__(self,key):
                if not isinstance(key,slice) or key.start!=addr or key.stop!=addr+stride*h or key.step is not None:raise ValueError('Renderer requested non-framebuffer memory')
                fd=os.open(surface.ram,os.O_RDONLY|os.O_NOFOLLOW)
                try:
                    s=os.fstat(fd)
                    if (s.st_dev,s.st_ino)!=surface.identity['ram'] or s.st_size!=RAM_BYTES:raise ValueError('RAM backing replaced')
                    visible=bytearray(stride*h)
                    for row in range(h):
                        data=os.pread(fd,w*bpp,addr+row*stride)
                        if len(data)!=w*bpp:raise ValueError('Short visible framebuffer row')
                        visible[row*stride:row*stride+w*bpp]=data
                    return visible
                finally:os.close(fd)
        pixels=bytes(self.pixels(VisibleRows(),cfg))
        if len(pixels)!=480*320*4:raise ValueError('Unexpected rendered pixel length')
        if self.config(self.vop,RAM_BYTES)!=cfg:raise ValueError('Display configuration changed during capture')
        self.check_identity();return pixels,cfg
    def frame(self):
        for _ in range(3):
            running();first,cfg=self.once();second,cfg2=self.once()
            if first==second and cfg==cfg2:return first,cfg
        raise ValueError('Display changed during bounded capture; inspect a fresh frame')
    def append_click(self,x,y,*,pid_intent=None):
        """Separate queued down/up by measured public clock progress, not host sleep.

        Queue spacing is not proof of when guest uinput/UI received either event.
        A stop/timeout/error aborts the hold and attempts one release on this same
        input file. Release is cleanup even when cold-ready is no longer true.
        """
        self.check_identity()
        if type(x) is not int or type(y) is not int or not(0<=x<480 and 0<=y<320):raise ValueError('Outside framebuffer')
        thermal_ready();initial=running()
        if initial['virtual_time_ns']+HOLD_NS>=720_000_000_000:raise ValueError('Insufficient shared budget for bounded touch hold')
        began=time.monotonic();deadline=began+HOLD_HOST_SECONDS
        result={'hold_requested_ns':HOLD_NS,'hold_host_limit_s':HOLD_HOST_SECONDS,'down_state':'not_attempted','release_state':'not_attempted','guest_receipt_proven':False}
        fd=os.open(self.touch,os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW)
        original_error=None
        def append(down):
            s=os.fstat(fd)
            if not stat.S_ISREG(s.st_mode) or (s.st_dev,s.st_ino)!=self.identity['touch'] or regular(self.touch)!=self.identity['touch']:raise ValueError('Touch file replaced')
            data=(json.dumps({'x':x,'y':y,'down':down})+'\n').encode()
            count=os.write(fd,data)
            if count!=len(data):raise OSError('Uncertain partial touch append; never retry this observation')
            # Full line bytes are known written even if the durability flush fails.
            # That permits exactly one cleanup release, not a press retry.
            result['down_state' if down else 'release_state']='fully_written_not_receipt_or_durability_proven'
            os.fsync(fd)
        try:
            with wlan_contract().admission_lock(RUN,monotonic=time.monotonic,sleep=time.sleep):
                admission_record=thermal_ready()
                if time.monotonic()>=deadline:raise TimeoutError('Touch host deadline before press')
                if (RUN/'stop-request').exists():raise ValueError('Run already stopping')
                if pid_intent is not None:
                    baseline=thermal_ready();at=running()
                    intent={**pid_intent,'schema':1,'run':str(RUN),'epoch':EPOCH,
                        'source_ns':at['virtual_time_ns'],'baseline_shared_ns':baseline['last_shared_mcu_ns'],
                        'baseline_report_sha256':digest(json.dumps(baseline,sort_keys=True).encode()),
                        'native_request_acceptance_proven':False,'parent_confirmation_attested':True}
                    atomic_once(RUN/'ui-pid-intent.json',intent)
                    result['pid_intent_sha256']=digest(json.dumps(intent,sort_keys=True).encode())
            if pid_intent is not None:
                ack_deadline=min(deadline,time.monotonic()+2.0)
                while True:
                    if time.monotonic()>=ack_deadline:raise TimeoutError('PID intent acknowledgement exceeded2s host ceiling')
                    acknowledged=intent_hold_safe(result['pid_intent_sha256'])
                    cold_rows(acknowledged)
                    if acknowledged.get('native_pid_request_observed') is not False:raise ValueError('Native PID request preceded confirmation press')
                    if acknowledged.get('ui_pid_intent_sha256')==result['pid_intent_sha256']:
                        if acknowledged.get('ui_pid_intent_observed') is not True or acknowledged.get('phase')!='waiting_native_pid_log':raise ValueError('Malformed PID intent acknowledgement')
                        result['observer_intent_acknowledged_before_down']=True
                        break
                    time.sleep(min(POLL_HOST_SECONDS,max(0,ack_deadline-time.monotonic())))
            with wlan_contract().admission_lock(RUN,monotonic=time.monotonic,sleep=time.sleep):
                if pid_intent is None:admission_record=thermal_ready()
                else:
                    admission_record=intent_hold_safe(result['pid_intent_sha256'])
                    cold_rows(admission_record)
                    if (admission_record.get('ui_pid_intent_sha256')!=result['pid_intent_sha256'] or admission_record.get('ui_pid_intent_observed') is not True or
                        admission_record.get('phase')!='waiting_native_pid_log' or admission_record.get('native_pid_request_observed') is not False):raise ValueError('PID acknowledgement changed before down')
                    if digest(self.frame()[0])!=pid_intent.get('frame_sha256'):raise ValueError('PID confirmation frame changed during acknowledgement')
                hold_console=HeldConsole(admission_record,running(),x,y)
                # Current full observer receipt remains mandatory for every down.
                # The producer is not locked; later bytes are an in-flight event.
                wlan_contract().require_report_clear(admission_record,RUN)
                if time.monotonic()>=deadline:raise TimeoutError('Touch host deadline before press')
                if (RUN/'stop-request').exists():raise ValueError('Run already stopping')
                result['down_state']='attempted_uncertain';append(True);result['down_state']='queued_not_receipt_proven'
            snapshot=running();start_ns=snapshot['virtual_time_ns'];previous_ns=start_ns
            result['post_down_published_ns']=start_ns
            while True:
                if time.monotonic()>=deadline:raise TimeoutError('Touch hold exceeded20s host ceiling')
                if pid_intent is None:thermal_ready(hold_console=hold_console)
                else:intent_hold_safe(result['pid_intent_sha256'],hold_console=hold_console)
                sample=running();now=sample['virtual_time_ns']
                if now<previous_ns:raise ValueError('Published clock moved backwards during hold')
                previous_ns=now;result['last_published_ns']=now;result['published_queue_spacing_ns']=now-start_ns
                if time.monotonic()>=deadline:raise TimeoutError('Touch hold exceeded20s host ceiling')
                if now-start_ns>=HOLD_NS and hold_console.last_status['complete']:
                    result['bound_down_transport']=hold_console.last_status
                    break
                time.sleep(min(POLL_HOST_SECONDS,max(0,deadline-time.monotonic())))
        except BaseException as error:
            original_error=error;result['hold_error']=type(error).__name__+': '+str(error)
            raise
        finally:
            if result['down_state']=='attempted_uncertain':
                result['release_state']='withheld_after_uncertain_down_append'
            if result['down_state'] in ('queued_not_receipt_proven','fully_written_not_receipt_or_durability_proven'):
                try:
                    result['release_state']='attempted_uncertain';append(False);result['release_state']='queued_not_receipt_proven'
                except BaseException as error:
                    result['release_error']=type(error).__name__+': '+str(error)
                    if original_error is None:original_error=error
            result['host_elapsed_seconds']=time.monotonic()-began
            os.close(fd)
            if pid_intent is not None and 'pid_intent_sha256' in result:
                atomic_once(RUN/'ui-pid-input-outcome.json',result)
            with (EVIDENCE/'touch-hold-results.jsonl').open('a') as stream:stream.write(json.dumps(result)+'\n')
            if original_error is not None and 'hold_error' not in result:raise original_error
        return result

def ppm(raw):
    rgb=bytearray()
    for n in range(0,len(raw),4):rgb.extend((raw[n+2],raw[n+1],raw[n]))
    return PPM_HEADER+rgb

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('bind')
    c=sub.add_parser('capture');c.add_argument('--name',required=True)
    c=sub.add_parser('click');c.add_argument('--observed',type=Path,required=True);c.add_argument('--x',type=int,required=True);c.add_argument('--y',type=int,required=True);c.add_argument('--visible-label',required=True);c.add_argument('--pid-confirmation',action='store_true',help='Parent attests this exact observed control confirms the native calibration/PID start; once only')
    a=p.parse_args();EVIDENCE.mkdir(exist_ok=True)
    if a.action=='bind':
        with (RUN/'ui-control.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);print(json.dumps(create_binding()))
        return
    load_binding();running()
    with (RUN/'ui-control.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);running();surface=DisplaySurface();raw,cfg=surface.frame();now=time.time();sha=digest(raw)
        if a.action=='capture':
            if not a.name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in a.name):raise ValueError('Safe new capture name required')
            folder=EVIDENCE/'ui-captures';folder.mkdir(exist_ok=True);image=folder/(a.name+'.ppm');meta=folder/(a.name+'.json')
            with image.open('xb') as stream:stream.write(ppm(raw))
            record={'actual_display_pixels':True,'transport':'existing public display backing; visible rows only','frame_sha256':sha,'ppm_sha256':digest(image_bytes(image)),'host_time':now,'image':str(image),'identity':surface.identity,'display_config':cfg,'renderer_sha256':RENDERER_SHA}
            with meta.open('x') as stream:json.dump(record,stream,indent=2);stream.write('\n')
            print(json.dumps(record));return
        observed=a.observed.resolve()
        if observed.parent!=EVIDENCE/'ui-captures':raise ValueError('Observation from another location')
        old=read_json(observed)
        # JSON serializes tuples as arrays; compare canonical serialization.
        if old.get('actual_display_pixels') is not True or json.dumps(old.get('identity'),sort_keys=True)!=json.dumps(surface.identity,sort_keys=True):raise ValueError('Wrong observed display session')
        if old.get('renderer_sha256')!=RENDERER_SHA or old.get('display_config')!=list(cfg):raise ValueError('Display configuration changed')
        if not 0<=now-old.get('host_time',0)<=120:raise ValueError('Observation too old')
        if old.get('frame_sha256')!=sha:raise ValueError('Visible frame changed; capture and inspect again')
        image=Path(old['image'])
        if image.parent!=observed.parent or digest(image_bytes(image))!=old.get('ppm_sha256'):raise ValueError('Observed pixels changed')
        if not a.visible_label.strip() or not(0<=a.x<480 and 0<=a.y<320):raise ValueError('Observed control and valid coordinates required')
        thermal_ready();event={'host_time':now,'action':'pointer_down_up','x':a.x,'y':a.y,'visible_label':a.visible_label,'observation':str(observed),'frame_sha256':sha,'transport':'existing touch.jsonl','no_rpc':True}
        try:
            with observed.with_suffix('.consumed.json').open('x') as stream:
                json.dump({**event,'state':'consumed_before_send'},stream);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        except FileExistsError:raise ValueError('Observation already consumed; capture and inspect again')
        with (EVIDENCE/'ui-actions.jsonl').open('a') as stream:stream.write(json.dumps({**event,'state':'before_send'})+'\n')
        # A final frame check after observation consumption closes lengthy metadata
        # I/O gaps. If changed/uncertain, consumed stays consumed and no retry occurs.
        if surface.frame()[0]!=raw:raise ValueError('Visible frame changed immediately before append')
        intent=None
        if a.pid_confirmation:
            intent={'purpose':'original_ui_calibration_confirmation_native_pid_start',
                'observed_frame':old,'consumed_action':read_json(observed.with_suffix('.consumed.json')),
                'frame_sha256':sha,'x':a.x,'y':a.y,'visible_label':a.visible_label}
        hold=surface.append_click(a.x,a.y,pid_intent=intent)
        with (EVIDENCE/'ui-actions.jsonl').open('a') as stream:stream.write(json.dumps({**event,'state':'queued_not_yet_observed','hold':hold})+'\n')
        print(json.dumps(event))
if __name__=='__main__':main()
