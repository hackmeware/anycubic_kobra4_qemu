import pathlib,csv,json,bisect
root=pathlib.Path(__file__).resolve().parents[3];out=pathlib.Path(__import__('os').environ.get('RESULT_DIRECTORY',str(root/'evidence/gpio-time-sync/cpu')))
def crc(data):
 v=0
 for b in data:
  for i in range(8):v=((v<<1)^7 if (v>>7)^((b>>i)&1) else v<<1)&255
 return v
reports=[]
for phase in range(10):
 rows=list(csv.DictReader((out/f'cpu-phase-{phase}.csv').open()));edges=[r for r in rows if r['event']=='edge'];response=[r for r in edges if int(r['mode'])&3==0 and int(r['reads'])>0]
 if not response or response[0]['level']!='0':
  reports.append({'phase_us':phase,'passed':False,'error':'No reply waveform','max_reads':max(int(x['reads']) for x in rows),'max_rejected':max(int(x['rejected']) for x in rows)});continue
 times=[int(r['clock_ns']) for r in response];levels=[int(r['level']) for r in response];start=times[0]
 req_edges=[r for r in edges if int(r['mode'])&3]
 bit=(int(req_edges[4]['clock_ns'])-int(req_edges[0]['clock_ns']))/4
 def at(t):return levels[bisect.bisect_right(times,t)-1]
 data=[]
 for byte in range(8):
  t=start+byte*10*bit
  assert at(t+bit/2)==0 and at(t+9.5*bit)==1,(phase,byte,'start/stop')
  data.append(sum(at(t+1.5*bit+index*bit)<<index for index in range(8)))
 assert data[:3]==[5,255,2] and crc(data[:-1])==data[-1],(phase,data)
 req=[int(r['clock_ns']) for r in edges if int(r['mode'])&3]
 first=req[0];jitter=max(abs(t-(first+round((t-first)/25000)*25000)) for t in req)
 assert max(int(r['reads']) for r in rows)==1 and max(int(r['rejected']) for r in rows)==0
 reports.append({'phase_us':phase,'passed':True,'reply_bytes':bytes(data).hex(),'request_grid_max_error_ns':jitter,'request_start_ns':first,'reply_start_ns':start,'turnaround_from_expected_request_end_ns':start-(first+1000000)})
assert (out/'cpu-phase.log').read_text().count('0x0000002A')==10,'CPU completion markers missing'
(out/'cpu-edge-analysis.json').write_text(json.dumps({'passed':all(r['passed'] for r in reports),'cpu_completion_markers':10,'results':reports},indent=2)+'\n');print(json.dumps(reports))

if not all(r['passed'] for r in reports):raise SystemExit('CPU phase regression failed; candidate not integration-ready')
