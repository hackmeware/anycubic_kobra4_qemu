#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RENODE=${RENODE:-"$ROOT/../at32-runtime/run-renode"}
FW=${MOTOR_FIRMWARE:-/workspace/shared/kobra4-firmware/payload/motor_firmware_v1.6.01_20260313.bin}
OUT="$ROOT/tests/results/generic-rl"
mkdir -p "$OUT"
cd "$ROOT"
for CASE in default zero-supply open-winding; do
    CHANGE=""
    DURATION=0.5
    [ "$CASE" != default ] || DURATION=1.0
    [ "$CASE" != zero-supply ] || CHANGE="sysbus.rlPlant Configure 0 2 0.003 500 2048"
    [ "$CASE" != open-winding ] || CHANGE="sysbus.rlPlant OpenWinding true"
    rm -f "$OUT/faults-$CASE.bin" "$OUT/states-$CASE.bin"
    cat > "$OUT/$CASE.resc" <<RESC
include @scripts/load.resc
include @scripts/board-clock-and-rtc.resc
include @scripts/generic-stationary-rl.resc
$CHANGE
sysbus LoadBinary @$FW 0x08008000
cpu VectorTableOffset 0x08008000
emulation RunFor "$DURATION"
dump_file 0x20000c00 48 @$OUT/faults-$CASE.bin
dump_file 0x2000070c 12 @$OUT/states-$CASE.bin
sysbus.rlPlant TriggerCount
sysbus.rlPlant ClippedSamples
sysbus.rlPlant GetCurrent 0 0
sysbus.rlPlant GetCurrent 0 1
cpu PC
quit
RESC
    "$RENODE" --disable-xwt --console "$OUT/$CASE.resc" > "$OUT/$CASE.log" 2>&1
done
python3 - "$OUT" <<'PY'
import pathlib,struct,sys,json
p=pathlib.Path(sys.argv[1]); results={}
for case in ('default','zero-supply','open-winding'):
    data=(p/f'faults-{case}.bin').read_bytes(); states=(p/f'states-{case}.bin').read_bytes()
    assert len(data)==48 and len(states)==12
    faults=[struct.unpack_from('<H',data,axis*16)[0] for axis in range(3)]
    results[case]={'faults':[hex(v) for v in faults], 'state_bytes':list(states)}
    if case=='default':
        assert faults==[0,0,0],faults
        assert states[1:7]==bytes(6),states.hex()
    else:
        assert all(v&0x40 for v in faults),(case,faults)
        assert all(not(v&8) for v in faults),(case,'offset calibration should pass at zero current',faults)
(p/'results.json').write_text(json.dumps(results,indent=2)+'\n')
print('GENERIC RL ORIGINAL FIRMWARE RESULTS:',json.dumps(results))
print('GENERIC RL NEGATIVE TESTS PASS: zero supply and open winding preserve original current-response faults')
PY
