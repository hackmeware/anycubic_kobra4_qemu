#!/usr/bin/env python3
"""Read-only verifier for the two recovered ErrorMessage-style native RPCs.
Acceptance is not physical homing/heating completion. Never sends requests.
"""
import argparse,json,pathlib,re
from decode_extruder_preheating_response import decode_grpc_message

def verify(text,begin,end):
 start=re.search(r'(?:^|\n)'+re.escape(begin)+r'\r?\n',text)
 if not start:return {'status':'pending_begin'}
 finish=re.search(r'(?:^|\n)'+re.escape(end)+r'\r?\n',text[start.end():])
 if not finish:return {'status':'pending_end'}
 block=text[start.end():start.end()+finish.start()];data=bytearray()
 for line in block.splitlines():
  if re.fullmatch(r'[0-7]{7,}\s+(?:[0-7]{3}\s*)+',line):data.extend(int(x,8) for x in line.split()[1:])
 pos=0;body=b'';status_zero=False
 while pos+9<=len(data):
  n=int.from_bytes(data[pos:pos+3],'big');typ,flags=data[pos+3:pos+5];stream=int.from_bytes(data[pos+5:pos+9],'big')&0x7fffffff;payload=bytes(data[pos+9:pos+9+n]);pos+=9+n
  if len(payload)!=n:raise ValueError('Incomplete HTTP2 frame')
  if stream==1 and typ==0:
   if flags&8:raise ValueError('Padded DATA is unsupported by this diagnostic decoder')
   body+=payload
  # Verified native literal HPACK trailer form; unsupported forms never prove success.
  if stream==1 and typ==1 and flags&1 and b'grpc-status\x010' in payload:status_zero=True
 if pos!=len(data):raise ValueError('Trailing incomplete HTTP2 frame')
 response=decode_grpc_message(body)
 return {'status':'response_captured','grpc_status_zero':status_zero,'protobuf_hex':body[5:].hex(),'decoded':response,'api_accepted':status_zero and not response['error_reported'],'physical_completion_proven':False}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--method',choices=['Homing','ExtruderPreheating'],required=True);p.add_argument('--console',type=pathlib.Path,required=True);p.add_argument('--begin',required=True);p.add_argument('--end',required=True);p.add_argument('--output',type=pathlib.Path);a=p.parse_args()
 try:result=verify(a.console.read_text(errors='replace'),a.begin,a.end)
 except (ValueError,UnicodeError) as e:result={'status':'unverified_response','error':str(e),'api_accepted':None,'definitive_rejection':False}
 result['method']=a.method
 if a.output:a.output.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
