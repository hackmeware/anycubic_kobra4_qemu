"""Pinned model/setup plan only. Does not launch or bypass historical gates."""
import hashlib,json,re,sys,importlib
from pathlib import Path
from run_limits import DEFAULT,RunLimits
HERE=Path(__file__).resolve().parent
MODEL_ARGS=['--shared-mcus','--motor-plant','electromechanical-driver','--motor-enable-wiring','mcu-control-only','--nozzle-tmc-model','autobaud','--thermal-profile','synthetic-cartridge-4x','--lis-profile','rigid-xy39-mainY-nozzleX-proper-rotation-v1','--z-probe-profile','synthetic-functional','--clock-coupled','--clock-source','qom-deadline','--clock-lockstep','--qemu-icount-shift','0','--clock-client','scalar','--renode-bootstrap','legacy','--renode-host-jit','default','--final-export-transport','include-file','--trace-homing-gpio','--assumed-xy-diag-cable']
Z={'bed-relative-mm':'-10','opposite-stop-relative-mm':'252','bed-side':'minimum','stiffness-n-per-mm':'20','damping-ns-per-mm':'0.05','baseline-counts':'0','counts-per-n':'10000','signal-polarity':'1','history-capacity':'4096','query-trace-rows':'1000000','sensor-trace-rows':'2000000'}
def safe(p):
 p=Path(p).resolve()
 if any(c.isspace() or c in '\"@${}' for c in str(p)):raise ValueError('Unsafe path')
 return p

def plan(root,run,limits=DEFAULT,thermal_rate=1):
 if type(thermal_rate) is not int or thermal_rate not in (1,4): raise ValueError("Explicit synthetic thermal rate must be 1 or 4")
 if not isinstance(limits,RunLimits):raise ValueError("Validated run limits required")
 root=safe(root);run=safe(run)
 if root.name!='calibration-native-fast4-c22-stop-event':raise ValueError('Original profile basename required')
 # Existing component gate is used unchanged from a fully staged project.
 sys.path.insert(0,str(root/'rv1106-at32-link/scripts'))
 module=importlib.import_module('pid_thermal_profile_selection')
 if Path(module.__file__).resolve()!=root/'rv1106-at32-link/scripts/pid_thermal_profile_selection.py':raise ValueError('Wrong imported helper root')
 hashes=module.verify_sources(root)
 commands={name:module.render(name,root,run) for name in ['main-setup','motor-setup','nozzle-setup','main-final','nozzle-final']}
 args=list(MODEL_ARGS)+["--lis-run-limit-seconds",str(limits.stop_seconds)]
 if thermal_rate==4:
  import rate4_thermal_profile
  rate4_thermal_profile.verify(root)
  args[args.index("--thermal-profile")+1]=rate4_thermal_profile.PROFILE
 for key,value in Z.items():args+=['--z-'+key,value]
 return {'thermal_rate_factor':thermal_rate,'run_limits':limits.record(),'model_arguments':args,'commands':commands,'verified_component_hashes':hashes,'synthetic':True,'physical_calibration_claim':False,'launch_performed':False,'historical_execution_manifest_validated':False,'requires':'Integrate exact command files, current runtime/firmware pins, fresh run supervision, original fault review and explicit bounded shared-clock contract. Native UI/touch calibration sequence is not launched by this plan.'}
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--run',required=True);a=p.parse_args();print(json.dumps(plan(a.root,a.run),indent=2))
