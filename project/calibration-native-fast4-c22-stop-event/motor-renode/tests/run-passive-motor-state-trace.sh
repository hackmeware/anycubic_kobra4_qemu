#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RENODE=${RENODE:-"$ROOT/../at32-runtime/renode_1.17.0-portable/renode"}
mkdir -p "$ROOT/tests/results/passive-observer"
OUT=$(mktemp -d "$ROOT/tests/results/passive-observer/run-XXXXXX")
mkdir "$OUT/config"
sed "s|__TRACE_PATH__|$OUT/trace.csv|g" "$ROOT/tests/passive-motor-state-trace.resc" > "$OUT/test.resc"
cd "$ROOT"
XDG_CONFIG_HOME="$OUT/config" "$RENODE" --disable-xwt --console "$OUT/test.resc" > "$OUT/test.log" 2>&1
cat "$OUT/test.log"
grep -q 'PASSIVE MOTOR OBSERVER TESTS PASS: 20' "$OUT/test.log"
printf 'Evidence directory: %s\n' "$OUT"
