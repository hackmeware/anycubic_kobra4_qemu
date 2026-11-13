#!/usr/bin/env python3
"""Run against rebuilt QEMU. Isolated, no firmware/disk/network/hardware.

Observed timer overshoot must meet the unchanged 5ms diagnostic bound in this
run. Passing samples do not guarantee a host-independent scheduling bound.
"""
import argparse
import json
import os
import pathlib
import select
import subprocess
import sys
import time

class VM:
    def __init__(self, executable, enabled):
        self.proc=subprocess.Popen([executable,'-M','rv1106'+(',virtual-deadline-enabled=on' if enabled else ''),
            '-m','64M','-S','-display','none','-serial','null','-monitor','none','-qmp','stdio']
            + (['-icount',f'shift={ICOUNT_SHIFT},align=off,sleep=off'] if ICOUNT_SHIFT is not None else []),
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.buffer=b'';self.serial=0;self.events=[]
        assert 'QMP' in self.read()
        self.call('qmp_capabilities')
    def read(self):
        end=time.monotonic()+3
        while b'\n' not in self.buffer:
            left=end-time.monotonic()
            if left<=0 or not select.select([self.proc.stdout],[],[],left)[0]:raise RuntimeError('QMP timeout')
            data=os.read(self.proc.stdout.fileno(),65536)
            if not data:raise RuntimeError('QMP EOF: '+self.proc.stderr.read().decode())
            self.buffer+=data
        line,self.buffer=self.buffer.split(b'\n',1)
        return json.loads(line)
    def call(self,command,args=None,error=False):
        self.serial+=1;req={'execute':command,'id':self.serial}
        if args is not None:req['arguments']=args
        self.proc.stdin.write((json.dumps(req)+'\n').encode());self.proc.stdin.flush()
        while True:
            result=self.read()
            if 'event' in result:self.events.append(result);continue
            if result.get('id')!=self.serial:continue
            if error:
                assert 'error' in result,result
                return result['error']
            assert 'error' not in result,result
            return result.get('return')
    def get(self,name):return self.call('qom-get',{'path':'/machine','property':name})
    def set(self,name,value,**kwargs):return self.call('qom-set',{'path':'/machine','property':name,'value':value},**kwargs)
    def close(self):
        self.proc.terminate()
        try:
            self.proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.communicate(timeout=5)

parser=argparse.ArgumentParser()
parser.add_argument('executable')
parser.add_argument('--icount-shift',type=int,choices=range(11),default=None)
parser.add_argument('--iterations',type=int,default=10)
parser.add_argument('--quantum-ns',type=int,default=1000000)
options=parser.parse_args()
if not 1 <= options.iterations <= 10000 or not 1 <= options.quantum_ns <= 10000000:
    parser.error("iterations must be 1..10000; quantum-ns 1..10000000")
ICOUNT_SHIFT=options.icount_shift
executable=str(pathlib.Path(options.executable).resolve())
vm=VM(executable,False)
try:
    assert vm.get('virtual-deadline-enabled') is False
    assert vm.get('virtual-deadline-armed') is False
    q=vm.get('virtual-time-ns');assert isinstance(q,int)
    vm.set('virtual-time-ns',123,error=True)
    vm.set('virtual-deadline-enabled',True,error=True)
    vm.set('virtual-deadline-ns',q+1000000,error=True)
finally:vm.close()
vm=VM(executable,True)
try:
    assert vm.get('virtual-deadline-enabled') is True
    q=vm.get('virtual-time-ns');time.sleep(.02);assert vm.get('virtual-time-ns')==q
    vm.set('virtual-deadline-ns',-1,error=True)
    vm.set('virtual-deadline-ns',q,error=True) if q else None
    vm.set('virtual-deadline-ns',q+1000000)
    assert vm.get('virtual-deadline-armed') is True
    vm.set('virtual-deadline-ns',0)
    assert vm.get('virtual-deadline-armed') is False
    assert vm.get('virtual-deadline-fired') is False
    assert vm.get('virtual-deadline-stop-ns')==-1
    samples=[];callback_overshoots=[]
    started=time.monotonic()
    for iteration in range(options.iterations):
        deadline=vm.get('virtual-time-ns')+options.quantum_ns
        vm.set('virtual-deadline-ns',deadline)
        vm.call('cont');limit=time.monotonic()+3
        while vm.call('query-status')['running']:
            if time.monotonic()>limit:
                raise AssertionError({'error':'Deadline failed to pause VM','iteration':iteration,
                    'actual_ns':vm.get('virtual-time-ns'),'requested_ns':deadline,
                    'armed':vm.get('virtual-deadline-armed'),'fired':vm.get('virtual-deadline-fired'),
                    'fired_ns':vm.get('virtual-deadline-fired-ns')})
            time.sleep(.001)
        actual=vm.get('virtual-time-ns')
        assert vm.get('virtual-deadline-ns')==deadline
        assert vm.get('virtual-deadline-armed') is False
        assert vm.get('virtual-deadline-fired') is True
        assert vm.get('virtual-deadline-stop-ns')==actual
        time.sleep(.002);assert vm.get('virtual-time-ns')==actual
        assert actual>=deadline,(actual,deadline)
        samples.append(actual-deadline)
        callback_overshoots.append(vm.get('virtual-deadline-fired-ns')-deadline)
        if actual-deadline > 5000000:
            raise AssertionError({'error':'unchanged 5ms bound exceeded','iteration':iteration,
                                  'actual_ns':actual,'requested_ns':deadline,
                                  'fired_ns':vm.get('virtual-deadline-fired-ns')})
    # A running VM must reject mutation, even cancellation.
    vm.set('virtual-deadline-ns',vm.get('virtual-time-ns')+1000000000)
    vm.call('cont');vm.set('virtual-deadline-ns',0,error=True);vm.call('stop')
    vm.set('virtual-deadline-ns',vm.get('virtual-time-ns'),error=True)
    epoch=vm.get('virtual-clock-epoch')
    vm.call('cont')
    vm.call('system_reset')
    limit=time.monotonic()+3
    while vm.get('virtual-clock-epoch')==epoch:
        if time.monotonic()>limit:raise AssertionError('Reset epoch did not advance')
    assert vm.get('virtual-clock-epoch')==epoch+1
    assert vm.call('query-status')['running'] is False
    reset_q=vm.get('virtual-time-ns');time.sleep(.01)
    assert vm.get('virtual-time-ns')==reset_q
    assert vm.get('virtual-deadline-armed') is False
    assert vm.get('virtual-deadline-fired') is False
    assert vm.get('virtual-deadline-ns')==0
    assert vm.get('virtual-deadline-stop-ns')==-1
    print(json.dumps({'diagnostic_only':True,'icount_shift':ICOUNT_SHIFT,
                      'instruction_time_assumption_ns':None if ICOUNT_SHIFT is None else 1<<ICOUNT_SHIFT,
                      'iterations':options.iterations,'quantum_ns':options.quantum_ns,
                      'max_callback_overshoot_ns':max(callback_overshoots),
                      'wall_seconds':time.monotonic()-started,
                      'overshoot_ns':samples,
                      'max_overshoot_ns':max(samples),'unchanged_bound_ns':5000000},indent=2))
    assert max(samples)<=5000000,'Observed host dispatch exceeded unchanged 5ms bound'
finally:vm.close()
