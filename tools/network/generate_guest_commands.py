#!/usr/bin/env python3
"""Short UART-safe shell command serialization for fresh diagnostic boot."""
from pathlib import Path
import shlex

MAX_LINE=500

def generate(hook, mode='isolated'):
    if mode not in ('isolated', 'internet'): raise ValueError('invalid network mode')
    lines=[
        '# Guest-only RAM /tmp preparation before hooks, no original image writes.',
        "if ! grep -q ' /tmp tmpfs ' /proc/mounts; then mount -t tmpfs -o size=16m,mode=1777 tmpfs /tmp; fi",
        "umask 077; mkdir -p /tmp/k4-usb-net; rm -f /tmp/k4-usb-net/lease-ready",
        "printf '%s\\n' "+shlex.quote(mode)+" > /tmp/k4-usb-net/mode",
        "if : > /tmp/k4-usb-net/hook.sh; then echo K4_NET_TMP_READY; else echo K4_NET_ERROR_TMP; fi",
    ]
    for line in hook.splitlines():
        lines.append("printf '%s\\n' "+shlex.quote(line)+' >> /tmp/k4-usb-net/hook.sh')
    lines += [
        'chmod 700 /tmp/k4-usb-net/hook.sh',
        'ifconfig lo up',
        'n=0; while [ ! -d /sys/class/net/eth0 ] && [ "$n" -lt 20 ]; do sleep 1; n=$((n+1)); done',
        'if [ -d /sys/class/net/eth0 ]; then ifconfig eth0 up && udhcpc -i eth0 -s /tmp/k4-usb-net/hook.sh -t 5 -T 2 -n -q; else echo K4_NET_ERROR_NO_ETH0; fi',
        'if [ -f /tmp/k4-usb-net/lease-ready ]; then echo K4_NET_CONFIG_READY; else echo K4_NET_CONFIG_FAILED; fi',
        'ifconfig eth0','route -n','cat /etc/resolv.conf'
    ]
    if any(len(line.encode())>MAX_LINE for line in lines):
        raise ValueError('Guest command exceeds UART-safe line bound')
    return '\n'.join(lines)+'\n'

if __name__=='__main__':
    here=Path(__file__).resolve().parent
    (here/'usb-ethernet.commands').write_text(generate((here/'udhcpc-hook.sh').read_text()))
