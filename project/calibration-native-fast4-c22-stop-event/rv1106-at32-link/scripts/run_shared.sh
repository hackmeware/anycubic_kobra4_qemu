#!/bin/sh
# Verified native three-MCU shared-time profile. QEMU remains independently timed.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
: "${MOTOR_IMAGE:?Set MOTOR_IMAGE to the original motor MCU binary}"
exec "$HERE/scripts/run_combined.sh" --shared-mcus --motor-image "$MOTOR_IMAGE" \
 --nozzle-setup-commands "$HERE/tests/nozzle-ntc-tmc.commands" "$@"
