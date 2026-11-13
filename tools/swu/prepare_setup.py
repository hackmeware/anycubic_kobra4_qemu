"""Prepare a known decrypted SWU setup archive; no scripts or ARM code executed."""
import argparse,hashlib,json,shutil,tarfile
from pathlib import Path
import build_app,build_system,build_disk,rv1106_fit
HERE=Path(__file__).resolve().parent
SETUP='e8845e5d8af475578f3e0f860f9990dc7b581620ad5cc07b50a5730a2e799b66'
def prepare(setup,out,tools):
 setup=Path(setup).resolve();out=Path(out).absolute()
 if setup.stat().st_size!=71905840 or build_app.sha(setup)!=SETUP:raise ValueError('unsupported setup archive')
 out.mkdir(mode=0o700);vendor=out/'vendor';vendor.mkdir(mode=0o700);inputs=out/'inputs';inputs.mkdir(mode=0o700)
 pins=json.loads((HERE/'firmware-profile.json').read_text())['expected_inputs']
 names={'mcu_firmware_v1.3.3_20260311.bin':'mcu.bin','motor_firmware_v1.6.01_20260313.bin':'motor.bin','nozzle_firmware_v1.2.9_20260120.bin':'nozzle.bin','update_ota.tar':'update_ota.tar'}
 with tarfile.open(setup) as tf:
  for name,target in names.items():
   m=tf.getmember('./'+name)
   if not m.isfile() or m.size>30*1024*1024:raise ValueError('setup member mismatch')
   p=(vendor if target.endswith('.tar') else inputs)/target
   with tf.extractfile(m) as src,p.open('xb') as dest:shutil.copyfileobj(src,dest)
   if target in pins and build_app.sha(p)!=pins[target]['sha256']:raise ValueError('MCU hash mismatch')
 layout=json.loads((HERE/'reference-disk-layout.json').read_text());expected={p['source']:p['sha256'] for p in layout['partitions'] if p['source'] and p['source'].endswith('.img')}
 seen=set()
 with tarfile.open(vendor/'update_ota.tar') as tf:
  for m in tf:
   if m.name not in expected or m.name in seen or not m.isfile() or m.size>32*1024*1024:raise ValueError('OTA member mismatch')
   seen.add(m.name);p=vendor/m.name
   with tf.extractfile(m) as src,p.open('xb') as dest:shutil.copyfileobj(src,dest)
   if build_app.sha(p)!=expected[m.name]:raise ValueError('OTA hash mismatch')
 if seen!=set(expected):raise ValueError('missing OTA member')
 # FIT images verified by the existing bounded parser.
 data=(vendor/'boot.img').read_bytes();nodes,total=rv1106_fit.fdt(data)
 for name,key in [('kernel-zImage','kernel'),('kernel-board-dtb.dtb','fdt')]:
  info,payload=rv1106_fit.fit_image(data,nodes,total,key)
  if hashlib.sha256(payload).hexdigest()!=pins[name]['sha256']:raise ValueError('FIT hash mismatch')
  (inputs/name).write_bytes(payload)
 system=build_system.build(vendor/'system.img',out/'system',Path(tools)/'usr/bin/mksquashfs')
 app=build_app.build([setup],out/'filesystems',tools)
 disk=build_disk.create(vendor,out/'system/system-diagnostic.img',out/'filesystems',out/'disk',HERE/'reference-disk-layout.json')
 shutil.copyfile(out/'disk/offline-emmc.img',inputs/'offline-emmc.img')
 (inputs/'disk-layout.json').write_text(json.dumps(disk,indent=2)+'\n')
 report={'status':'PREPARED_DIAGNOSTIC_INPUTS_BOOT_UNTESTED','setup_sha256':SETUP,'profile':'kobra-r9-rebuilt-v1','vendor_code_executed':False,'signature_authenticity_verified':False,'old_disk_metadata_reproduced':False,'inputs':{p.name:{'bytes':p.stat().st_size,'sha256':build_app.sha(p)} for p in inputs.iterdir()},'system':system,'filesystems':app}
 (out/'PREPARED-INPUTS.json').write_text(json.dumps(report,indent=2)+'\n');return report
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--setup',required=True);p.add_argument('--out',required=True);p.add_argument('--tools-root',required=True);a=p.parse_args();print(json.dumps(prepare(a.setup,a.out,a.tools_root),indent=2))
