import pathlib,tempfile,os,subprocess,json
root=pathlib.Path(__file__).resolve().parents[3];base=pathlib.Path(__file__).resolve().parent
out=pathlib.Path(__import__('os').environ.get('RESULT_DIRECTORY',str(root/'evidence/gpio-time-sync')));out.mkdir(exist_ok=True,parents=True)
with tempfile.TemporaryDirectory(prefix='tmc-autobaud-') as folder:
 d=pathlib.Path(folder);(d/'home/.config').mkdir(parents=True)
 repl=d/'test.repl';repl.write_text('''gpio: AT32.AT32GPIO @ sysbus 0x40010800
tmc: Nozzle.VirtualNozzleTmc2209Autobaud @ sysbus
    port: gpio
tests: NozzleTests.AutobaudTmcTests @ sysbus 0x60000000
    tmc: tmc
    gpio: gpio
observer: NozzleDiagnostics.PassiveAutobaudObserver @ sysbus
    port: gpio
    tmc: tmc
gpio:
    3 -> tmc@0
''')
 lines=[f'include @{base}/AT32F403A_IO_Synchronized.cs']+[f'include @{base}/{n}' for n in ['VirtualNozzleTmc2209Autobaud.cs','PassiveAutobaudObserver.cs','AutobaudTmcTests.cs']]+['mach create "main"','emulation SetGlobalQuantum "'+os.environ.get('GLOBAL_QUANTUM','0.00001')+'"',f'machine LoadPlatformDescription @{repl}']
 cases=[]
 for baud in [20000,40000,50000,80000]:
  for phase in [0,3,9]:
   for fault,delay in [('none',x) for x in [0,1,2,3,14,15]]+[(x,0) for x in ['crc','address','stop','disconnect','sync']]:
    label=f'b{baud}_p{phase}_d{delay}_{fault}';cases.append({'label':label,'baud':baud,'phase_us':phase,'senddelay':delay,'fault':fault})
    lines += [f'sysbus.observer Mark "{label}"',f'sysbus.tests StartWaveform {phase} "{fault}" {baud} {delay}','emulation RunFor "0.025"','sysbus.tests CheckWaveform','sysbus.tmc LearnedSyncSpanNanoseconds']
 lines += [f'sysbus.tests WriteSummary "{out}/test-summary.json"',f'sysbus.observer WriteCsv "{out}/phase-edges.csv"','sysbus.observer Dropped','sysbus.observer PassiveReadChecks','sysbus.gpio CpuSynchronizationCalls','quit']
 script=d/'test.resc';script.write_text('\n'.join(lines)+'\n');(out/'test.resc.txt').write_text(script.read_text());(out/'cases.json').write_text(json.dumps(cases,indent=2))
 env=dict(os.environ,HOME=str(d/'home'),XDG_CONFIG_HOME=str(d/'home/.config'),TMPDIR=str(d))
 r=subprocess.run([str(root/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(script)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=75)
 (out/'phase.log').write_text(r.stdout)
 assert r.returncode==0,r.stdout[-4000:]
 assert json.loads((out/'test-summary.json').read_text())=={'positive':72,'negative':60}
 print(json.dumps({'positive_cases':72,'negative_cases':60,'production_model_modified':False}))
