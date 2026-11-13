#!/bin/sh
# Explicit 128MiB diagnostic, native UI + original main/nozzle firmwares.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ROOT=$(dirname "$HERE")
: "${DISK:?Set DISK to the offline-profile raw disk image}"
: "${MCU_IMAGE:?Set MCU_IMAGE to the original main MCU binary}"
: "${NOZZLE_IMAGE:?Set NOZZLE_IMAGE to the original nozzle MCU binary}"
# Headless readiness must not introduce an independent screenshot HMP stop.
if [ "${HEADLESS_READY_ONLY:-0}" != 1 ]; then
 set -- --screenshot "$HERE/test-results/combined/display.ppm" "$@"
fi
exec python3 "$HERE/scripts/run_link.py" \
 --qemu "$ROOT/rv1106-qemu/bin/qemu-system-arm-display" \
 --rv-image "$ROOT/rv1106-linux-display-128diag/linux-test.elf" \
 --memory 128 --cpu cortex-a7,has_el3=off --disk "$DISK" \
 --mcu-image "$MCU_IMAGE" --mcu-base 0x08004000 --mcu-hext 24000000 --rv-uart 3 \
 --nozzle-image "$NOZZLE_IMAGE" --virtual-baud 576000 --timeout 75 \
 --mcu-setup-commands "$HERE/tests/main-virtual-ntc.commands" \
 --nozzle-setup-commands "$HERE/tests/nozzle-virtual-ntc.commands" \
 --console-commands "$HERE/tests/main-ui-rw.commands" \
 --renode-bootstrap "${RENODE_BOOTSTRAP:-legacy}" --clock-client "${CLOCK_CLIENT:-scalar}" \
 --log-dir "$HERE/test-results/combined" "$@"
