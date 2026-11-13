"""Explicit c17-only production GPIO/ODE composition. No fixture host or stimulus."""
from pathlib import Path
import hashlib,json
from run_limits import RunLimits
PROFILE='rigid-xy39-mainY-nozzleX-proper-rotation-v1'
REL='printer-shared-mcu/experimental/native-dual-lis'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def add_arguments(p):
 p.add_argument("--lis-run-limit-seconds",type=int,default=None,help="Explicit finite absolute shared-time contract; native LIS only")
 p.add_argument('--lis-profile',choices=['none',PROFILE],default='none',help='Explicit hypothetical rigid motor-source LIS pair; no physical resonance accuracy claim')
def validate(root,a):
 if getattr(a,'lis_run_limit_seconds',None) is not None:
  RunLimits(a.lis_run_limit_seconds)
  if a.lis_profile=='none':raise ValueError('LIS run limit requires explicit LIS profile')
 if a.lis_profile=='none':return
 if a.lis_profile!=PROFILE or root.name!='calibration-native-fast4-c22-stop-event' or not a.shared_mcus or a.motor_plant!='electromechanical-driver' or not a.clock_lockstep:
  raise ValueError('Explicit c17 shared electromechanical lockstep sensor profile required')
def select(root,generated,a):
 validate(root,a)
 if a.lis_profile=='none':return None
 limits=RunLimits(719 if getattr(a,'lis_run_limit_seconds',None) is None else a.lis_run_limit_seconds)
 source=root/REL;pins=json.loads((source/'SOURCE-PINS.json').read_text())
 for rel,h in pins.items():
  p=source/rel
  if p.is_symlink() or sha(p)!=h:raise ValueError('Pinned LIS source changed: '+rel)
 manifest_path=generated/'manifest.json';manifest=json.loads(manifest_path.read_text())
 extra=generated/'native-dual-lis';extra.mkdir()
 paths=[]
 for board,ns in [('main','PrinterMain'),('nozzle','PrinterNozzle')]:
  target=generated/board/'peripherals/AT32F403A_IO.cs'
  # Exactly original namespace-isolated type is replaced before it is compiled.
  original=root/('at32-renode' if board=='main' else 'nozzle-renode')/'peripherals/AT32F403A_IO.cs'
  expected=original.read_text().replace('Antmicro.Renode.Peripherals.AT32','Antmicro.Renode.Peripherals.'+ns)
  if target.read_text()!=expected:raise ValueError('Unexpected GPIO owner/collision before LIS selection')
  before=sha(target);target.write_bytes((source/board/'AT32F403A_IO.cs').read_bytes())
  record=next(x for x in manifest if x['generated']==str(target.relative_to(generated)))
  record.update(source=REL+'/'+board+'/AT32F403A_IO.cs',source_sha256=sha(source/board/'AT32F403A_IO.cs'),before_selection_sha256=before,generated_sha256=sha(target),experimental_lis_profile=PROFILE,transformation='reviewed postcommit/reset event hook; private namespace retained')
  bridge=extra/(board+'-GpioMode3Lis2dw12Bridge.cs');bridge.write_bytes((source/board/'GpioMode3Lis2dw12Bridge.cs').read_bytes());paths.append(bridge)
  manifest.append(dict(board=board,source=REL+'/'+board+'/GpioMode3Lis2dw12Bridge.cs',source_sha256=sha(bridge),generated=str(bridge.relative_to(generated)),generated_sha256=sha(bridge),experimental_lis_profile=PROFILE))
 for name in ['TimedLis2dw12CrossBoard.cs','RigidTranslationConfiguration.cs','Tmr8PublicSnapshotPublisher.cs','PublishedSnapshotAccelerationInput.cs','DualBoardSensorBinding.cs','BoundedStatusRunLimits.cs','NativeDualSensorAttachment.cs']:
  dest=extra/name;dest.write_bytes((source/name).read_bytes());paths.append(dest)
  manifest.append(dict(board='shared',source=REL+'/'+name,source_sha256=sha(source/name),generated=str(dest.relative_to(generated)),generated_sha256=sha(dest),experimental_lis_profile=PROFILE))
 manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
 profile={'schema':1,'run_limits':limits.record(),'profile':PROFILE,'attachment_planned':True,'attachment_proven':False,'native_acquisition_proven':False,'physical_resonance_fidelity_proven':False,'mapping':json.loads((source/'MECHANICAL-HYPOTHESIS.json').read_text()),'source_pins':pins,'pins_sha256':sha(source/'SOURCE-PINS.json'),'transport':'original Linux UART -> original MCU firmware -> PB12/PB13/PB15/PB14 GPIO mode3; separate main/nozzle namespaces','source':'genuine original motor TMR8 coherent post-plant snapshots only'}
 (a.log_dir/'sensor-profile.json').write_text(json.dumps(profile,indent=2)+'\n')
 lines=['mach set "main"','include '+' '.join('@'+str(p) for p in paths),f'machine LoadPlatformDescriptionFromString "nativeDualLis: SensorCrossBoard.NativeDualSensorAttachment @ sysbus {{ hypothesis: \\\"{PROFILE}\\\" }}"',f'sysbus.nativeDualLis ConfigureRunLimit {limits.stop_seconds}',f'sysbus.nativeDualLis StartStatus "{a.log_dir}/sensor-status.json"']
 return {'tail':lines,'profile':profile}
