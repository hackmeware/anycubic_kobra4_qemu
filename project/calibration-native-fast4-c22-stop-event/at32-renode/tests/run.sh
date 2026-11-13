#!/usr/bin/env bash
set -euo pipefail
export TMPDIR=$(mktemp -d "${TMPDIR:-/tmp}/at32-renode.XXXXXX")
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RUNTIME=${RENODE_RUNTIME:-"$ROOT/../at32-runtime"}
export HOME="${RENODE_HOME:-$RUNTIME/home}"
export XDG_CONFIG_HOME="$HOME/.config"
export PATH="$RUNTIME/venv/bin:$PATH"
RENODE_TEST=${RENODE_TEST:-"$RUNTIME/renode_1.17.0-portable/renode-test"}
mkdir -p "$ROOT/tests/results" "$XDG_CONFIG_HOME"
cd "$ROOT/tests/results"
exec "$RENODE_TEST" "$ROOT/tests/smoke.robot" "$@" --variable "MODEL_ROOT:$ROOT"
