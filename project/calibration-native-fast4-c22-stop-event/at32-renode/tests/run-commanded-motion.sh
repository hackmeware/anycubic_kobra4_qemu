#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RENODE=${RENODE:-"${RENODE_RUNTIME:-$ROOT/../at32-runtime}/run-renode"}
mkdir -p "$ROOT/tests/results"
SCRIPT=$(mktemp --suffix=.resc)
trap 'rm -f "$SCRIPT"' EXIT
cat > "$SCRIPT" <<RESC
include @$ROOT/peripherals/AT32F403A_IO.cs
include @$ROOT/peripherals/VirtualStepperCommandObserver.cs
include @$ROOT/tests/CommandedMotionTests.cs
mach create
machine LoadPlatformDescription @$ROOT/tests/commanded-motion.repl
sysbus.tests Run
sysbus.observer WriteCsv "$ROOT/tests/results/commanded-motion.csv"
quit
RESC
"$RENODE" --disable-xwt --console "$SCRIPT" 2>&1 | tee "$ROOT/tests/results/commanded-motion.log"
grep -q 'COMMANDED MOTION TESTS PASS' "$ROOT/tests/results/commanded-motion.log"
