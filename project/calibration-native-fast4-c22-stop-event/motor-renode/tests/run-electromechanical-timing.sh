#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RENODE=${RENODE:-"$ROOT/../at32-runtime/run-renode"}
mkdir -p "$ROOT/tests/results/electromechanical"
cd "$ROOT"
SCRIPT=$(mktemp --suffix=.resc)
trap 'rm -f "$SCRIPT"' EXIT
sed "s|__TRACE_PATH__|$ROOT/tests/results/electromechanical/timing.csv|g" tests/generic-electromechanical-timing.resc > "$SCRIPT"
"$RENODE" --disable-xwt --console "$SCRIPT" 2>&1 | tee tests/results/electromechanical/timing.log
grep -q 'ELECTROMECHANICAL TIMING TESTS PASS: 8' tests/results/electromechanical/timing.log
