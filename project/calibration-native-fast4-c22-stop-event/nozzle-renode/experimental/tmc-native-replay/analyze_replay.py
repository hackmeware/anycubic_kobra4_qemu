import pathlib,json,csv,bisect,math
root=pathlib.Path(__file__).resolve().parents[3];out=root/'evidence/tmc-native-replay';native=json.loads((root/'evidence/nozzle-uart-timing/native-xy-quantum1/edge-analysis.json').read_text())['transactions'];meta=json.loads((out/'metadata.json').read_text())
def crc(data):
 c=0
 for b in data:
  for i in range(8):c=((c<<1)^7 if (c>>7)^((b>>i)&1) else c<<1)&255
 return c
results=[]
for model in ['fixed','autobaud']:
 rows=list(csv.DictReader((out/f'{model}-edges.csv').open()));last=rows[-1];assert (int(last['reads']),int(last['writes']),int(last['rejected']))==(19,10,0)
 for t in native:
  if 'reply' not in t:continue
  start=t['request_start_ns']-meta['origin_ns'];next_start=next((x['request_start_ns']-meta['origin_ns'] for x in native if x['transaction']==t['transaction']+1),10**20)
  edges=[r for r in rows if r['event']=='edge' and not int(r['mode'])&3 and start<int(r['clock_ns'])<next_start];assert edges and edges[0]['level']=='0'
  times=[int(r['clock_ns']) for r in edges];levels=[int(r['level']) for r in edges];period=t['sync_four_bit_span_ns']/4 if model=='autobaud' else 25000
  def at(n):return levels[bisect.bisect_right(times,n)-1]
  values=[]
  for byte in range(8):
   ns=times[0]+byte*10*period;assert at(ns+period/2)==0 and at(ns+9.5*period)==1
   values.append(sum(at(ns+(1.5+k)*period)<<k for k in range(8)))
  assert crc(values[:-1])==values[-1]
  expected=bytes.fromhex(t['reply']['decoded_hex']);assert bytes(values)==expected
  positions=[];prev=1
  for byte,v in enumerate(expected):
   for bit,level in enumerate([0]+[(v>>k)&1 for k in range(8)]+[1]):
    if level!=prev:positions.append(byte*10+bit);prev=level
  assert len(positions)==len(times),(model,t['transaction'],len(positions),len(times))
  errors=[actual-times[0]-math.ceil(pos*period) for actual,pos in zip(times,positions)]
  assert max(abs(e) for e in errors)<=1,(model,t['transaction'],errors)
  results.append({'model':model,'native_transaction':t['transaction'],'native_classification':t['transport']['classification'],'reply_period_ns':period,'edge_error_ns_min_max':[min(errors),max(errors)],'reply_hex':bytes(values).hex(),'crc_and_framing_valid':True})
(out/'validation.json').write_text(json.dumps({'passed':True,'results':results,'scope':'Offline model reply waveform validation, not native receiver verification'},indent=2))
print('PASS: both models accept29 requests,10writes/19reads/rejected0; all38reply CRC/framing and exact edge periods checked. Autobaud follows each native sync, fixed remains25us.')
