#!/usr/bin/env bash
set -euo pipefail
BASE=$(cd -- "$(dirname -- "$0")" && pwd)
OUT=${1:?New result directory required}
[[ ! -e "$OUT" ]] || { echo 'Refusing existing output' >&2; exit 1; }
mkdir -p "$OUT"
i=0
for mode in parallel serial serial parallel; do
 i=$((i+1))
 timeout --kill-after=5s 60s python "$BASE/benchmark.py" --mode "$mode" --output "$OUT/$i-$mode" >"$OUT/$i.stdout" 2>"$OUT/$i.stderr"
done
python "$BASE/compare.py" "$OUT"
