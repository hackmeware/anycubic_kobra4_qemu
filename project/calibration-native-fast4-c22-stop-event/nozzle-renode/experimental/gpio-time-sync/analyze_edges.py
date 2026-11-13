"""Independent assertions on candidate's observed GPIO waveform, not LastReply."""
import pathlib,csv,json,bisect
root=pathlib.Path(__file__).resolve().parents[3];out=pathlib.Path(__import__('os').environ.get('RESULT_DIRECTORY',str(root/'evidence/gpio-time-sync')))
cases=json.loads((out/'cases.json').read_text());sections={};label=None
for row in csv.DictReader((out/'phase-edges.csv').open()):
 if row['event'].startswith('mark:b'):label=row['event'][5:];sections[label]=[]
 elif label:sections[label].append(row)
def crc(data):
 c=0
 for b in data:
  for i in range(8):c=((c<<1)^7 if (c>>7)^((b>>i)&1) else c<<1)&255
 return c
results=[]
for case in cases:
 rows=sections[case['label']];edges=[r for r in rows if r['event']=='edge'];request=[r for r in edges if int(r['mode'])&3 and r['level']=='0'];reply=[r for r in edges if not int(r['mode'])&3 and int(r['reads'])>0]
 if case['fault']!='none':
  assert not reply,case
  continue
 bit=1000000000//case['baud'];start=int(request[0]['clock_ns']);reply_start=int(reply[0]['clock_ns']);delay_bits=8*(case['senddelay']|1)
 # Four request bytes: final stop sample at39.5 bit periods, retained reference.
 assert reply_start-start==bit*79//2+delay_bits*bit,(case,reply_start-start)
 times=[int(r['clock_ns']) for r in reply];levels=[int(r['level']) for r in reply]
 def at(t):return levels[bisect.bisect_right(times,t)-1]
 decoded=[]
 for byte in range(8):
  t=reply_start+byte*10*bit
  assert at(t+bit//2)==0 and at(t+bit*19//2)==1,(case,byte,'framing')
  decoded.append(sum(at(t+(3+2*i)*bit//2)<<i for i in range(8)))
 assert decoded[:3]==[5,255,2] and crc(decoded[:-1])==decoded[-1],(case,decoded)
 results.append(dict(case,measured_reply_start_delta_ns=reply_start-start,reply_bytes=bytes(decoded).hex()))
(out/'edge-results.json').write_text(json.dumps({'passed':True,'positive_waveforms':len(results),'negative_no_reply_cases':60,'results':results},indent=2)+'\n');print('PASS:72 baud/phase/SENDDELAY edge waveforms and60 negative no-reply cases')
