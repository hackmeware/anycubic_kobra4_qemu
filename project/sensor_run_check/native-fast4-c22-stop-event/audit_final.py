#!/usr/bin/env python3
"""Read-only full GPIO audit after the guarded native owner has exited. No completion invention."""
from pathlib import Path
import hashlib,json,subprocess,sys
E=Path(__file__).resolve().parent;W=E.parents[1];P=W/'calibration-native-fast4-c22-stop-event';R=P/'rv1106-at32-link/experimental/native-ui-resonance';N='native-fast4-86400s-c23'
if __name__=='__main__':
 if not (E/'run-c23/owner-watch-final.json').is_file():raise ValueError('Wait for owner watch terminal evidence')
 terminal=json.loads((E/'run-c23/owner-watch-final.json').read_text())
 if type(terminal.get('owner_exit_code')) is not int or terminal.get('owner_process_exited') is not True or terminal.get('checkpoint_cleanup_confirmed') is not True or (E/'run-c23/checkpoint-survivor.json').exists():raise ValueError('Owner or checkpoint cleanup not confirmed')
 pins=json.loads((E/'final-c22-pins.json').read_text())
 for name in ('gpio_capture.py','gpio-capture-budget.json'):
  rel=str((R/name).relative_to(P))
  if hashlib.sha256((R/name).read_bytes()).hexdigest()!=pins[rel]:raise ValueError('Final audit source changed')
 out=E/'full-gpio-final-audit.json'
 with out.open('x') as f:
  result=subprocess.run([sys.executable,'-I','-B',str(R/'gpio_capture.py'),str(P/'runs'/N),str(R/'gpio-capture-budget.json')],stdout=f,stderr=subprocess.PIPE,timeout=180)
 if result.returncode:raise ValueError('Full GPIO audit failed: '+result.stderr.decode()[-2048:])
 print(json.dumps({'full_gpio_audit_passed':True,'result':str(out),'all_other_capture_streams_complete_claimed':False,'native_completion_claimed':False}))
