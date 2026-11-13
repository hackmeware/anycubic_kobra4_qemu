"""Reconstructed offline UI evidence adapter and read-only loopback RFB probe.
Reconstructed from retained thread source; not claimed byte-identical to lost file.
"""
import importlib.util,json,sys,time,socket,struct,hashlib,ipaddress,re
from pathlib import Path

def module(root,name):
    root=Path(root).resolve(strict=True);sys.path.insert(0,str(root))
    try:
        spec=importlib.util.spec_from_file_location('kobra_ui_'+name,root/(name+'.py'))
        obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj
    finally:sys.path.pop(0)

def commands(root,run):return module(root,'generate_ui').generate(run,network='off')[0]

def normalize_console(text):
    clean=re.sub(r'\x1b\[[0-9;]*m','',text).replace('\r\n','\n')
    if any((ord(c)<32 and c not in '\n\r\t') or ord(c)==127 for c in clean):
        raise ValueError('Unrecognized console control sequence; no terminal rewriting accepted')
    return clean

def nonuniform(ppm):
    header=b'P6\n480 320\n255\n'
    if not ppm.startswith(header) or len(ppm)!=len(header)+480*320*3:raise ValueError('Unexpected captured PPM geometry/length')
    pixels=ppm[len(header):];return pixels!=pixels[:3]*(480*320)

def evidence(out,plan,live=False):
    out=Path(out);result={'requested':True,'run_id':plan['ui_run_id'],'ui_connection_ready':False,'printer_ready':False,'fault_observed':False,'frame_verified':False,'loopback_viewer_verified':False,'full_c22_fault_review_performed':False}
    try:
        path=out/'logs/console.bin'
        if path.stat().st_size>32*1024**2:raise ValueError('UI console bound')
        result.update(module(plan['ui_tools'],'ui_evidence').parse(normalize_console(path.read_text(errors='replace')),plan['ui_run_id']))
    except (OSError,ValueError) as e:result['parse_error']=str(e)
    try:
        endpoint=json.loads((out/'logs/vnc-endpoint.json').read_text())
        inventory=json.loads((out/'OWNED-LISTENERS.json').read_text());rows=inventory['observed']
        matching_rows=inventory.get('current',[]) if live else rows
        result['all_owned_listeners_loopback']=bool(rows) and all(ipaddress.ip_address(r['address']).is_loopback for r in rows)
        result['loopback_viewer_verified']=result['all_owned_listeners_loopback'] and endpoint['host']=='127.0.0.1' and any(r['address']=='127.0.0.1' and r['port']==endpoint['port'] for r in matching_rows)
        probe=json.loads((out/'FRAME-PROBE.json').read_text());frame_path=out/'frame-probe.ppm'
        if frame_path.stat().st_size>480*320*3+64:raise ValueError('Captured frame exceeds bound')
        frame=frame_path.read_bytes();result['frame_sha256_matches']=hashlib.sha256(frame).hexdigest()==probe['sha256']
        result['frame_nonuniform']=nonuniform(frame)
        result['live_frame_available']=probe['frames_received']>0 and result['frame_sha256_matches'] and result['frame_nonuniform']
        result['live_frame_basis']='Owned reviewed VNC source has uniform-zero fallback; nonuniform captured RFB pixels require a decoded guest frame'
        report={} if live else json.loads((out/'logs/live-viewer.json').read_text())
        result['frame_verified']=report.get('valid_guest_updates',0)>0 and result['live_frame_available']
        result['visual_ui_inspection_performed']=False
        result['viewer']=report;result['frame_probe']=probe;result['endpoint']=endpoint
    except (OSError,KeyError,ValueError) as e:result['frame_evidence_error']=str(e)
    name='UI-OBSERVATION.json' if live else 'UI-EVIDENCE.json'
    pending=out/(name+'.pending');pending.write_text(json.dumps(result,indent=2)+'\n');pending.replace(out/name)
    return result

def should_stop(observation):
    return not observation.get('parse_error') and all(observation.get(k) for k in ('ui_connection_ready','live_frame_available','loopback_viewer_verified'))

def receive(sock,n):
    data=bytearray()
    while len(data)<n:
        chunk=sock.recv(n-len(data))
        if not chunk:raise EOFError('RFB disconnected')
        data.extend(chunk)
    return bytes(data)

def capture(sock):
    if receive(sock,12)!=b'RFB 003.008\n':raise ValueError('RFB version')
    sock.sendall(b'RFB 003.008\n')
    if receive(sock,2)!=b'\x01\x01':raise ValueError('RFB security')
    sock.sendall(b'\x01')
    if receive(sock,4)!=bytes(4):raise ValueError('RFB security result')
    sock.sendall(b'\x01');header=receive(sock,24);w,h=struct.unpack('>HH',header[:4]);n=struct.unpack('>I',header[20:])[0]
    if (w,h)!=(480,320) or n>4096:raise ValueError('RFB size')
    expected=struct.pack('>BBBBHHHBBB3x',32,24,0,1,255,255,255,16,8,0)
    if header[4:20]!=expected:raise ValueError('RFB pixel format')
    receive(sock,n);sock.sendall(struct.pack('>BBHHHH',3,0,0,0,w,h))
    if receive(sock,4)!=b'\0\0\0\1':raise ValueError('RFB rectangle count')
    if struct.unpack('>HHHHi',receive(sock,12))!=(0,0,w,h,0):raise ValueError('RFB rectangle')
    raw=receive(sock,w*h*4);rgb=bytearray(w*h*3)
    rgb[0::3]=raw[2::4];rgb[1::3]=raw[1::4];rgb[2::3]=raw[0::4]
    return b'P6\n480 320\n255\n'+rgb

def probe(out):
    out=Path(out);plan=json.loads((out/'RUN-PLAN.json').read_text());end=time.monotonic()+plan['hard_limit_seconds'];count=0
    while time.monotonic()<end and not (out/'stop-request').exists():
        try:
            ep=json.loads((out/'logs/vnc-endpoint.json').read_text())
            rows=json.loads((out/'OWNED-LISTENERS.json').read_text())['current']
            if ep['host']!='127.0.0.1' or not any(r['address']=='127.0.0.1' and r['port']==ep['port'] for r in rows):raise ValueError('owned loopback endpoint not yet observed')
            with socket.create_connection(('127.0.0.1',ep['port']),timeout=2) as sock:
                sock.settimeout(2);ppm=capture(sock)
            count+=1;pending=out/'frame-probe.ppm.pending';pending.write_bytes(ppm);pending.replace(out/'frame-probe.ppm')
            record={'frames_received':count,'sha256':hashlib.sha256(ppm).hexdigest(),'nonuniform_pixels':nonuniform(ppm),'width':480,'height':320,'touch_events_sent':0,'keys_sent':0,'clipboard_sent':0,'host':'127.0.0.1','port':ep['port'],'caution':'Framebuffer reception is not UI readiness; consult native UI evidence and valid_guest_updates'}
            pending=out/'FRAME-PROBE.json.pending';pending.write_text(json.dumps(record,indent=2)+'\n');pending.replace(out/'FRAME-PROBE.json')
        except (OSError,ValueError,KeyError,EOFError):pass
        time.sleep(2)

if __name__=='__main__':probe(sys.argv[1])
