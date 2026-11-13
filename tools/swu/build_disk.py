"""Create a new synthetic GPT eMMC image, never a physical-device flashing image."""
import argparse,hashlib,json,struct,uuid,zlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
NAMESPACE=uuid.UUID('69213ca9-3997-4303-a317-9be41db57ce7')
def sha(p):
 with open(p,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def guid(name):return uuid.uuid5(NAMESPACE,name).bytes_le
def create(inputs,system,app,out,layout):
 if sha(layout)!='021394b8b297d0de21d2db32069b68011c773811cd7988aaed3f55fa19621d43':raise ValueError('unsupported reference layout hash')
 inputs=Path(inputs);out=Path(out).absolute();out.mkdir(mode=0o700)
 original=json.loads(Path(layout).read_text());parts=original['partitions'];size=original['disk_size'];sectors=size//512
 sources={}
 for p in parts:
  name=p['source']
  if not name:continue
  file=Path(system) if name=='system.img' else Path(app)/name if name.endswith('.ext4') else inputs/name
  if not file.is_file() or file.stat().st_size>p['sectors']*512:raise ValueError('missing/oversize input '+name)
  digest=sha(file)
  if name not in ('system.img','app.ext4','userdata.ext4','data.ext4') and digest!=p['sha256']:raise ValueError('vendor input hash mismatch '+name)
  sources[name]=(file,digest)
 table=bytearray(128*128)
 for p in parts:
  off=(p['partition']-1)*128
  table[off:off+16]=uuid.UUID('0fc63daf-8483-4772-8e79-3d69d8477de4').bytes_le
  table[off+16:off+32]=guid(p['name']);struct.pack_into('<QQQ',table,off+32,p['start_sector'],p['start_sector']+p['sectors']-1,0)
  encoded=p['name'].encode('utf-16le');table[off+56:off+56+len(encoded)]=encoded
 def header(current,backup,lba):
  h=bytearray(512);struct.pack_into('<8sIIIIQQQQ16sQIII',h,0,b'EFI PART',0x10000,92,0,0,current,backup,34,sectors-34,guid('disk'),lba,128,128,zlib.crc32(table));struct.pack_into('<I',h,16,zlib.crc32(h[:92]));return h
 mbr=bytearray(512);mbr[446:462]=struct.pack('<B3sB3sII',0,b'\0\2\0',0xee,b'\xff'*3,1,sectors-1);mbr[510:]=b'\x55\xaa'
 image=out/'offline-emmc.img'
 with image.open('xb') as f:
  f.truncate(size);f.write(mbr);f.write(header(1,sectors-1,2));f.write(table)
  f.seek((sectors-33)*512);f.write(table);f.write(header(sectors-1,1,sectors-33))
  for p in parts:
   if p['source']:
    f.seek(p['start_sector']*512)
    with sources[p['source']][0].open('rb') as src:
     while b:=src.read(1024*1024):f.write(b)
 report={'profile':'kobra-r9-rebuilt-v1','warning':original['warning'],'boot_tested':False,'old_r9_disk_hash_reproduced':False,'sha256':sha(image),'disk_size':size,'partitions':[]}
 with image.open('rb') as f:
  for p in parts:
   r=dict(p)
   if p['source']:
    source,digest=sources[p['source']];length=source.stat().st_size;f.seek(p['start_sector']*512)
    if hashlib.sha256(f.read(length)).hexdigest()!=digest:raise ValueError('disk readback mismatch')
    r.update(sha256=digest,source_bytes=length)
   report['partitions'].append(r)
 (out/'PREPARED-DISK.json').write_text(json.dumps(report,indent=2)+'\n');return report
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--vendor-images',required=True);p.add_argument('--system',required=True);p.add_argument('--app-dir',required=True);p.add_argument('--out',required=True);p.add_argument('--layout',required=True);a=p.parse_args();print(json.dumps(create(a.vendor_images,a.system,a.app_dir,a.out,a.layout),indent=2))
