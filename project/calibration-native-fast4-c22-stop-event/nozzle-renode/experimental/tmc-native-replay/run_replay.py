"""Offline exact request-edge replay; no original firmware execution or edits."""
import csv,json,pathlib,tempfile,os,subprocess,bisect,hashlib
root=pathlib.Path(__file__).resolve().parents[3];base=pathlib.Path(__file__).resolve().parent
out=root/'evidence/tmc-native-replay';out.mkdir(exist_ok=True,parents=True)
source=root/'runs/native-xy-quantum1/nozzle-tmc-edges.csv';rows=list(csv.DictReader(source.open()))
analysis=json.loads((root/'evidence/nozzle-uart-timing/native-xy-quantum1/edge-analysis.json').read_text());transactions=analysis['transactions'];origin=transactions[0]['request_start_ns']-1000000
events=[]
for t in transactions:
 start=t['request_start_ns'];data=bytes.fromhex(t['transport']['request']['uart_hex']);length=len(data)
 end=start+sum(t['byte_start_intervals_ns'])+int(t['sync_four_bit_span_ns']*10/4)
 # Input-mode transition is unobserved in passive edge-only capture. Explicit fixture assumption.
 events.append((start-origin-1,'start'))
 req=[r for r in rows if r['event']=='edge' and int(r['mode'])&3 and start<=int(r['clock_ns'])<end]
 # Exclude later isolated host high release edge; request topology already checked by analyzer.
 for r in req:events.append((int(r['clock_ns'])-origin,r['level']))
 events.append((end-origin,'release'))
events.sort();(out/'request-events.csv').write_text(''.join(f'{n},{v}\n' for n,v in events))
for model in ['fixed','autobaud']:
 with tempfile.TemporaryDirectory(prefix='native-edge-replay-') as folder:
  d=pathlib.Path(folder);(d/'home/.config').mkdir(parents=True)
  cls='VirtualNozzleTmc2209Autobaud' if model=='autobaud' else 'VirtualNozzleTmc2209'
  observer=(base/'PassiveAutobaudObserver.cs').read_text()
  if model=='fixed':observer=observer.replace('VirtualNozzleTmc2209Autobaud','VirtualNozzleTmc2209')
  (d/'Observer.cs').write_text(observer)
  repl=d/'test.repl';repl.write_text(f'''gpio: AT32.AT32GPIO @ sysbus 0x40010800
tmc: Nozzle.{cls} @ sysbus
    port: gpio
replay: NozzleTests.RecordedRequestReplay @ sysbus
    gpio: gpio
observer: NozzleDiagnostics.PassiveAutobaudObserver @ sysbus
    port: gpio
    tmc: tmc
gpio:
    3 -> tmc@0
''')
  source_model=base/'VirtualNozzleTmc2209Autobaud.cs' if model=='autobaud' else root/'nozzle-renode/peripherals/VirtualNozzleTmc2209.cs'
  lines=[f'include @{root}/nozzle-renode/peripherals/AT32F403A_IO.cs',f'include @{source_model}',f'include @{d}/Observer.cs',f'include @{base}/RecordedRequestReplay.cs','mach create "replay"','emulation SetGlobalQuantum "0.000001"',f'machine LoadPlatformDescription @{repl}',f'sysbus.replay Load "{out}/request-events.csv"','emulation RunFor "0.2"',f'sysbus.observer WriteCsv "{out}/{model}-edges.csv"','sysbus.observer Dropped','quit']
  script=d/'run.resc';script.write_text('\n'.join(lines));(out/f'{model}.resc.txt').write_text(script.read_text())
  env=dict(os.environ,HOME=str(d/'home'),XDG_CONFIG_HOME=str(d/'home/.config'),TMPDIR=str(d))
  r=subprocess.run([str(root/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(script)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=45)
  (out/f'{model}.log').write_text(r.stdout);assert r.returncode==0,r.stdout[-3000:]
  assert (out/f'{model}-edges.csv').exists(),r.stdout[-3000:]
(out/'metadata.json').write_text(json.dumps({'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'global_quantum_us':1,'request_edges_rescaled':False,'release_assumption':'Release input at final byte start + ten learned bit periods; actual mode transition was not recorded. No CPU/native receiver in this replay.','origin_ns':origin},indent=2))
print('Recorded request replay completed for fixed and autobaud; edge validation is separate.')
