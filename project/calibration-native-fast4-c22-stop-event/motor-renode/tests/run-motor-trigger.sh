#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RENODE=${RENODE:-"$ROOT/../at32-runtime/run-renode"}
mkdir -p "$ROOT/tests/results"
cd "$ROOT"
"$RENODE" --disable-xwt --console tests/motor-trigger.resc 2>&1 | tee tests/results/motor-trigger.log
grep -q 'MOTOR TRIGGER TESTS PASS: 31' tests/results/motor-trigger.log
