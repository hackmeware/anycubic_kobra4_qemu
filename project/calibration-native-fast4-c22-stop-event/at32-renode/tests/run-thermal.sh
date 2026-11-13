#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RUNTIME=${RENODE_RUNTIME:-"$ROOT/../at32-runtime"}
RENODE=${RENODE:-"$RUNTIME/run-renode"}
mkdir -p "$ROOT/tests/results"
SCRIPT=$(mktemp --suffix=.resc)
trap 'rm -f "$SCRIPT"' EXIT
cat > "$SCRIPT" <<SCRIPT
include @$ROOT/peripherals/AT32F403A_System.cs
include @$ROOT/peripherals/VirtualPrinterThermal.cs
include @$ROOT/tests/VirtualThermalTests.cs
mach create
machine LoadPlatformDescription @$ROOT/tests/thermal.repl
sysbus.thermalTests Run
emulation RunFor "0.1"
sysbus.thermalTests CheckTimer
sysbus.thermal ColdReset
sysbus.thermal OnGPIO 0 true
emulation RunFor "0.0025"
sysbus.thermal OnGPIO 0 false
emulation RunFor "0.0075"
sysbus.thermalTests CheckPWM
quit
SCRIPT
"$RENODE" --disable-xwt --console "$SCRIPT" 2>&1 | tee "$ROOT/tests/results/thermal.log"
grep -q 'VIRTUAL THERMAL TESTS PASS:' "$ROOT/tests/results/thermal.log"
grep -q 'VIRTUAL THERMAL TIMER PASS' "$ROOT/tests/results/thermal.log"
grep -q "VIRTUAL THERMAL PWM PASS" "$ROOT/tests/results/thermal.log"
