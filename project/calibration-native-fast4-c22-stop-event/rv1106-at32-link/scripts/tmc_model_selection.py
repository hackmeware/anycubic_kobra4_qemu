"""Explicit generated-copy selection; production model and firmware stay unchanged."""
import hashlib,json,re

def select(root,generated,choice):
 if choice not in ('fixed','autobaud'):raise ValueError('Unknown TMC model')
 if choice=='fixed':return {'selection':'fixed','experimental':False}
 source=root/'nozzle-renode/experimental/tmc-native-replay/VirtualNozzleTmc2209Autobaud.cs'
 dest=generated/'nozzle/peripherals/VirtualNozzleTmc2209.cs'
 text=source.read_text().replace('VirtualNozzleTmc2209Autobaud','VirtualNozzleTmc2209')
 for ns in ('AT32','Nozzle'):text=text.replace('Antmicro.Renode.Peripherals.'+ns,'Antmicro.Renode.Peripherals.PrinterNozzle');text=re.sub(r'\b'+ns+r'\.','PrinterNozzle.',text)
 dest.write_text(text)
 info={'selection':'autobaud','experimental':True,'source':str(source.relative_to(root)),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'generated_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'transformation':'namespace and class identity only','gpio_sync_time_added':False,'turnaround_tuned':False,'firmware_changed':False}
 path=generated/'manifest.json';manifest=json.loads(path.read_text());entry=next(e for e in manifest if e['generated']=='nozzle/peripherals/VirtualNozzleTmc2209.cs');entry.update(source=info['source'],source_sha256=info['source_sha256'],generated_sha256=info['generated_sha256'],experimental_tmc_model='autobaud');path.write_text(json.dumps(manifest,indent=2)+'\n')
 return info


def require_quantum(commands):
 values=[]
 for line in commands:
  if re.match(r'\s*emulation\s+SetGlobalQuantum\b',line):
   match=re.fullmatch(r'\s*emulation\s+SetGlobalQuantum\s+"?(0\.000001)"?\s*',line)
   values.append(bool(match))
 if not values or not values[-1]:
  raise ValueError('Experimental autobaud requires an explicit final setup SetGlobalQuantum "0.000001"')
