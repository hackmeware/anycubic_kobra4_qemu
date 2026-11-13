#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RENODE=${RENODE:-"$ROOT/../at32-runtime/renode_1.17.0-portable/renode"}
RESULT_DIR=${RESULT_DIR:-"$ROOT/tests/results/native-nozzle-heater-binding"}
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
include @$ROOT/scripts/native-nozzle-heater-binding.resc
include @$ROOT/tests/NativeNozzleHeaterBindingTests.cs
machine LoadPlatformDescription @$ROOT/tests/native-nozzle-heater-binding-checks.repl
sysbus.heaterBindingChecks Prepare
emulation RunFor "1"
sysbus.heaterBindingChecks EndPWM
emulation RunFor "10"
sysbus.heaterBindingChecks CheckCoolingAndBeginFault
emulation RunFor "0.1"
sysbus.heaterBindingChecks CheckFaultAndReset
emulation RunFor "0.1"
sysbus.heaterBindingChecks Finish
sysbus.nativeNozzleHeaterBinding WriteStatus @$RESULT_DIR/binding.json
sysbus.passiveNozzleThermalObserver WriteCsv @$RESULT_DIR/observer.csv
quit
SCRIPT
cd "$ROOT"
timeout 90 "$RENODE" --disable-xwt --console "$WORK/test.resc" 2>&1 | tee "$RESULT_DIR/renode.log"
grep -q 'NATIVE NOZZLE HEATER BINDING TESTS PASS:' "$RESULT_DIR/renode.log"
python3 - "$RESULT_DIR" <<'PY'
import csv,json,pathlib,sys
p=pathlib.Path(sys.argv[1]);j=json.loads((p/'binding.json').read_text())
assert j['heater_connected'] and not j['pb9_fan_connected']
assert not j['initial_resolved_pb8_level'] and not j['current_resolved_pb8_level']
assert j['forwarded_gpio_edges']>=202 and j['reset_observations']==1
assert not j['direct_duty_override_used'] and not j['temperature_override_used']
rows=list(csv.DictReader((p/'observer.csv').open()))
assert any(float(r['physical_temperature_c'])>25 and int(r['published_adc_code'])<4023 for r in rows)
assert all(float(r['last_fan_duty'])==0 for r in rows)
assert any(r['sensor_fault']=='open' and r['published_adc_code']=='4095' for r in rows)
assert any(r['sensor_fault']=='short' and r['published_adc_code']=='0' for r in rows)
print('NATIVE NOZZLE BINDING CSV PASS: actual GPIO-driven heat/ADC, fan unbound, visible sensor faults')
PY
