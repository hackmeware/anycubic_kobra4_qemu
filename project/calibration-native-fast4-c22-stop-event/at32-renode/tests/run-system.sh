#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RUNTIME=${RENODE_RUNTIME:-"$ROOT/../at32-runtime"}
RENODE=${RENODE:-"$RUNTIME/run-renode"}
mkdir -p "$ROOT/tests/results"
LOG="$ROOT/tests/results/system.log"
"$RENODE" --disable-xwt --console --execute "include @$ROOT/peripherals/AT32F403A_System.cs; include @$ROOT/tests/SystemPeripheralTests.cs; mach create; machine LoadPlatformDescription @$ROOT/tests/system.repl; sysbus.systemTests Run; quit" 2>&1 | tee "$LOG"
grep -q 'SYSTEM TESTS PASS: 51' "$LOG"
