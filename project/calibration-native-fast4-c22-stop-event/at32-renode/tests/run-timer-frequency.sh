#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RENODE=${RENODE:-"$ROOT/../at32-runtime/renode_1.17.0-portable/renode"}
export HOME=${RENODE_HOME:-"$ROOT/../at32-runtime/home"}
export XDG_CONFIG_HOME="$HOME/.config"
mkdir -p "$ROOT/tests/results"
cd "$ROOT"
"$RENODE" --disable-xwt --console tests/timer-frequency.resc 2>&1 | tee tests/results/timer-frequency.log
grep -q 'TIMER FREQUENCY TESTS PASS: 30' tests/results/timer-frequency.log
"$RENODE" --disable-xwt --console tests/main-timer-semantics.resc 2>&1 | tee tests/results/main-timer-semantics.log
grep -q 'MAIN TIMER SEMANTICS TESTS PASS: 16' tests/results/main-timer-semantics.log
