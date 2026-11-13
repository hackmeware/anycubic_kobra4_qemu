"""Fast stopped-export receipt checks; complete GPIO byte/row audit is separate and mandatory."""
import json,os,stat

def read(path):
 fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as f:
  st=os.fstat(f.fileno())
  if not stat.S_ISREG(st.st_mode) or st.st_size>65536:raise ValueError('Receipt not bounded regular')
  return json.load(f)
def assess(run,here):
 plan=read(here/'gpio-capture-budget.json');results={}
 for name,budget in plan['ports'].items():
  status=read(run/(name+'.status.json'));st=(run/name).stat(follow_symlinks=False)
  if not stat.S_ISREG(st.st_mode) or status.get('enabled') is not False or status.get('capacity_reached') is not False or status.get('dropped_rows')!=0 or status.get('last_error')!='':raise ValueError('Incomplete GPIO receipt:'+name)
  if status.get('maximum_rows')!=budget['maximum_rows'] or status.get('maximum_bytes')!=budget['maximum_bytes'] or status.get('bytes_written')!=st.st_size or not 16<=status.get('rows_written',-1)<budget['maximum_rows']:raise ValueError('GPIO receipt size/budget mismatch:'+name)
  results[name]=status
 physical=read(run/'physical-state-status.json')
 if physical.get('stopped') is not True or physical.get('capacity_reached') is not False or physical.get('dropped_rows')!=0 or physical.get('error_count')!=0 or physical.get('last_error')!='':raise ValueError('Physical capture incomplete')
 sensor=read(run/'z-sensor-status.json')
 for key in ('dropped','provider_failures','adapter_errors','protocol_errors','scheduler_nonconvergence_errors'):
  if sensor.get(key)!=0:raise ValueError('Z sensor capture/fault:'+key)
 force=read(run/'z-force-status.json')
 return {'gpio_stopped_receipts_valid':True,'gpio_receipts':results,'physical_receipt':physical,'z_sensor_receipt':sensor,'z_force_receipt':force,
         'all_capture_streams_complete':False,'complete_streaming_final_audit_pending':True,'native_completion_claimed':False}
