"""Read-only comparison of passive native GPIO edges and paired UART transport."""
import pathlib,csv,json,bisect,hashlib,sys
run_name=sys.argv[1] if len(sys.argv)>1 else "native-home-x-heater"
root=pathlib.Path(__file__).resolve().parents[3]
out=root/'evidence/nozzle-uart-timing'/run_name
transport=json.loads((out/'transport.json').read_text())
p=root/'runs'/run_name/'nozzle-tmc-edges.csv'
rows=list(csv.DictReader(p.open())); requests=[]; replies=[]
for r in rows:
 if r['event']!='edge' or r['clock_ns']=='0':continue
 groups=requests if int(r['mode'])&3 else replies
 if not groups or int(r['clock_ns'])-int(groups[-1][-1]['clock_ns'])>500000:groups.append([])
 groups[-1].append(r)
idle_output_groups=[g for g in requests if len(g)==1 and g[0]['level']=='1']
requests=[g for g in requests if g not in idle_output_groups]
assert len(requests)==len(transport['transactions'])
# Reply intra-waveform high spans can exceed 500us? For this captured set none do.
expected_replies=sum(t["actual_packed_reply_length"]>0 for t in transport["transactions"])
assert len(replies)==expected_replies

def crc(data):
 c=0
 for b in data:
  for i in range(8):c=((c<<1)^7 if (c>>7)^((b>>i)&1) else c<<1)&255
 return c
results=[];ri=0
for i,(edges,t) in enumerate(zip(requests,transport['transactions'])):
 data=bytes.fromhex(t['request']['uart_hex']);expected=[];prev=1
 for j,b in enumerate(data):
  for k,v in enumerate([0]+[(b>>n)&1 for n in range(8)]+[1]):
   if v!=prev:expected.append((j*10+k,v));prev=v
 assert len(expected)==len(edges) and all(int(r['level'])==v for r,(_,v) in zip(edges,expected)),i
 start=int(edges[0]['clock_ns']);deviations=[int(r['clock_ns'])-start-bit*25000 for r,(bit,_) in zip(edges,expected)]
 starts=[int(r['clock_ns']) for r,(bit,_) in zip(edges,expected) if bit%10==0]
 result={'transaction':i,'transport':t,'request_start_ns':start,'sync_four_bit_span_ns':int(edges[4]['clock_ns'])-start,'byte_start_intervals_ns':[b-a for a,b in zip(starts,starts[1:])],'request_edge_grid_error_min_max_ns':[min(deviations),max(deviations)],'request_edges_preserve_all_expected_transitions':True,'rejected_before_after':[int(edges[0]['rejected']),int(edges[-1]['rejected'])]}
 end=int(requests[i+1][0]['clock_ns']) if i+1<len(requests) else 10**30
 if ri<len(replies) and start<int(replies[ri][0]['clock_ns'])<end:
  rep=replies[ri];ri+=1;times=[int(r['clock_ns']) for r in rep];levels=[int(r['level']) for r in rep]
  def at(ns):return levels[bisect.bisect_right(times,ns)-1]
  period=result['sync_four_bit_span_ns']/4 if run_name=='native-ready-autobaud' else 25000
  values=[];bad=[]
  for j in range(8):
   b=times[0]+j*10*period
   if at(b+period/2)!=0 or at(b+9.5*period)!=1:bad.append(j)
   values.append(sum(at(b+(1.5+k)*period)<<k for k in range(8)))
  result['reply']={'bit_period_ns':period,'start_ns':times[0],'decoded_hex':bytes(values).hex(),'bad_start_stop':bad,'crc_valid':crc(values[:-1])==values[-1],'matches_model_last_reply':bytes(values).hex()==rep[-1]['last_reply'].replace('-','').lower(),'edge_grid_max_error_ns':max(abs((n-times[0])-round((n-times[0])/period)*period) for n in times),'matches_native_received_bytes':bytes(values).hex()==t['response']['uart_hex']}
 results.append(result)
assert ri==expected_replies
report={'isolated_output_high_edges':idle_output_groups,'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'note':'clock_ns passive available-clock time, not guaranteed CPU-instruction time; waveform sampled at unchanged model 25us bit period. Ordered request transition topology exactly matches all known transport requests. No edge times adjusted.','transactions':results}
(out/'edge-analysis.json').write_text(json.dumps(report,indent=2)+'\n')
for r in results:
 if r['transport']['classification'] in ('empty_read','malformed_read') or r['rejected_before_after'][0]!=r['rejected_before_after'][1]:print(json.dumps(r))
print('Reply waveforms:',ri,'valid:',sum(bool(r.get('reply',{}).get('crc_valid')) for r in results))
