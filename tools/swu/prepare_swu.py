#!/usr/bin/env python3
"""Prepare diagnostic emulator inputs from a local SWU or explicit HTTPS URL."""
import argparse,getpass,json,os,sys
from pathlib import Path
import import_swu,prepare_setup

def run(a):
 os.umask(0o077);out=import_swu.fresh_directory(a.output)
 report={'status':'INCOMPLETE','firmware_executed':False,'manufacturer_authenticity_verified':False,'boot_tested':False}
 try:
  source=out/'input.swu'
  if a.url:
   if not a.sha256:raise ValueError('--url requires --sha256')
   report['source']=import_swu.download(a.url,source)
  else:
   original=Path(a.swu).resolve(strict=True)
   if not original.is_file() or original.stat().st_size>import_swu.MAX_SWU:raise ValueError('not a bounded regular SWU')
   with original.open('rb') as src:import_swu.bounded_copy(src,source,original.stat().st_size)
   report['source']={'kind':'local','filename':original.name}
  actual=import_swu.digest(source);report['swu_sha256']=actual
  if actual!=import_swu.KNOWN_SHA256 or a.sha256 and actual!=a.sha256.lower():raise ValueError('unsupported firmware hash/version')
  if not sys.stdin.isatty():raise ValueError('interactive terminal required for SWU password')
  password=getpass.getpass('SWU password (not saved): ').encode()
  import_swu.extract_outer(source,out/'outer',password,import_swu.Budget());password=None
  setup=out/'outer/update_swu/setup.tar.gz'
  prepared=prepare_setup.prepare(setup,out/'prepared',a.tools_root)
  report.update(status=prepared['status'],prepared_report='prepared/PREPARED-INPUTS.json',profile=prepared['profile'])
  return report
 finally:(out/'IMPORT-REPORT.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);s=p.add_mutually_exclusive_group(required=True);s.add_argument('--swu');s.add_argument('--url');p.add_argument('--sha256');p.add_argument('--output',required=True);p.add_argument('--tools-root',required=True);a=p.parse_args()
 try:print(json.dumps(run(a),indent=2))
 except Exception as e:print('Preparation stopped: '+str(e),file=sys.stderr);sys.exit(2)
