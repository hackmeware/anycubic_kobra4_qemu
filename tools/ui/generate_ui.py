"""Firmware-free UI command generator; reconstructed from retained source history."""
import argparse,hashlib,json,re
from pathlib import Path
import touch_helper,event_probe
HERE=Path(__file__).resolve().parent
def encoded(data,path):
 if not re.fullmatch(r'/tmp/[a-zA-Z0-9_.-]+',path):raise ValueError('unsafe guest path')
 return ["printf '"+''.join('\\%03o'%b for b in data[i:i+64])+"' "+('>' if i==0 else '>>')+' '+path+' || exit 1' for i in range(0,len(data),64)]
def generate(run,network='off'):
 if not re.fullmatch(r'ui-[a-z0-9][a-z0-9-]{7,55}',run):raise ValueError('invalid fresh run identifier')
 if network!='off':raise ValueError('UI startup requires networking off')
 backend=(HERE/'backend-gate.sh.in').read_text().replace('@RUN@',run)
 setup='''#!/bin/sh
set -eu
RUN=@RUN@
abort() { printf '\\nUI_PREP_ABORT run=%s reason=%s\\n' "$RUN" "$1"; exit 1; }
mkdir /tmp/@RUN@ || abort reused_run
mount -t tmpfs tmpfs /run || abort run_mount
mount -t ext4 /dev/mmcblk0p13 /app || abort app_mount
mount -t squashfs -o ro /dev/mmcblk0p10 /oem || abort oem_mount
mount -t ext4 /dev/mmcblk0p12 /userdata || abort userdata_mount
mount -t ext4 /dev/mmcblk0p14 /data || abort data_mount
mkdir -p /data/logs /data/ui /data/gcodes /data/timelapse /data/config /data/configs
ifconfig lo up || abort loopback
export LD_LIBRARY_PATH=/app/lib:/oem/usr/lib
export TEMPERATURE_SENSOR_CONFIG=/app/etc/sensors.cfg
[ -c /dev/uinput ] || abort uinput_missing
[ -c /dev/fb0 ] || abort framebuffer_missing
[ "$(cat /sys/class/graphics/fb0/virtual_size)" = 480,320 ] || abort framebuffer_dimensions
mkfifo /tmp/touch-events || abort fifo
chmod 700 /tmp/diagnostic-touch /tmp/diagnostic-event-probe
/tmp/diagnostic-touch &
TOUCH_PID=$!
read -r UP REST < /proc/uptime
DEADLINE=$((${UP%%.*} + 10))
ATTEMPTS=0
while :; do
 ATTEMPTS=$((ATTEMPTS + 1))
 kill -0 "$TOUCH_PID" 2>/dev/null || abort touch_ended
 FOUND=
 for N in /sys/class/input/event*/device/name; do
  [ -f "$N" ] || continue
  [ "$(cat "$N")" = 'RV1106 diagnostic touch' ] || continue
  [ -z "$FOUND" ] || abort ambiguous_touch
  E=${N%/device/name}; E=${E##*/}; FOUND=/dev/input/$E
 done
 if [ -n "$FOUND" ] && [ -c "$FOUND" ]; then
  ln -s "$FOUND" /tmp/diagnostic-event || abort event_link
  /tmp/diagnostic-event-probe || abort touch_dimensions
  break
 fi
 read -r UP REST < /proc/uptime
 [ "${UP%%.*}" -lt "$DEADLINE" ] && [ "$ATTEMPTS" -lt 20 ] || abort touch_deadline
 sleep 1
done
printf '\\nUI_DEVICES_VERIFIED run=%s\\n' "$RUN"
exec /bin/sh /tmp/@RUN@-backend.sh
'''.replace('@RUN@',run)
 commands=['mount -t tmpfs tmpfs /tmp || exit 1']
 for data,path in [(touch_helper.build(),'/tmp/diagnostic-touch'),(event_probe.build(),'/tmp/diagnostic-event-probe'),(backend.encode(),'/tmp/'+run+'-backend.sh'),(setup.encode(),'/tmp/'+run+'-setup.sh')]:commands+=encoded(data,path)
 commands+=['/bin/sh /tmp/'+run+'-setup.sh']
 if any(len(x.encode())>=2048 for x in commands):raise ValueError('console line too long')
 return '\n'.join(commands)+'\n',setup,backend
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--network',choices=['off'],default='off');p.add_argument('--output',required=True);a=p.parse_args();data,_,_=generate(a.run_id,a.network)
 with Path(a.output).open('x') as f:f.write(data)
 print(json.dumps({'run':a.run_id,'sha256':hashlib.sha256(data.encode()).hexdigest(),'max_line_bytes':max(map(len,data.encode().splitlines())),'guest_executed':False}))
