"""Read-only paired native TMC transport/UART analysis; never repairs bytes."""
import pathlib,sys,json,hashlib,collections
root=pathlib.Path(__file__).resolve().parents[3];sys.path.insert(0,str(root/'rv1106-at32-link/scripts'))
from decode_frames import frames

def crc(data):
 c=0
 for b in data:
  for i in range(8):c=((c<<1)^7 if (c>>7)^((b>>i)&1) else c<<1)&255
 return c

def decode(data):
 bits=[(b>>i)&1 for b in data for i in range(8)];values=[];bad=[]
 assert len(bits)%10==0
 for n in range(len(bits)//10):
  b=bits[n*10:n*10+10];values.append(sum(b[j+1]<<j for j in range(8)))
  if b[0]!=0 or b[9]!=1:bad.append(n)
 return {'uart_hex':bytes(values).hex(),'bad_start_stop_byte_indices':bad,'crc_valid':bool(values) and crc(values[:-1])==values[-1]}

def analyze(name):
 run=root/'runs'/name;groups=[];hashes={}
 for file,cmd in [('rv-nozzle-tx.bin',0x32),('nozzle-tx.bin',0x6b)]:
  raw=(run/file).read_bytes();hashes[file]=hashlib.sha256(raw).hexdigest();found=[]
  for f in frames(raw):
   frame=bytes.fromhex(f['decoded_hex']);p=frame[2:-3]
   if p and p[0]==cmd:found.append({'offset':f['offset'],'sequence':frame[1]&15,'payload':p})
  groups.append(found)
 reqs,replies=groups;assert len(reqs)==len(replies)
 result=[];counts=collections.Counter()
 for req,reply in zip(reqs,replies):
  p=req['payload'];r=reply['payload'];assert p[1]==r[1]==0
  assert reply['sequence']==(req['sequence']+1)%16
  tx=p[3:3+p[2]];want=p[3+p[2]];rx=r[3:];assert len(rx)==r[2] and len(p)==p[2]+4
  request=decode(tx);response=decode(rx)
  assert request['crc_valid'] and not request['bad_start_stop_byte_indices']
  kind='write_no_reply_expected' if want==0 else 'empty_read' if not rx else 'valid_read' if response['crc_valid'] and not response['bad_start_stop_byte_indices'] else 'malformed_read'
  counts[kind]+=1
  result.append({'request_offset':req['offset'],'response_offset':reply['offset'],'request_sequence':req['sequence'],'response_sequence':reply['sequence'],'outer_frame_crc_valid':True,'expected_packed_reply_length':want,'actual_packed_reply_length':len(rx),'request':request,'response':response,'classification':kind})
 return {'run':name,'capture_sha256':hashes,'summary':dict(counts),'transactions':result}
out=root/'evidence/nozzle-uart-timing';out.mkdir(exist_ok=True,parents=True)
report={'bit_edges_recorded':False,'pairing':'Ordered TMC command/response pairs; every sequence checked modulo16; decoder accepts only valid outer CRC frames','runs':[analyze(n) for n in ['native-control-only-homing','native-enable-initialized']]}
(out/'native-capture-comparison.json').write_text(json.dumps(report,indent=2)+'\n')
for r in report['runs']:print(r['run'],r['summary'])
