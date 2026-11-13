#!/usr/bin/env bash
# Independent bus tests executed inside Renode, with real child registrations.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RUNTIME=${RENODE_RUNTIME:-"$ROOT/../at32-runtime"}
RENODE=${RENODE:-"$RUNTIME/run-renode"}
mkdir -p "$ROOT/tests/results"
LOG="$ROOT/tests/results/bus.log"
"$RENODE" --disable-xwt --console --execute "include @$ROOT/peripherals/AT32F403A_Bus.cs; include @$ROOT/tests/BusPeripheralTests.cs; mach create; machine LoadPlatformDescription @$ROOT/tests/bus.repl; sysbus.busTests Run; quit" 2>&1 | tee "$LOG"
# Renode monitor errors do not necessarily produce a nonzero process exit code.
grep -q 'BUS TESTS PASS: 37' "$LOG"
