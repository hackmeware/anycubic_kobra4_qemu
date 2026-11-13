#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 1 ]]; then echo "Usage: $0 /path/to/nozzle.bin" >&2; exit 2; fi
ROOT=$(cd "$(dirname "$0")/.." && pwd)
FW=$(realpath "$1")
EXPECTED=ae09264667ff4a72905706026b1591bdede91e1f250755319fec531328e54e2f
[[ $(sha256sum "$FW" | cut -d ' ' -f 1) == "$EXPECTED" ]] || { echo "Unexpected nozzle firmware SHA256" >&2; exit 2; }
# A simple temporary symlink avoids monitor tokenization of user path characters.
INPUT_DIR=$(mktemp -d /tmp/nozzle-fw-clock.XXXXXX)
trap 'rm -f "$INPUT_DIR/firmware.bin"; rmdir "$INPUT_DIR"' EXIT
ln -s "$FW" "$INPUT_DIR/firmware.bin"
RENODE=${RENODE:-"$ROOT/../at32-runtime/renode_1.17.0-portable/renode"}
export HOME=${RENODE_HOME:-"$ROOT/../at32-runtime/home"}
export XDG_CONFIG_HOME="$HOME/.config"
mkdir -p "$ROOT/tests/results"
cd "$ROOT"
"$RENODE" --disable-xwt --console --execute "\$bin=@$INPUT_DIR/firmware.bin; include @tests/nozzle-firmware-clock.resc" 2>&1 | tee tests/results/nozzle-firmware-clock.log
grep -q 'NOZZLE FIRMWARE CLOCK TESTS PASS: 9' tests/results/nozzle-firmware-clock.log
