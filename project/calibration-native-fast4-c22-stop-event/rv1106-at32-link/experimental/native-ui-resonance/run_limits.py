"""One trusted, finite absolute shared-time contract. Not a wall-clock timeout."""
from dataclasses import dataclass
NS=1_000_000_000
DEFAULT_STOP_SECONDS=719
MAX_STOP_SECONDS=86400
@dataclass(frozen=True)
class RunLimits:
    stop_seconds:int=DEFAULT_STOP_SECONDS
    def __post_init__(self):
        if type(self.stop_seconds) is not int or not 1<=self.stop_seconds<=MAX_STOP_SECONDS:
            raise ValueError('shared stop seconds must be integer 1..86400')
    @property
    def stop_ns(self): return self.stop_seconds*NS
    @property
    def status_limit(self): return (self.stop_seconds+1)*100+10
    def record(self):
        return {'schema':1,'shared_stop_seconds':self.stop_seconds,'shared_stop_ns':self.stop_ns,'status_interval_ns':10_000_000,'status_write_limit':self.status_limit,'cleanup_reserve_writes':110,'maximum_shared_stop_seconds':MAX_STOP_SECONDS}
    @classmethod
    def from_record(cls,record):
        if not isinstance(record,dict) or any(type(v) is not int for v in record.values()):raise ValueError('integer run limits object required')
        limits=cls(record.get('shared_stop_seconds'))
        if record!=limits.record():raise ValueError('inconsistent run limits')
        return limits
DEFAULT=RunLimits()
