#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 1 ]]; then echo "Usage: $0 /absolute/path/to/mcu_firmware_v1.3.3_20260311.bin" >&2; exit 2; fi
FIRMWARE=$(realpath "$1")
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RUNTIME=${RENODE_RUNTIME:-"$ROOT/../at32-runtime"}
export HOME="${RENODE_HOME:-$RUNTIME/home}"
export XDG_CONFIG_HOME="$HOME/.config"
export TMPDIR=$(mktemp -d "${TMPDIR:-/tmp}/at32-user.XXXXXX")
export PATH="$RUNTIME/venv/bin:$PATH"
RENODE_TEST=${RENODE_TEST:-"$RUNTIME/renode_1.17.0-portable/renode-test"}
mkdir -p "$ROOT/tests/user-results" "$XDG_CONFIG_HOME"
cd "$ROOT/tests/user-results"
exec "$RENODE_TEST" "$ROOT/tests/user_firmware.robot" --variable "MODEL_ROOT:$ROOT" --variable "USER_FIRMWARE:$FIRMWARE" --save-logs always
