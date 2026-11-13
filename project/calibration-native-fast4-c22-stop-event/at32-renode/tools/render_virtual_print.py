#!/usr/bin/env python3
"""Render an observer CSV as a standalone, read-only HTML replay. No network access."""
import argparse, csv, html, io, json, math
from pathlib import Path

def render(source, destination):
    text = Path(source).read_text()
    lines = text.splitlines()
    label = next((s[10:] for s in lines if s.startswith('# source: ')), 'unverified bindings')
    reader = csv.DictReader(io.StringIO('\n'.join(s for s in lines if not s.startswith('#'))))
    rows = []
    for row in reader:
        parsed = {}
        for key, value in row.items():
            if key is None: raise ValueError('Extra CSV columns')
            if key.endswith('_fault'): parsed[key] = value
            elif value in ('', None): parsed[key] = None
            else:
                number = float(value)
                if not math.isfinite(number): raise ValueError('Non-finite sample')
                parsed[key] = number
        if parsed.get('time_s') is None: raise ValueError('Missing time_s')
        if rows and parsed['time_s'] <= rows[-1]['time_s']: raise ValueError('Time must increase')
        rows.append(parsed)
    if not rows: raise ValueError('No samples')
    data = json.dumps(rows, allow_nan=False).replace('<', '\\u003c')
    page = TEMPLATE.replace('__LABEL__', html.escape(label)).replace('__DATA__', data)
    Path(destination).write_text(page)
    return len(rows)

TEMPLATE = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Virtual printer observation</title>
<style>body{font:16px system-ui;background:#101827;color:#edf1f7;max-width:1100px;margin:30px auto;padding:0 20px}h1{font-size:27px}.note{color:#ffcf73}canvas{width:100%;height:230px;background:#172338;border-radius:10px}input{width:75%}button{padding:8px 16px}pre{white-space:pre-wrap}.legend{font-size:14px;color:#bdc9db}</style>
<h1>Virtual printer observation</h1><p>Source: <strong>__LABEL__</strong></p><p class="note">Measured virtual component state, not proof of a completed print. Axis A/B are motor-space coordinates unless separately verified. No inferred nozzle path, extrusion geometry or real hardware control.</p>
<button id="play">Play</button> <input id="seek" type="range" min="0" value="0" step="1" aria-label="Replay sample"><span id="time"></span>
<h2>Temperature</h2><div class="legend">Hotend: orange · Bed: blue. Empty series means no connected model.</div><canvas id="thermal" width="1060" height="230"></canvas>
<h2>Axis position</h2><div class="legend">A: orange · B: blue · Z: green · Extruder: pink. Millimeters depend on configured steps/mm.</div><canvas id="axes" width="1060" height="230"></canvas><pre id="values"></pre>
<script>const rows=__DATA__;const seek=document.getElementById('seek');seek.max=rows.length-1;
function chart(id,keys,colors,index,unit){const c=document.getElementById(id),x=c.getContext('2d');x.clearRect(0,0,c.width,c.height);let values=rows.flatMap(r=>keys.map(k=>r[k])).filter(v=>v!==null&&v!==undefined);if(!values.length){x.fillStyle='#fff';x.fillText('No connected model',30,40);return;}let low=values.reduce((a,b)=>Math.min(a,b),Infinity),high=values.reduce((a,b)=>Math.max(a,b),-Infinity);if(low===high){low-=1;high+=1;}let end=rows.at(-1).time_s||1;const px=t=>60+t/end*(c.width-80),py=v=>195-(v-low)/(high-low)*170;x.font='13px system-ui';x.fillStyle='#bdc9db';x.fillText(high.toFixed(1)+' '+unit,4,22);x.fillText(low.toFixed(1),4,198);x.fillText('0 s',60,220);x.fillText(end.toFixed(2)+' s',c.width-85,220);keys.forEach((k,n)=>{x.strokeStyle=colors[n];x.beginPath();let started=false;rows.forEach(r=>{if(r[k]===null||r[k]===undefined){started=false;return;}if(started)x.lineTo(px(r.time_s),py(r[k]));else{x.moveTo(px(r.time_s),py(r[k]));started=true;}});x.stroke();});x.strokeStyle='#ffffff';x.beginPath();x.moveTo(px(rows[index].time_s),20);x.lineTo(px(rows[index].time_s),200);x.stroke();}
function draw(){let i=+seek.value,r=rows[i];document.getElementById('time').textContent=r.time_s.toFixed(2)+' virtual s';chart('thermal',['hotend_c','bed_c'],['#ffa34d','#58b5ff'],i,'°C');chart('axes',['a_mm','b_mm','z_mm','e_mm'],['#ffa34d','#58b5ff','#74df9b','#ff8cc5'],i,'mm');document.getElementById('values').textContent=JSON.stringify(r,null,2);}
let playing=false;document.getElementById('play').onclick=()=>{playing=!playing;document.getElementById('play').textContent=playing?'Pause':'Play';};seek.oninput=draw;setInterval(()=>{if(playing){if(+seek.value>=rows.length-1){playing=false;document.getElementById('play').textContent='Play';return;}seek.value=+seek.value+1;draw();}},100);draw();</script></html>'''
if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('csv',type=Path);p.add_argument('html',type=Path);a=p.parse_args()
    print(f'Rendered {render(a.csv,a.html)} observed samples to {a.html}')
