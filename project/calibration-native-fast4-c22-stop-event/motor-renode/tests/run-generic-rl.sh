#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RENODE=${RENODE:-"$ROOT/../at32-runtime/run-renode"}
mkdir -p "$ROOT/tests/results"
cd "$ROOT"
"$RENODE" --disable-xwt --console tests/generic-rl-tests.resc > tests/results/generic-rl-unit.log 2>&1
grep 'GENERIC RL TESTS PASS:' tests/results/generic-rl-unit.log
! grep -Eq 'Error|Exception|There was an error' tests/results/generic-rl-unit.log
