"""Synthetic Cortex-M requests timed by unchanged 8MHz DWT, not native firmware."""
import pathlib,struct,tempfile,os,subprocess,json,hashlib,csv
root=pathlib.Path(__file__).resolve().parents[3];base=pathlib.Path(__file__).resolve().parent
out=root/'evidence/tmc-autobaud/cpu';out.mkdir(exist_ok=True,parents=True)
def fixture(phase):
 words=[];fixups=[]
 def emit(w):words.append(w)
 def load(r,value):fixups.append((len(words),r,value));emit(0)
 load(4,0xe0001000);emit(0x2001);emit(0x6020);emit(0x3404)
 load(5,0x40010800);emit(0x2008);emit(0x60e8);load(0,0x44441444);emit(0x6028)
 data=bytes.fromhex('f50002c8')
 for i in range(41):
  load(0,1000+phase*8+i*200)
  # ldr r2,[r4]; cmp r2,r0; blo back to ldr
  emit(0x6822);emit(0x4282);emit(0xd3fc)
  if i==40:load(0,0x44444444);emit(0x6028)
  else:
   bit=i%10;level=(bit==9 or (bit>0 and data[i//10]&(1<<(bit-1))))
   emit(0x2008 if level else 0x2000);emit(0x60e8)
 load(7,0x20000000);emit(0x202a);emit(0x6038);emit(0xbf30);emit(0xe7fd)
 if len(words)%2:emit(0xbf00)
 for index,r,value in fixups:
  literal_offset=8+len(words)*2;pc=(8+index*2+4)&~3;delta=literal_offset-pc
  assert delta%4==0 and 0<=delta<=1020
  words[index]=0x4800|(r<<8)|(delta//4);words.extend([value&65535,value>>16])
 return struct.pack('<II',0x20001000,0x08000009)+struct.pack('<'+'H'*len(words),*words)
with tempfile.TemporaryDirectory(prefix='tmc-cpu-phase-') as folder:
 d=pathlib.Path(folder);(d/'home/.config').mkdir(parents=True)
 repl=d/'cpu.repl';repl.write_text('''flash: Memory.MappedMemory @ sysbus 0x08000000
    size: 0x10000
ram: Memory.MappedMemory @ sysbus 0x20000000
    size: 0x1000
nvic: IRQControllers.NVIC @ sysbus 0xE000E000
    priorityMask: 0xF0
    systickFrequency: 8000000
    IRQ -> cpu@0
cpu: CPU.CortexM @ sysbus
    cpuType: "cortex-m3"
    nvic: nvic
dwt: AT32.AT32DWT @ sysbus 0xE0001000
    frequency: 8000000
gpio: AT32.AT32GPIO @ sysbus 0x40010800
tmc: Nozzle.VirtualNozzleTmc2209Autobaud @ sysbus
    port: gpio
observer: NozzleDiagnostics.PassiveAutobaudObserver @ sysbus
    port: gpio
    tmc: tmc
gpio:
    3 -> tmc@0
''')
 lines=[f'include @{root}/nozzle-renode/peripherals/{n}' for n in ['AT32F403A_IO.cs','AT32F403A_DWT.cs']]+[f'include @{base}/VirtualNozzleTmc2209Autobaud.cs',f'include @{base}/PassiveAutobaudObserver.cs','emulation SetGlobalQuantum "0.00001"']
 fixtures=[]
 for phase in range(10):
  f=out/f'cpu-phase-{phase}.bin';f.write_bytes(fixture(phase));fixtures.append({'phase_us':phase,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
  lines += [f'mach create "phase{phase}"',f'machine LoadPlatformDescription @{repl}','cpu PerformanceInMips 8',f'sysbus LoadBinary @{f} 0x08000000','cpu VectorTableOffset 0x08000000','emulation RunFor "0.004"',f'sysbus.observer WriteCsv "{out}/cpu-phase-{phase}.csv"','sysbus ReadDoubleWord 0x20000000','sysbus.tmc Reads','sysbus.tmc RejectedFrames','sysbus.tmc LastReply','mach clear']
 lines += ['quit'];script=d/'test.resc';script.write_text('\n'.join(lines)+'\n')
 env=dict(os.environ,HOME=str(d/'home'),XDG_CONFIG_HOME=str(d/'home/.config'),TMPDIR=str(d))
 r=subprocess.run([str(root/'at32-runtime/renode_1.17.0-portable/renode'),'--disable-gui','--console',str(script)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=60)
 (out/'cpu-phase.log').write_text(r.stdout)
 assert r.returncode==0,r.stdout[-3000:]
 reports=[]
 for phase in range(10):
  rows=list(csv.DictReader((out/f'cpu-phase-{phase}.csv').open()))
  reports.append({'phase_us':phase,'rows':len(rows),'max_reads':max(int(x['reads']) for x in rows),'max_rejected':max(int(x['rejected']) for x in rows),'last_reply':rows[-1]['last_reply']})
 (out/'cpu-phase-report.json').write_text(json.dumps({'fixture_type':'synthetic Cortex-M DWT-paced GPIO request; not native firmware receive verification','fixtures':fixtures,'results':reports},indent=2)+'\n');print(json.dumps(reports))
