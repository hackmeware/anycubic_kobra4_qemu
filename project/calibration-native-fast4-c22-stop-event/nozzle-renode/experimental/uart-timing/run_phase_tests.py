import pathlib,tempfile,os,subprocess,json
root=pathlib.Path(__file__).resolve().parents[3]
base=pathlib.Path(__file__).resolve().parent
out=root/'evidence/nozzle-uart-timing';out.mkdir(exist_ok=True,parents=True)
with tempfile.TemporaryDirectory(prefix='tmc-phase-') as folder:
 d=pathlib.Path(folder);(d/'home/.config').mkdir(parents=True)
 repl=d/'test.repl';repl.write_text('''gpio: AT32.AT32GPIO @ sysbus 0x40010800
tmc: Nozzle.VirtualNozzleTmc2209 @ sysbus
    port: gpio
tests: NozzleTests.PhaseTmcTests @ sysbus 0x60000000
    tmc: tmc
    gpio: gpio
observer: NozzleDiagnostics.PassiveTmcTimingObserver @ sysbus
    port: gpio
    tmc: tmc
gpio:
    3 -> tmc@0
''')
 lines=[f'include @{root}/nozzle-renode/peripherals/AT32F403A_IO.cs',f'include @{root}/nozzle-renode/peripherals/VirtualNozzleTmc2209.cs',f'include @{base}/PassiveTmcTimingObserver.cs',f'include @{base}/PhaseTmcTests.cs','mach create "main"','emulation SetGlobalQuantum "0.00001"',f'machine LoadPlatformDescription @{repl}']
 for phase in range(10):
  for fault in ['none','crc','address','stop','disconnect']:
   label=f'phase_{phase}_{fault}';lines += [f'sysbus.observer Mark "{label}"',f'sysbus.tests StartWaveform {phase} "{fault}"','emulation RunFor "0.005"','sysbus.tests CheckWaveform']
 lines += [f'sysbus.observer WriteCsv "{out}/ideal-phase-edges.csv"','sysbus.observer Dropped','quit']
 script=d/'test.resc';script.write_text('\n'.join(lines)+'\n')
 env=dict(os.environ,HOME=str(d/'home'),XDG_CONFIG_HOME=str(d/'home/.config'),TMPDIR=str(d))
 result=subprocess.run([str(root/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(script)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=60)
 (out/'ideal-phase.log').write_text(result.stdout)
 assert result.returncode==0,result.stdout[-4000:]
 assert result.stdout.count('NOZZLE GPIO WAVEFORM PASS')==10,result.stdout[-4000:]
 assert result.stdout.count('NEGATIVE PASS:')==40,result.stdout[-4000:]
 print(json.dumps({'ideal_phase_cases':10,'negative_phase_cases':40,'cpu_driven':False,'production_model_modified':False}))
