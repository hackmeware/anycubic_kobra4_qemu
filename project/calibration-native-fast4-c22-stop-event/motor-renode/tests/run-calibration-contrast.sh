#!/usr/bin/env bash
# Runs the user-supplied original firmware. Does not alter firmware or its RAM.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RENODE=${RENODE:-"$ROOT/../at32-runtime/run-renode"}
FW=${MOTOR_FIRMWARE:-/workspace/shared/kobra4-firmware/payload/motor_firmware_v1.6.01_20260313.bin}
OUT="$ROOT/tests/results/calibration"
mkdir -p "$OUT"
cd "$ROOT"
for INPUT in 2048 0; do
    SCRIPT="$OUT/input-$INPUT.resc"
    rm -f "$OUT/samples-$INPUT.bin" "$OUT/faults-$INPUT.bin"
    cat > "$SCRIPT" <<RESC
include @scripts/load.resc
include @scripts/board-clock-and-rtc.resc
include @scripts/stationary-current-plant.resc
sysbus LoadBinary @$FW 0x08008000
cpu VectorTableOffset 0x08008000
sysbus.adc1 SetChannelValue 0 $INPUT
sysbus.adc1 SetChannelValue 4 $INPUT
sysbus.adc2 SetChannelValue 5 $INPUT
sysbus.adc2 SetChannelValue 6 $INPUT
sysbus.adc3 SetChannelValue 12 $INPUT
sysbus.adc3 SetChannelValue 10 $INPUT
emulation RunFor "0.5"
dump_file 0x20003b60 48 @$OUT/samples-$INPUT.bin
dump_file 0x20000c00 48 @$OUT/faults-$INPUT.bin
cpu PC
quit
RESC
    "$RENODE" --disable-xwt --console "$SCRIPT" > "$OUT/input-$INPUT.log" 2>&1
done
python3 - "$OUT" <<'PY'
import pathlib,struct,sys
p=pathlib.Path(sys.argv[1])
for v in (2048,0):
    data=(p/f'samples-{v}.bin').read_bytes(); faults=(p/f'faults-{v}.bin').read_bytes()
    assert len(data)==48 and len(faults)==48
    for motor in range(3):
        wait,samples,sum1,sum2,offset1,offset2=struct.unpack_from('<HHIIHH',data,motor*16)
        assert (wait,samples)==(0,0),(v,motor,wait,samples)
        assert (sum1,sum2)==(v*2048,v*2048),(v,motor,sum1,sum2)
        assert (offset1,offset2)==(v,v),(v,motor,offset1,offset2)
        fault=struct.unpack_from('<H',faults,motor*16)[0]
        assert bool(fault&8)==(v==0),(v,motor,hex(fault))
print('MOTOR CALIBRATION CONTRAST PASS: original firmware preserves zero-input calibration faults')
PY
