#!/bin/sh
# Diagnostic original application startup, not a full printer boot.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ROOT=$(dirname "$HERE")
: "${DISK:?Set DISK to the offline-profile raw disk image}"
: "${MCU_IMAGE:?Set MCU_IMAGE to mcu_firmware_v1.3.3_20260311.bin}"
exec python3 "$HERE/scripts/run_link.py" \
 --qemu "$ROOT/rv1106-qemu/bin/qemu-system-arm-emmc" \
 --rv-image "$ROOT/rv1106-linux-emmc/linux-test.elf" \
 --cpu cortex-a7,has_el3=off --disk "$DISK" \
 --mcu-image "$MCU_IMAGE" --mcu-base 0x08004000 \
 --rv-uart 3 --mcu-uart usart1 --timeout 40 \
 --console-commands "$HERE/tests/native-main.commands" "$@"
