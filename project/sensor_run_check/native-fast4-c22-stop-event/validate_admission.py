"""Exact independent qualification receipts required before any c19 native launch."""
from pathlib import Path
import hashlib,json
E=Path(__file__).resolve().parent;W=E.parents[1]
def require(review):
 if review.get('passed') is not True:raise ValueError('Independent combined review missing')
 for name in ('native_source_gate','original_mcu_acquisition_gate'):
  gate=review.get(name,{})
  if gate.get('qualified') is not True or gate.get('native_firmware_executed') is not True or gate.get('cleanup_verified') is not True:
   raise ValueError('Native prerequisite not qualified: '+name)
  evidence=gate.get('evidence',[])
  if not isinstance(evidence,list) or not evidence or len(evidence)>8:raise ValueError('Bounded qualification evidence required')
  for item in evidence:
   p=W/item['path']
   if p.is_symlink() or not p.resolve().is_relative_to(W/'sensor_run_check') or not p.is_file():raise ValueError('Invalid qualification evidence path')
   if hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Qualification evidence changed: '+str(p))
 if review.get('pid_values_hardware_transferable') is not False:raise ValueError('Synthetic PID disclaimer required')
 return True
if __name__=='__main__':
 require(json.loads((E/'independent-review/final-review.json').read_text()))
 print('Exact native prerequisite receipts verified; this does not launch firmware.')
