#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RENODE=${RENODE:-"$ROOT/../at32-runtime/run-renode"}
FW=${MOTOR_FIRMWARE:-/workspace/shared/kobra4-firmware/payload/motor_firmware_v1.6.01_20260313.bin}
OUT="$ROOT/tests/results"
mkdir -p "$OUT"
cd "$ROOT"
SCRIPT="$OUT/pwm-runtime.resc"
cat > "$SCRIPT" <<RESC
include @scripts/load.resc
include @scripts/board-clock-and-rtc.resc
include @scripts/stationary-current-plant.resc
include @scripts/pwm-trigger-wiring.resc
sysbus LoadBinary @$FW 0x08008000
cpu VectorTableOffset 0x08008000
emulation RunFor "0.3"
sysbus ReadBytes 0x2000073e 36
sysbus ReadBytes 0x40012c00 72
sysbus ReadBytes 0x40000400 72
sysbus ReadBytes 0x40000800 72
sysbus ReadBytes 0x2000070c 12
quit
RESC
"$RENODE" --disable-xwt --console "$SCRIPT" > "$OUT/pwm-wired-register-snapshot.log" 2>&1
python3 - "$OUT/pwm-wired-register-snapshot.log" <<'PY'
import re,struct,sys
s=open(sys.argv[1]).read();s=re.sub(r'\x1b\[[0-9;]*m','',s)
arrays=re.findall(r'\[\s*((?:0x[0-9A-Fa-f]{2},\s*)+)\]',s)
d=[bytes(int(x,16) for x in re.findall(r'0x([0-9A-Fa-f]{2})',b)) for b in arrays]
assert len(d)==5,len(d)
for timer in d[1:4]:
    ctrl,ctrl2,smcr=struct.unpack_from('<III',timer)
    assert ctrl&1,hex(ctrl)
    assert smcr==0x16,hex(smcr)
    assert struct.unpack_from('<I',timer,0x2c)[0]==4000
assert d[4][1:7]==bytes([6]*6),d[4].hex()
print('MOTOR PWM RUNTIME PASS: original firmware starts all three drive timers via selected hardware triggers')
PY
