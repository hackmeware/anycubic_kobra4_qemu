#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RENODE=${RENODE:-"$ROOT/../at32-runtime/run-renode"}
mkdir -p "$ROOT/tests/results/electromechanical"
cd "$ROOT"
"$RENODE" --disable-xwt --console tests/generic-electromechanical-tests.resc 2>&1 | tee tests/results/electromechanical/equations.log
grep -q 'ELECTROMECHANICAL EQUATION TESTS PASS: 24' tests/results/electromechanical/equations.log
