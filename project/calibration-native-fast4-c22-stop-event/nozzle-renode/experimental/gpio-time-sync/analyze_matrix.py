import pathlib,json,csv,bisect,re
root=pathlib.Path(__file__).resolve().parents[3];base=root/'evidence/gpio-time-sync/matrix'
def crc(data):
 c=0
 for b in data:
  for i in range(8):c=((c<<1)^7 if (c>>7)^((b>>i)&1) else c<<1)&255
 return c
reports=[]
for folder in sorted(base.iterdir()):
 if not folder.is_dir() or not (folder/'mode.json').exists():continue
 mode=json.loads((folder/'mode.json').read_text());text=(folder/'cpu-phase.log').read_text();samples=[]
 # Every phase prints mailbox, Reads, RejectedFrames, learned span (or Reads for
 # fixed model), MMIO sync-call count and passive-check count after pausing.
 # Remove complete timestamped logger records that can interleave monitor tokens.
 # Preserve raw logs; refuse analysis unless exactly six values per phase remain.
 text=re.sub(r'\[\d{2}:\d{2}:\d{2}\.\d+\] \[(?:INFO|WARNING)\] [^\n]*\n','',text)
 values=[int(x,16) for x in re.findall(r'^0x([0-9A-Fa-f]+)\s*$',text,re.M)]
 assert len(values)==60,(folder,len(values))
 for phase in range(10):
  v=values[phase*6:phase*6+6];assert v[0]==42
  rows=list(csv.DictReader((folder/f'cpu-phase-{phase}.csv').open()));edges=[r for r in rows if r['event']=='edge'];req=[r for r in edges if int(r['mode'])&3]
  sync_edges=[int(r['clock_ns']) for r in req[:5]];first=sync_edges[0]
  falls=[int(r['clock_ns']) for r in req if r['level']=='0'];byte_starts=[]
  for i in range(4):
   target=first+i*250000;t=min(falls,key=lambda x:abs(x-target))
   byte_starts.append(t if abs(t-target)<=12500 else None)
  reply=[r for r in edges if not int(r['mode'])&3 and int(r['reads'])>0]
  sample={'phase_us':phase,'reads':v[1],'rejected':v[2],'final_model_sync_span_ns':v[3] if mode['model']=='autobaud' else None,'mmio_sync_calls':v[4],'passive_read_checks':v[5],
   'observed_first_sync_edges_ns':sync_edges,'observed_sync_span_ns':sync_edges[4]-sync_edges[0],
   'byte_start_edges_ns':byte_starts,'byte_start_detection':'Nearest falling edge to nominal250us byte grid within12.5us; null if ambiguous/outside window',
   'inter_byte_start_ns':[b-a if a is not None and b is not None else None for a,b in zip(byte_starts,byte_starts[1:])],
   'edge_artifact':str(folder/f'cpu-phase-{phase}.csv'),'reply_valid':False}
  if reply:
   period=v[3]/4 if mode['model']=='autobaud' else 25000
   times=[int(r['clock_ns']) for r in reply];levels=[int(r['level']) for r in reply];start=times[0]
   def at(t):return levels[bisect.bisect_right(times,t)-1]
   decoded=[];bad=[]
   for byte in range(8):
    t=start+byte*10*period
    if at(t+period/2)!=0 or at(t+9.5*period)!=1:bad.append(byte)
    decoded.append(sum(at(t+(1.5+i)*period)<<i for i in range(8)))
   sample.update(reply_bytes=bytes(decoded).hex(),bad_framing_bytes=bad,reply_valid=not bad and decoded[:3]==[5,255,2] and crc(decoded[:-1])==decoded[-1])
  samples.append(sample)
 report={'mode':mode,'passed_phases':sum(x['reply_valid'] and x['reads']==1 and x['rejected']==0 for x in samples),'total_phases':10,'phases':samples}
 reports.append(report);(folder/'matrix-phase-analysis.json').write_text(json.dumps(report,indent=2)+'\n')
 print(folder.name,report['passed_phases'],'/10',[(x['phase_us'],x['reads'],x['rejected']) for x in samples if not x['reply_valid']])
(base/'summary.json').write_text(json.dumps({'native_calibration':False,'production_changes':False,'runs':reports},indent=2)+'\n')
