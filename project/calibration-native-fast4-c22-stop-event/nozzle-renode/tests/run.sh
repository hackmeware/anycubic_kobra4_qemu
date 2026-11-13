#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 1 ]];then echo "Usage: $0 /path/nozzle_firmware_v1.2.9_20260120.bin" >&2;exit 2;fi
ROOT=$(cd "$(dirname "$0")/.." && pwd)
FW=$(realpath "$1")
RUNTIME=${RENODE_RUNTIME:-"$ROOT/../at32-runtime"}
export HOME=${RENODE_HOME:-"$RUNTIME/home"}
export XDG_CONFIG_HOME="$HOME/.config"
export TMPDIR=$(mktemp -d /tmp/nozzle-test.XXXXXX)
export PATH="$RUNTIME/venv/bin:$PATH"
mkdir -p "$ROOT/tests/results" "$XDG_CONFIG_HOME"
cd "$ROOT/tests/results"
exec "${RENODE_TEST:-$RUNTIME/renode_1.17.0-portable/renode-test}" "$ROOT/tests/nozzle.robot" --variable "MODEL_ROOT:$ROOT" --variable "NOZZLE_FIRMWARE:$FW" --save-logs always
