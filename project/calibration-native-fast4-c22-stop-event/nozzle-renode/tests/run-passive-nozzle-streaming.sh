#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RENODE=${RENODE:-"$ROOT/../at32-runtime/renode_1.17.0-portable/renode"}
RESULT_DIR=${RESULT_DIR:-"$ROOT/tests/results/passive-nozzle-streaming"}
mkdir -p "$RESULT_DIR"
SESSION=$(mktemp -d "$RESULT_DIR/session-XXXXXX")
printf '%s\n' "$SESSION" > "$RESULT_DIR/latest-session.txt"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export HOME="$WORK/home" XDG_CONFIG_HOME="$WORK/home/.config"
mkdir -p "$XDG_CONFIG_HOME"
cat > "$WORK/test.resc" <<SCRIPT
include @$ROOT/peripherals/AT32F403A_System.cs
include @$ROOT/peripherals/AT32F403A_IO.cs
mach create
machine LoadPlatformDescription @$ROOT/tests/passive-nozzle-thermal-observer.repl
include @$ROOT/scripts/virtual-nozzle-recovered-ntc.resc
include @$ROOT/scripts/passive-nozzle-thermal-observer.resc
include @$ROOT/tests/PassiveNozzleStreamingTests.cs
machine LoadPlatformDescription @$ROOT/tests/passive-nozzle-streaming-checks.repl
sysbus.streamChecks Prepare @$SESSION
emulation RunFor "0.1"
sysbus.streamChecks Finish @$SESSION
quit
SCRIPT
cd "$ROOT"
timeout 90 "$RENODE" --disable-xwt --console "$WORK/test.resc" 2>&1 | tee "$SESSION/renode.log"
grep -q 'PASSIVE NOZZLE STREAMING TESTS PASS:' "$SESSION/renode.log"
python3 - "$SESSION" <<'PY'
import csv,json,pathlib,sys
p=pathlib.Path(sys.argv[1]);load=lambda n:json.loads((p/n).read_text())
live=load('live.status.json');stopped=load('stopped.status.json');cap=load('capped.status.json');failed=load('failed.status.json')
assert live['streaming'] and live['stream_rows_written']==4 and not live['stream_error_count']
assert not stopped['streaming'] and not stopped['stream_requested']
assert cap['stream_capacity_reached'] and cap['stream_rows_written']==2 and cap['stream_dropped_rows']==2
assert failed['stream_error_count'] and failed['stream_dropped_rows']==2 and failed['stream_write_outcome_uncertain']
for name in ['stream.csv','continued.csv','capped.csv','failed.csv']:
 rows=list(csv.DictReader((p/name).open()));assert rows and all(None not in r for r in rows)
 assert all(float(r['physical_temperature_c'])==25 and r['published_adc_code']=='4023' and r['last_heater_duty']=='0' and r['last_fan_duty']=='0' for r in rows)
print('PASSIVE NOZZLE STREAM CSV/STATUS PASS: flush, fresh-file protection, bounded output, explicit I/O uncertainty, unchanged devices')
PY
