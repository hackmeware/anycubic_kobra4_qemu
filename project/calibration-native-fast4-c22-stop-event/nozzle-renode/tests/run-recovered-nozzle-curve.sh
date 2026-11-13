#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RENODE=${RENODE:-"$ROOT/../at32-runtime/renode_1.17.0-portable/renode"}
RESULT_DIR=${RESULT_DIR:-"$ROOT/tests/results/recovered-nozzle-curve"}
mkdir -p "$RESULT_DIR"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export HOME="$WORK/home"
export XDG_CONFIG_HOME="$HOME/.config"
mkdir -p "$XDG_CONFIG_HOME"
python3 "$ROOT/tests/check-recovered-nozzle-data.py" | tee "$RESULT_DIR/data-validation.log"
cat > "$WORK/test.resc" <<SCRIPT
include @$ROOT/peripherals/AT32F403A_System.cs
mach create
machine LoadPlatformDescription @$ROOT/tests/recovered-nozzle-curve.repl
include @$ROOT/scripts/virtual-nozzle-recovered-ntc.resc
include @$ROOT/tests/RecoveredNozzleCurveVectors.cs
include @$ROOT/tests/RecoveredNozzleCurveTests.cs
machine LoadPlatformDescription @$ROOT/tests/recovered-nozzle-curve-checks.repl
sysbus.thermalChecks Run
emulation RunFor "0.1"
sysbus.thermalChecks CheckUnconnectedTimer
sysbus.virtualNozzleNTC ColdReset
sysbus.virtualNozzleNTC OnGPIO 0 true
emulation RunFor "0.0025"
sysbus.virtualNozzleNTC OnGPIO 0 false
emulation RunFor "0.0075"
sysbus.thermalChecks CheckPWM
quit
SCRIPT
cd "$ROOT"
timeout 90 "$RENODE" --disable-xwt --console "$WORK/test.resc" 2>&1 | tee "$RESULT_DIR/renode.log"
grep -q 'RECOVERED NOZZLE CURVE TESTS PASS:' "$RESULT_DIR/renode.log"
grep -q 'RECOVERED NOZZLE UNCONNECTED TIMER PASS' "$RESULT_DIR/renode.log"
grep -q 'RECOVERED NOZZLE SYNTHETIC PWM PASS' "$RESULT_DIR/renode.log"
