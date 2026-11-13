"""External bound on original scalar stepping; no original control files edited."""
import json
from run_limits import DEFAULT,RunLimits
LIMIT_NS=719_000_000_000  # deliberately below original 720 s contract

def guarded_step(stepper, original_step, out, amount, limits=DEFAULT):
    if not isinstance(limits,RunLimits):raise ValueError("validated RunLimits required")
    if type(amount) is not int or amount<=0 or type(stepper.time_ns) is not int or stepper.time_ns<0:raise ValueError("positive integer step and nonnegative integer shared time required")
    if stepper.time_ns+amount >= limits.stop_ns:
        (out/'stop-request').touch(exist_ok=True)
        (out/'R9-TIME-LIMIT.json').write_text(json.dumps({'limit_ns':limits.stop_ns,'run_limits':limits.record(),'before_ns':stepper.time_ns,'requested_ns':amount,'advanced':False})+'\n')
        raise RuntimeError('R9 shared virtual-time bound reached; requested step not executed')
    return original_step(amount)

def install(out, limits=DEFAULT):
    if not isinstance(limits,RunLimits):raise ValueError("validated RunLimits required")
    (out/"R9-RUN-LIMITS.json").write_text(json.dumps(limits.record())+"\n")
    import lockstep_coordinator as module
    Original=module.LockstepCoordinator
    class Bounded(Original):
        def __init__(self,qmp_client,stepper,*a,**kw):
            original_step=stepper.step
            stepper.step=lambda amount:guarded_step(stepper,original_step,out,amount,limits)
            super().__init__(qmp_client,stepper,*a,**kw)
    module.LockstepCoordinator=Bounded
