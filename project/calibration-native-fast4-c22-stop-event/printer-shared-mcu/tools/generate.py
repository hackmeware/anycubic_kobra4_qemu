#!/usr/bin/env python3
"""Generate namespace-isolated model copies; changes identifiers only, never firmware."""
import argparse,hashlib,json,re
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]);p.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'generated');a=p.parse_args()
manifest=[]
for board,folder,ns in [('main','at32-renode','PrinterMain'),('nozzle','nozzle-renode','PrinterNozzle'),('motor','motor-renode','PrinterMotor')]:
 src=a.root/folder;out=a.output/board
 for sub in ['peripherals','platforms','scripts']:
  for f in sorted((src/sub).glob('*')):
   if not f.is_file() or f.suffix not in ['.cs','.repl','.resc']:continue
   text=f.read_text();text=text.replace('Antmicro.Renode.Peripherals.AT32','Antmicro.Renode.Peripherals.'+ns)
   text=text.replace('Antmicro.Renode.Peripherals.Nozzle','Antmicro.Renode.Peripherals.'+ns)
   text=re.sub(r'\bAT32\.',ns+'.',text);text=re.sub(r'\bNozzle\.',ns+'.',text)
   text=re.sub(r'mach create \"[^\"]+\"', 'mach create \"'+board+'\"', text)
   # Include paths are absolute, so startup no longer depends on working directory.
   text=re.sub(r'@(peripherals|platforms|scripts)/([^\s"\n]+)',lambda m:'@'+str((out/m[1]/m[2]).resolve()),text)
   dest=out/sub/f.name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(text)
   manifest.append(dict(board=board,source=str(f.relative_to(a.root)),source_sha256=hashlib.sha256(f.read_bytes()).hexdigest(),generated=str(dest.relative_to(a.output)),generated_sha256=hashlib.sha256(dest.read_bytes()).hexdigest()))
(a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(a.output)

base=a.output.resolve()
t=(Path(__file__).resolve().parents[1]/'bootstrap.resc.in').read_text().replace('@GENERATED@',str(base))
(base/'shared-load.resc').write_text(t)
