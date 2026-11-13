#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RENODE=${RENODE:-"${RENODE_RUNTIME:-$ROOT/../at32-runtime}/run-renode"}
mkdir -p "$ROOT/tests/results"
LOG="$ROOT/tests/results/mechanics.log"
"$RENODE" --disable-gui --console --execute "include @$ROOT/peripherals/VirtualPrinterMechanics.cs; include @$ROOT/tests/MechanicsTests.cs; mach create; machine LoadPlatformDescriptionFromString \"mechanicsTests: AT32Tests.MechanicsTests @ sysbus\"; sysbus.mechanicsTests Run; quit" 2>&1 | tee "$LOG"
grep -q 'MECHANICS TESTS PASS: 25' "$LOG"
