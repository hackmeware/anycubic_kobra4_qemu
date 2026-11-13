"""Dedicated serialized lockstep sender; use only while live peer input is banned.

RenodeStepper selects main itself before RunFor/PublishStep. This sender must
share the launcher's peer-write lock; it does not add duplicate monitor commands.
"""
class SerializedStepSender:
    def __init__(self,process,write_lock):
        self.process=process
        self.write_lock=write_lock
    def __call__(self,data):
        if not isinstance(data,bytes):raise TypeError('Monitor commands must be bytes')
        with self.write_lock:
            if self.process.poll() is not None:raise RuntimeError('Renode process exited')
            self.process.stdin.write(data)
            self.process.stdin.flush()
