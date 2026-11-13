#!/usr/bin/env python3
"""Read-only summary of controlled virtual GPIO heater probes; never assigns pins."""
import argparse,csv,json,pathlib
p=argparse.ArgumentParser();p.add_argument('directory',type=pathlib.Path);a=p.parse_args()
result={}
for board,pins in [('main',['PA0']),('nozzle',['PB8','PB9'])]:
    rows=list(csv.DictReader((a.directory/f'{board}-gpio.csv').open()))
    data={}
    for pin in pins:
        selected=[r for r in rows if r['pin']==pin]
        # Initial callback in early observer builds is an initial state, not an edge.
        edges=[r for r in selected if r['event']=='edge' and int(r['time_us'])>0]
        pulses=[];start=None
        for r in edges:
            t=int(r['time_us'])
            if r['level']=='1':start=t
            elif start is not None:
                pulses.append({'rise_us':start,'fall_us':t,'high_seconds':(t-start)/1e6});start=None
        data[pin]={'edges':edges,'completed_high_pulses':pulses,'markers':[r for r in selected if r['event'].startswith('snapshot:')]}
    result[board]=data
print(json.dumps(result,indent=2))
