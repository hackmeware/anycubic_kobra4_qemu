"""Read-only evidence gate. Counters prove model activity, never native host completion."""
from run_limits import DEFAULT,RunLimits
PROFILE='rigid-xy39-mainY-nozzleX-proper-rotation-v1'
def check(s,now,limits=DEFAULT):
 if not isinstance(limits,RunLimits):raise ValueError("validated RunLimits required")
 advertised=s.get("run_limits")
 if advertised is not None and RunLimits.from_record(advertised)!=limits:raise ValueError("LIS run contract mismatch")
 if limits!=DEFAULT and advertised is None:raise ValueError("Explicit long-run status contract required")
 if (s.get('schema')!=1 or s.get('source')!='native-dual-lis-public-status' or s.get('hypothesis')!=PROFILE or s.get('disposed') is not False or s.get('fault') is not None):
  raise ValueError('LIS attachment identity/disposal/fault: '+str(s.get('fault')))
 for k in ('virtual_time_ns','sequence','source_captures','published_pairs','superseded_pairs'):
  if type(s.get(k)) is not int or s[k]<0:raise ValueError('Invalid LIS status counter: '+k)
 if s['sequence']<1 or s['sequence']>limits.status_limit:raise ValueError('LIS status publication bound')
 if now is not None and not 0<=now-s['virtual_time_ns']<=250000000:raise ValueError('Unconfirmed/stale LIS status')
 for board in ('main','nozzle'):
  b=s.get(board,{})
  if b.get('input_fault') is not None or b.get('sensor_fault') is not None:raise ValueError('LIS '+board+' acquisition/source fault: '+str(b))
  if type(b.get('ready')) is not bool or type(b.get('sampling')) is not bool:raise ValueError('Malformed LIS readiness')
  for k in ('generated_samples','consumed_source_samples','last_sample_ns','last_acquisition_ns','last_source_ns','previous_source_ns','source_age_ns','derivative_interval_ns','last_publication_ns','fifo_count','overwritten_samples','ctrl1','ctrl2','ctrl6','fifo_ctrl'):
   if type(b.get(k)) is not int or b[k]<0:raise ValueError('Invalid LIS board counter: '+k)
  if b['fifo_count']>32:raise ValueError('LIS FIFO capacity violated')
  if b['consumed_source_samples']:
   if not (b['previous_source_ns']<b['last_source_ns']<=b['last_publication_ns']<=b['last_acquisition_ns']<=s['virtual_time_ns'] and b['source_age_ns']==b['last_acquisition_ns']-b['last_source_ns']<625000 and b['derivative_interval_ns']==b['last_source_ns']-b['previous_source_ns']<=625000):raise ValueError('LIS acquisition causal/freshness contract violated')
 if s.get('original_host_acquisition_proven') is not False or s.get('calibration_complete') is not False or s.get('physical_fidelity_proven') is not False:raise ValueError('Unsupported LIS completion/physical claim')
 return bool(s['main']['ready'] and s['nozzle']['ready'] and s['source_captures']>=2 and s['published_pairs']>=1)

def assess_final(run,thermal,expected_epoch,limits=DEFAULT):
 """Final public model/lifecycle proof only; native sensor stop remains separate."""
 import json,hashlib
 from pathlib import Path
 read=lambda n:json.loads(thermal.read_regular(run/n,maximum=65536))
 status=read('sensor-final.json');step=read('renode-step.json');cleanup=read('sensor-final.json.cleanup.json')
 if step.get('schema')!=1 or not isinstance(expected_epoch,str) or not expected_epoch or step.get('epoch')!=expected_epoch or type(step.get('step_id')) is not int or step['step_id']<0 or step.get('source')!='renode-shared-mcu-step' or step.get('paused') is not True or step.get('enabled') is not True or step.get('time_went_backwards') is not False:raise ValueError('Sensor final needs confirmed paused boundary')
 now=step.get('virtual_time_ns')
 if type(now) is not int or now<0 or now%1000 or status.get('virtual_time_ns')!=now:raise ValueError('Sensor final is not at exact confirmed paused boundary')
 check(status,now,limits)
 expected={'schema':1,'disposed':True,'binding_disposed':True,'publisher_connected':False,'publisher_subscribed':False,'main_input_subscribed':False,'nozzle_input_subscribed':False}
 if cleanup!=expected:raise ValueError('Incomplete sensor binding cleanup receipt')
 ack_raw=thermal.read_regular(run/'final-export.json',maximum=65536)
 captured={}
 ack=thermal.verify_final_ack(ack_raw,run,captured)
 found=0
 for index,b in enumerate(json.loads(ack_raw)['batches']):
  rel=Path(b.get('command_file',''))
  if rel.is_absolute() or len(rel.parts)!=2 or rel.parts[0]!='final-export-batches' or '..' in rel.parts:raise ValueError('Invalid final batch command path')
  raw=thermal.read_regular(run/rel,maximum=1024*1024)
  if hashlib.sha256(raw).hexdigest()!=b.get('command_file_sha256'):raise ValueError('Final batch source changed')
  exact='sysbus.nativeDualLis Close "'+str(run/'sensor-final.json')+'"'
  lines=raw.decode().splitlines()
  if exact in lines:
   if b.get('board')!='main' or lines.count(exact)!=1:raise ValueError('Wrong/duplicate sensor close')
   begin_command='echo \"LIS_SENSOR_FINAL_BEGIN\"';end_command='echo \"LIS_SENSOR_FINAL_END\"'
   if lines.count(begin_command)!=1 or lines.count(end_command)!=1 or not lines.index(begin_command)+1==lines.index(exact)==lines.index(end_command)-1:raise ValueError('Sensor close outside exact command envelope')
   chunk=captured['final-export-window-'+str(index).zfill(3)+'.bin']
   response=[thermal.ANSI.sub(b'',line).strip(b'\r') for line in chunk.split(b'\n')]
   response=response[response.index(b['begin_marker'].encode())+1:response.index(b['end_marker'].encode())]
   if response.count(b'LIS_SENSOR_FINAL_BEGIN')!=1 or response.count(b'LIS_SENSOR_FINAL_END')!=1 or response.index(b'LIS_SENSOR_FINAL_BEGIN')>=response.index(b'LIS_SENSOR_FINAL_END'):raise ValueError('Sensor final acknowledgement envelope missing')
   found+=1
 if found!=1:raise ValueError('Exactly one acknowledged sensor close required')
 return {'passed':True,'paused_source_ns':now,'status':status,'cleanup':cleanup,'final_ack':ack,'native_sensor_stop_proven':False,'native_host_acquisition_proven':False,'full_calibration_complete':False,'scope':'Public model acquisition counters and exact disposed binding only; separate original host/native workflow proof required'}
