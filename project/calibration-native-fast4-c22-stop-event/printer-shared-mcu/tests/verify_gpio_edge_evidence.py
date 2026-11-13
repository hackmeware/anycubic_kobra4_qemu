"""Verify saved CPU-less unit/fanout logs; no emulator actions."""
import csv,sys
from pathlib import Path
p=Path(sys.argv[1])
assert 'PASSIVE GPIO EDGE TESTS PASS: 15' in (p/'test.log').read_text()
for name in ['main','motor']:
 with (p/(name+'.csv')).open() as f: rows=list(csv.DictReader(x for x in f if not x.startswith('#')))
 assert [x['kind'] for x in rows]==['initial','edge','edge','edge','edge']
 assert [int(x['level']) for x in rows]==[0,1,0,1,0]
 assert [int(x['sequence']) for x in rows]==list(range(5))
 assert rows[2]['virtual_time_s']==rows[3]['virtual_time_s']
print('PASS: 15 observer assertions and two-machine four-edge fanout/order/time checks')
