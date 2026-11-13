import pathlib,sys,json,csv,hashlib
out=pathlib.Path(sys.argv[1]);results=[];signatures=[]
for i,mode in enumerate(['parallel','serial','serial','parallel'],1):
 p=out/f'{i}-{mode}';r=json.loads((p/'benchmark.json').read_text());assert r['combined_steps']==100 and r['max_lead_ns']<=5000000 and r['max_lag_ns']<=1000000
 sig={}
 for board in ['main','motor','nozzle']:
  rows=list(csv.reader((p/f'{board}-ordering.csv').open()));bykind={k:[(int(t),int(v)) for t,kind,v in rows if kind==k] for k in ['timer','gpio','uart']}
  assert len(bykind['timer'])==1010 and [v for _,v in bykind['timer']]==list(range(1,1011))
  assert all(b[0]>=a[0] for a,b in zip(bykind['timer'],bykind['timer'][1:]))
  if board in ['main','motor']:
   assert len(bykind['uart'])>=1009 and [v for _,v in bykind['uart']]==[j%256 for j in range(1,len(bykind['uart'])+1)]
  assert int((p/f'{board}-ordering.csv.cpu').read_text())>0
  sig[board]=bykind
 results.append(r);signatures.append(sig)
(out/'comparison.json').write_text(json.dumps({'runs':results,'exact_trace_identity':all(x==signatures[0] for x in signatures),'scope':'Synthetic scheduler benchmark only; inspect any ordering difference before native integration'},indent=2))
print('ABBA checks passed; exact trace identity:',all(x==signatures[0] for x in signatures))
