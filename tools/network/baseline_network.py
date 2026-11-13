#!/usr/bin/env python3
"""New diagnostic integration, separate from historical R9 manifests."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import struct

BASELINE_SHA256='d295efe337e46357fa6cc9bf28356ba6e0cc0df5c82198aa3bf0a4d1eae7bfb1'

def network_args(mode='off', http_port=None, mqtt_port=None):
    if mode not in ('off','isolated','internet'): raise ValueError('invalid network mode')
    ports=[p for p in (http_port,mqtt_port) if p is not None]
    if any(type(p) is not int or not 1<=p<=65535 for p in ports) or len(ports)!=len(set(ports)):
        raise ValueError('invalid or duplicate forwarding ports')
    if mode=='off':
        if ports:raise ValueError('forwarding requires networking')
        return ['-nic','none']
    net='user,id=net0,restrict='+('on' if mode=='isolated' else 'off')
    for host,guest in ((http_port,18910),(mqtt_port,9883)):
        if host is not None:net+=f',hostfwd=tcp:127.0.0.1:{host}-:{guest}'
    return ['-netdev',net,'-device','usb-net,netdev=net0']

def enable_usb_host(nodes):
    """Apply BEFORE serializing diagnostic DT/ELF. Never edits original nodes."""
    nodes=copy.deepcopy(nodes)
    # Keep any alternate original controller at this MMIO address disabled.
    for path,props in nodes.items():
        if path.rsplit('/',1)[-1].endswith('@ffb00000'):
            props['status']=b'disabled\0'
    nodes['/usbdrd']={'compatible':b'simple-bus\0','#address-cells':struct.pack('>I',1),
        '#size-cells':struct.pack('>I',1),'ranges':b'','status':b'okay\0'}
    nodes['/usbdrd/usb@ffb00000']={'compatible':b'generic-xhci\0',
        'reg':struct.pack('>II',0xffb00000,0x10000),'interrupts':struct.pack('>III',0,54,4),
        'dr_mode':b'host\0','maximum-speed':b'high-speed\0','status':b'okay\0'}
    return nodes

def validate_runner_args(args):
    """Trusted local run_link argv, not a sandbox for hostile paths/values."""
    pairs={'-M','-m','-display','-monitor','-chardev','-serial','-kernel','-cpu','-drive','-object','-qmp','-icount'}
    values={}; index=0
    while index<len(args):
        flag=args[index]
        if flag=='-S':
            values.setdefault(flag,[]).append(True); index+=1; continue
        if flag not in pairs or index+1>=len(args):raise ValueError('unsupported/incomplete QEMU option '+flag)
        value=args[index+1];index+=2;values.setdefault(flag,[]).append(value)
        if flag=='-display' and value!='none':raise ValueError('unexpected display')
        if flag=='-monitor' and value!='none' and not value.startswith('pipe:'):raise ValueError('only local monitor pipes admitted')
        if flag=='-chardev' and not value.startswith('serial,'):raise ValueError('only runner serial chardev admitted')
        if flag=='-object' and not value.startswith('memory-backend-file,id=displayram,'):
            raise ValueError('unexpected QEMU object')
    if len(values.get('-M',[]))!=1 or len(values.get('-kernel',[]))!=1:raise ValueError('machine and kernel required once')
    machine=values['-M'][0]
    independent=('rv1106','rv1106,memory-backend=displayram')
    coupled=tuple(m+',virtual-deadline-enabled=on' for m in independent)
    if machine in coupled:
        if values.get('-S')!=[True] or values.get('-icount')!=['shift=0,align=off,sleep=off'] or len(values.get('-qmp',[]))!=1:
            raise ValueError('coupled mode requires exact deadline/S/icount0/QMP tuple')
        qmp=values['-qmp'][0]
        if not qmp.startswith('pipe:/') or any(c in qmp for c in ',\n\r') or '..' in Path(qmp[5:]).parts:
            raise ValueError('coupled QMP requires clean absolute local pipe')
    elif machine in independent:
        if any(flag in values for flag in ('-S','-icount','-qmp')):
            raise ValueError('partial or ungated coupled configuration')
    else:raise ValueError('unsupported machine')
    return list(args)

def command(runtime,args,mode='off',http_port=None,mqtt_port=None):
    runtime=Path(runtime).resolve()
    binary=runtime/'bin/qemu-baseline'
    with binary.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if digest!=BASELINE_SHA256:raise ValueError('scalar baseline hash mismatch')
    loader=runtime/'lib/ld-linux-x86-64.so.2'
    if not loader.is_file():raise ValueError('private runtime loader missing')
    return [str(loader),'--library-path',str(runtime/'lib'),str(binary)]+validate_runner_args(args)+network_args(mode,http_port,mqtt_port)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime',required=True)
    p.add_argument('--mode',choices=['off','isolated','internet'],default='off')
    p.add_argument('--http-port',type=int);p.add_argument('--mqtt-port',type=int)
    p.add_argument('--execute',action='store_true',help='Explicitly exec QEMU after validation; otherwise JSON only')
    p.add_argument('qemu_args',nargs=argparse.REMAINDER)
    a=p.parse_args();args=a.qemu_args
    if args and args[0]=='--':args=args[1:]
    try:cmd=command(a.runtime,args,a.mode,a.http_port,a.mqtt_port)
    except (OSError,ValueError) as e:p.error(str(e))
    if a.execute:os.execv(cmd[0],cmd)
    print(json.dumps({'profile':'r9-scalar-usb-ethernet-diagnostic-v1','argv':cmd,'guest_network_verified':False},indent=2))
if __name__=='__main__':main()
