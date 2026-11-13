#!/usr/bin/env bash
# All generic suites, with optional uploaded application image as the first arg.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
if [[ $# -gt 1 ]]; then echo "Usage: $0 [path/to/mcu_firmware_v1.3.3_20260311.bin]" >&2; exit 2; fi
mkdir -p "$ROOT/tests/results"
"$ROOT/tests/run.sh" "$ROOT/tests/extras.robot" "$ROOT/tests/timer-adapter.robot"
python3 "$ROOT/tests/run-io.py" | tee "$ROOT/tests/results/io.log"
python3 "$ROOT/tests/run-dma.py" | tee "$ROOT/tests/results/dma.log"
bash "$ROOT/tests/run-bus.sh"
bash "$ROOT/tests/run-system.sh"
bash "$ROOT/tests/run-thermal.sh"
bash "$ROOT/tests/run-mechanics.sh"
bash "$ROOT/tests/run-observer.sh"
bash "$ROOT/tests/run-commanded-motion.sh"
python3 "$ROOT/tests/test_observer_render.py"
if [[ $# -eq 1 ]]; then "$ROOT/tests/run-user-firmware.sh" "$1"; fi
printf '\nALL REQUESTED TEST SUITES PASSED\n'
