#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RENODE=${RENODE:-"$ROOT/../at32-runtime/renode_1.17.0-portable/renode"}
RESULT_DIR=${RESULT_DIR:-"$ROOT/tests/results/passive-nozzle-thermal-observer"}
mkdir -p "$RESULT_DIR"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export HOME="$WORK/home"
export XDG_CONFIG_HOME="$HOME/.config"
mkdir -p "$XDG_CONFIG_HOME"
cat > "$WORK/test.resc" <<SCRIPT
include @$ROOT/peripherals/AT32F403A_System.cs
include @$ROOT/peripherals/AT32F403A_IO.cs
mach create
machine LoadPlatformDescription @$ROOT/tests/passive-nozzle-thermal-observer.repl
include @$ROOT/scripts/virtual-nozzle-recovered-ntc.resc
include @$ROOT/scripts/passive-nozzle-thermal-observer.resc
include @$ROOT/tests/PassiveNozzleThermalObserverTests.cs
machine LoadPlatformDescription @$ROOT/tests/passive-nozzle-thermal-observer-checks.repl
sysbus.observerChecks Prepare
emulation RunFor "0.0025"
sysbus.observerChecks SwitchOutputs
emulation RunFor "0.1"
sysbus.observerChecks Finish
sysbus.passiveNozzleThermalObserver WriteCsv @$RESULT_DIR/observer.csv
sysbus.observerChecks WriteCappedCsv @$RESULT_DIR/capped.csv
quit
SCRIPT
cd "$ROOT"
timeout 90 "$RENODE" --disable-xwt --console "$WORK/test.resc" 2>&1 | tee "$RESULT_DIR/renode.log"
grep -q 'PASSIVE NOZZLE OBSERVER TESTS PASS:' "$RESULT_DIR/renode.log"
python3 - "$RESULT_DIR" <<'PY'
import csv,json,pathlib,sys
root=pathlib.Path(sys.argv[1])
rows=list(csv.DictReader((root/'observer.csv').open()))
assert rows and all(None not in row for row in rows)
edges=[r for r in rows if r['event']=='edge']
assert [(r['time_us'],r['changed_pin'],r['changed_level']) for r in edges]==[('0','PB8','1'),('2500','PB8','0'),('2500','PB9','1'),('2500','PB8','1')]
for row in rows:
    assert float(row['physical_temperature_c'])==25 and row['published_adc_code']=='4023'
    assert row['sensor_curve']=='NTC ZM3863 HNS112HC4570G0' and row['sensor_fault']=='none'
    assert all(row[k]=='0' for k in ['curve_out_of_range','model_overtemperature','model_heater_latched_off','last_heater_duty','last_fan_duty'])
status=json.loads((root/'observer.csv.status.json').read_text())
assert status['rows']==len(rows) and status['observed_edges']==4 and status['dropped_rows']==0
assert not status['firmware_guard_state_recorded'] and not status['actuator_connection_created']
capped=json.loads((root/'capped.csv.status.json').read_text())
assert capped['rows']==2 and capped['capacity_reached'] and capped['dropped_rows']>0
print('PASSIVE NOZZLE CSV PASS: real synthetic GPIO edges, thermal invariance, loss reporting and source scope')
PY
