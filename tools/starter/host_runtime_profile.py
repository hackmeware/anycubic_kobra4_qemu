"""Explicit pinned host-shell experiment. Never edits source/runtime in place."""
import hashlib,json,pathlib,shutil
ORIGINAL='6af41340073256ba1c08c24c0b494f732284c72f29546c3034e5a36dca7312c8'
CANDIDATE='fd6fd1e2e49ca5c0738f861a577c8b7218308d6f58768a842f63620f323f2ceb'
OFFSET=9215
OLD=bytes.fromhex('6f97000006');NEW=bytes.fromhex('2614000000')
def digest(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def prepare(renode,out,profile):
 renode=pathlib.Path(renode);out=pathlib.Path(out)
 if profile=='original':return renode,{'profile':'original','history_autosave_disabled':False}
 if profile!='no-history-autosave':raise ValueError('unknown host runtime profile')
 source=renode.parent;target=out/'host-runtime-renode'
 if target.exists() or target.is_symlink():raise ValueError('new runtime directory required')
 for p in source.rglob('*'):
  if p.is_symlink():raise ValueError('source runtime symlinks rejected')
 dll=source/'AntShell.dll'
 if digest(dll)!=ORIGINAL:raise ValueError('unrecognized AntShell source')
 data=dll.read_bytes()
 if data[OFFSET:OFFSET+5]!=OLD:raise ValueError('IL offset signature mismatch')
 candidate=data[:OFFSET]+NEW+data[OFFSET+5:]
 if hashlib.sha256(candidate).hexdigest()!=CANDIDATE:raise ValueError('candidate hash mismatch')
 shutil.copytree(source,target)
 (target/'AntShell.dll').write_bytes(candidate)
 differences=[];rows=[]
 for p in sorted(source.rglob('*')):
  if not p.is_file():continue
  rel=p.relative_to(source);a=digest(p);b=digest(target/rel)
  if a!=b:differences.append(str(rel))
  rows.append({'path':str(rel),'original_sha256':a,'selected_sha256':b})
 if differences!=['AntShell.dll']:raise ValueError('unexpected runtime differences')
 record={'profile':profile,'history_autosave_disabled':True,'in_memory_history_preserved':True,'command_audit':'monitor-commands.jsonl append-only; renode.log unchanged','original_sha256':ORIGINAL,'candidate_sha256':CANDIDATE,'patch_file_offset':OFFSET,'patch_old':OLD.hex(),'patch_new':NEW.hex(),'virtual_time_modified':False,'firmware_modified':False,'files':rows}
 (out/'HOST-RUNTIME-MANIFEST.json').write_text(json.dumps(record,indent=2)+'\n')
 return target/renode.name,record
