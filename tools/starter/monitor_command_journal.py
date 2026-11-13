"""Append-only host command audit. Original Renode commands/guards unchanged."""
import json,time,threading
_installed=False
def install(out):
 global _installed
 if _installed:raise RuntimeError('journal already installed')
 import renode_stepper
 original=renode_stepper.RenodeStepper.__init__
 path=out/'monitor-commands.jsonl';lock=threading.Lock()
 def init(self,process,ack_path,send_callback,timeout=10):
  def send(data):
   # Write-ahead record: intent does not claim successful command execution.
   row={'host_monotonic_ns':time.monotonic_ns(),'event':'send_intent','bytes_utf8':data.decode('utf-8'),'scope':'host Renode monitor, not guest console'}
   with lock:
    with path.open('a') as f:f.write(json.dumps(row,separators=(',',':'))+'\n');f.flush()
   return send_callback(data)
  return original(self,process,ack_path,send,timeout)
 renode_stepper.RenodeStepper.__init__=init;_installed=True
