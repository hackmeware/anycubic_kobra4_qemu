#!/usr/bin/env python3
"""Compare isolated on/off/capacity runs without changing source or evidence."""
import csv,hashlib,sys
from pathlib import Path
p=Path(sys.argv[1])
physical=[(p/f'{m}-physical.csv').read_bytes() for m in ['off','on','bounded']]
assert physical[0]==physical[1]==physical[2], 'Physics trace differs with observer'
counts=[(p/f'{m}-count.txt').read_text() for m in ['off','on','bounded']]
assert counts==['240']*3, counts
rows=list(csv.DictReader((p/'on-contact.csv').open()))
assert len(rows)==6 and [r['kind'] for r in rows[:3]]==['initial']*3
transitions=rows[3:]
assert [r['contact_nonzero'] for r in transitions]==['1','0','1']
assert all(float(r['previous_integration_time_s'])<float(r['state_time_s'])==float(r['observation_time_s']) for r in transitions)
assert len(list(csv.DictReader((p/'bounded-contact.csv').open())))==3
assert not (p/'off-contact.csv').exists()
for mode in ['off','on','bounded']:
 assert 'PASSIVE CONTACT TESTS PASS' in (p/f'{mode}.log').read_text()
print('PASS: identical physical CSV bytes in all three runs; 240 integrations each; enter/leave/reenter and capacity checks.')
print('Physical CSV SHA256:',hashlib.sha256(physical[0]).hexdigest())
