"""Diagnostic two-way virtual-time stepping, not cycle-accurate calibration."""
import json
import pathlib
import threading
import time

class LockstepCoordinator:
    def __init__(self,qmp_client,stepper,output,max_lead_ns=5000000,slice_ns=1000000):
        if type(slice_ns) is not int or slice_ns<=0 or slice_ns>max_lead_ns or slice_ns%1000:
            raise ValueError('Slice must be positive whole microseconds within lead bound')
        self.qmp=qmp_client;self.stepper=stepper;self.output=pathlib.Path(output)
        self.max_lead_ns=max_lead_ns;self.slice_ns=slice_ns
        self.error=None;self.samples=[];self.transitions=0;self.max_lead=0;self.max_lag=0
        self.started=time.monotonic();self.stopped=threading.Event();self.closed=False
        self.qmp.call('stop')
        self.q0=self._paused_now('QEMU did not pause before lockstep baseline');self.r0=stepper.time_ns;self.previous_q=self.q0
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def _paused_now(self,message):
        aggregate=getattr(self.qmp,'paused_now',None)
        if callable(aggregate):return aggregate()
        if self.qmp.call('query-status').get('running') is not False:
            raise RuntimeError(message)
        return self.qmp.now()

    def _check(self,q,r,lag_bound):
        skew=(q-self.q0)-(r-self.r0)
        self.max_lead=max(self.max_lead,skew);self.max_lag=max(self.max_lag,-skew)
        if skew>self.max_lead_ns:
            raise RuntimeError(f'QEMU exceeded unchanged virtual lead bound: {skew}ns')
        if -skew>lag_bound:
            raise RuntimeError(f'QEMU exceeded lockstep lag bound: {-skew}ns')
        return skew

    def run(self):
        try:
            while not self.stopped.is_set():
                # Never let Renode run a second slice until QEMU has caught up.
                q=self._paused_now('QEMU unexpectedly running at lockstep boundary')
                if q!=self.previous_q:raise RuntimeError('Paused QEMU clock changed outside coordinator')
                r=self.stepper.step(self.slice_ns)
                self._check(q,r,self.slice_ns)
                target=self.q0+(r-self.r0)
                if target<=q:raise RuntimeError('No positive QEMU catch-up slice remains')
                q=self.qmp.run_until(target)
                self.transitions+=2
                if q<self.previous_q:raise RuntimeError('QEMU clock regressed')
                skew=self._check(q,r,0)
                self.previous_q=q
                self.samples.append({'wall_s':time.monotonic()-self.started,
                    'step_id':self.stepper.step_id,'qemu_delta_ns':q-self.q0,
                    'renode_delta_ns':r-self.r0,'measured_skew_ns':skew,
                    'last_deadline_ns':getattr(self.qmp,'last_deadline',target),
                    'last_callback_ns':getattr(self.qmp,'last_fired',None),
                    'last_stop_ns':getattr(self.qmp,'last_stop',q),'qemu_running':False})
        except Exception as exc:
            self.error=str(exc)
        finally:
            try:self.qmp.call('stop')
            except Exception as exc:self.error=self.error or ('Unable to stop QEMU: '+str(exc))
            try:self.stepper.pause(force=self.stepper.failed)
            except Exception as exc:self.error=self.error or ('Unable to pause Renode: '+str(exc))

    def close(self):
        if self.closed:return
        self.closed=True;self.stopped.set()
        # All step and QMP reads are separately bounded; never close a shared
        # stream while the worker still owns it.
        self.thread.join(self.stepper.timeout+20*getattr(self.qmp,'timeout',3)+2)
        if self.thread.is_alive():
            self.error=self.error or 'Lockstep worker did not finish bounded shutdown'
            self.stepper.pause(force=True)
        report={'mode':'bidirectional actual virtual-time lockstep','event_mode':True,
            'clock_frequency_modified':False,'physical_cycle_accuracy_claimed':False,
            'slice_ns':self.slice_ns,'configured_max_lead_ns':self.max_lead_ns,
            'configured_max_intermediate_lag_ns':self.slice_ns,
            'max_measured_qemu_lead_ns':self.max_lead,'max_measured_qemu_lag_ns':self.max_lag,
            'transitions':self.transitions,'wall_seconds':time.monotonic()-self.started,
            'error':self.error,'samples':self.samples}
        self.output.write_text(json.dumps(report,separators=(',', ':'))+'\n')
        if not self.thread.is_alive():self.qmp.close()
