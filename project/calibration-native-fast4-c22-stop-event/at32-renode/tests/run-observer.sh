#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RENODE=${RENODE:-"${RENODE_RUNTIME:-$ROOT/../at32-runtime}/run-renode"}
mkdir -p "$ROOT/tests/results"
SCRIPT=$(mktemp --suffix=.resc)
trap 'rm -f "$SCRIPT"' EXIT
cat > "$SCRIPT" <<RESC
include @$ROOT/peripherals/AT32F403A_System.cs
include @$ROOT/peripherals/VirtualPrinterThermal.cs
include @$ROOT/peripherals/VirtualPrinterMechanics.cs
include @$ROOT/peripherals/VirtualPrinterObserver.cs
include @$ROOT/tests/ObserverTests.cs
mach create
machine LoadPlatformDescription @$ROOT/tests/observer.repl
sysbus.tests Drive
emulation RunFor "1"
sysbus.tests Check
sysbus.observer WriteCsv "$ROOT/tests/results/observer.csv"
sysbus.tests Restart
emulation RunFor "2"
sysbus.tests CheckCapacity
quit
RESC
"$RENODE" --disable-xwt --console "$SCRIPT" 2>&1 | tee "$ROOT/tests/results/observer.log"
grep -q 'OBSERVER TESTS PASS' "$ROOT/tests/results/observer.log"
grep -q 'OBSERVER CAPACITY PASS' "$ROOT/tests/results/observer.log"
python3 "$ROOT/tools/render_virtual_print.py" "$ROOT/tests/results/observer.csv" "$ROOT/tests/results/observer.html"
