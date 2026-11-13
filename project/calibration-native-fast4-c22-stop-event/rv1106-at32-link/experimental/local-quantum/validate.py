"""Fail-closed comparison. A differing event trace is not silently normalized."""
import pathlib,csv,json,sys
p=pathlib.Path(sys.argv[1]);summary={};passed=True
for board,phase in [('main',1),('motor',3),('nozzle',7)]:
 a=list(csv.reader((p/'baseline'/f'{board}-ordering.csv').open()));b=list(csv.reader((p/'local'/f'{board}-ordering.csv').open()))
 def order(rows,kind):return [(int(t),int(v)) for t,k,v in rows if k==kind]
 timers=order(b,'timer');errors=[t-(phase+(v-1)*31)*1000 for t,v in timers]
 first=next(({'index':i,'baseline':x,'local':y} for i,(x,y) in enumerate(zip(a,b)) if x!=y),None)
 au=order(a,'uart');bu=order(b,'uart')
 per_source={str(src):[v for t,v in au if v>>6==src]==[v for t,v in bu if v>>6==src] for src in range(3)}
 item={'rows_baseline':len(a),'rows_local':len(b),'trace_identical':a==b,'first_difference':first,'timer_ticks':len(timers),'timer_timestamp_residual_ns':[min(errors),max(errors)],'merged_uart_order_equal':[v for t,v in au]==[v for t,v in bu],'uart_order_per_source_equal':per_source,'cpu_baseline':int((p/'baseline'/f'{board}-ordering.csv.cpu').read_text()),'cpu_local':int((p/'local'/f'{board}-ordering.csv.cpu').read_text())}
 assert item['cpu_baseline']==item['cpu_local']>0
 # Comparator negative controls: swapping distinct records and dropping one must be rejected.
 altered=[list(x) for x in a];idx=next(i for i in range(len(a)-1) if a[i]!=a[i+1]);altered[idx],altered[idx+1]=altered[idx+1],altered[idx]
 assert altered!=a and a[:-1]!=a
 item['injected_reorder_and_drop_detected']=True
 summary[board]=item;passed &= a==b
for mode in ['baseline','local']:
 r=json.loads((p/mode/'lockstep-smoke.json').read_text());assert r['error'] is None and r['transitions']==200 and r['max_measured_qemu_lead_ns']<=5000000 and r['max_measured_qemu_lag_ns']<=1000000
result={'correctness_passed':passed,'native_integration_allowed':False,'results':summary,'note':'Timestamp differences are observed machine elapsed time, not proof of device frequency mutation. Source frequencies remain unchanged.'}
(p/'validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if not passed:raise SystemExit(1)
