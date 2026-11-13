#!/usr/bin/env bash
# Explicit virtual fixture. No physical-machine calibration claim.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd)
NAME=${1:?Provide a new run name}
[[ "$NAME" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo 'Invalid run name' >&2; exit 1; }
GLOBAL_QUANTUM_US=${GLOBAL_QUANTUM_US:-10}
case "$GLOBAL_QUANTUM_US" in
 1) GLOBAL_QUANTUM_SECONDS=0.000001 ;;
 10) GLOBAL_QUANTUM_SECONDS=0.00001 ;;
 *) echo 'GLOBAL_QUANTUM_US must be 1 or 10' >&2; exit 1 ;;
esac
NOZZLE_TMC_MODEL=${NOZZLE_TMC_MODEL:-fixed}
case "$NOZZLE_TMC_MODEL" in
 fixed) ;;
 autobaud) [[ "$GLOBAL_QUANTUM_US" == 1 ]] || { echo 'Experimental autobaud requires GLOBAL_QUANTUM_US=1' >&2; exit 1; } ;;
 *) echo 'NOZZLE_TMC_MODEL must be fixed or autobaud' >&2; exit 1 ;;
esac
Z_PROBE_PROFILE=${Z_PROBE_PROFILE:-none}
case "$Z_PROBE_PROFILE" in
 none) ;;
 synthetic-functional) [[ "$GLOBAL_QUANTUM_US" == 1 ]] || { echo 'Synthetic Z requires explicit GLOBAL_QUANTUM_US=1' >&2; exit 1; } ;;
 *) echo 'Z_PROBE_PROFILE must be none or synthetic-functional' >&2; exit 1 ;;
esac
THERMAL_PROFILE=${THERMAL_PROFILE:-none}
case "$THERMAL_PROFILE" in
 none) ;;
 synthetic-calibration)
  [[ "$GLOBAL_QUANTUM_US" == 1 ]] || { echo 'Synthetic thermal profile requires explicit GLOBAL_QUANTUM_US=1' >&2; exit 1; }
  [[ "${NATIVE_NOZZLE_HEATER:-0}" == 0 ]] || { echo 'THERMAL_PROFILE owns the heater bindings; do not add NATIVE_NOZZLE_HEATER' >&2; exit 1; }
  ;;
 *) echo 'THERMAL_PROFILE must be none or synthetic-calibration' >&2; exit 1 ;;
esac
Z_PARAMETERS=(BED_RELATIVE_MM OPPOSITE_STOP_RELATIVE_MM BED_SIDE STIFFNESS_N_PER_MM DAMPING_NS_PER_MM BASELINE_COUNTS COUNTS_PER_N SIGNAL_POLARITY HISTORY_CAPACITY QUERY_TRACE_ROWS)
for PARAM in "${Z_PARAMETERS[@]}"; do
 KEY="Z_$PARAM"
 if [[ -v "$KEY" && "$Z_PROBE_PROFILE" == none ]]; then echo "$KEY requires explicit Z_PROBE_PROFILE=synthetic-functional" >&2; exit 1; fi
done
D="$ROOT/runs/$NAME"
[[ ! -e "$D" ]] || { echo 'Run directory already exists; refusing to overwrite evidence' >&2; exit 1; }
mkdir -p "$D"
touch "$D/console-input.commands" "$D/peer-monitor-input.commands"
printf 'pause\nmachine ElapsedVirtualTime\ndump_file 0x20000000 0x18000 @%s/final-main-sram.bin\n' "$D" > "$D/main-final.commands"
cat "$ROOT/rv1106-at32-link/tests/assumed-centered-xy-contact.commands" > "$D/motor-setup.commands"
if [[ "${PASSIVE_MOTOR_TRACE:-0}" == 1 ]]; then
 printf 'include @peripherals/PassiveMotorStateTrace.cs\nmachine LoadPlatformDescription @platforms/passive-motor-state-trace.repl\nsysbus.passiveMotorStateTrace Start "%s/motor-state.csv"\n' "$D" >> "$D/motor-setup.commands"
fi
if [[ "${PASSIVE_CONTACT_TRACE:-0}" == 1 ]]; then
 printf 'sysbus.electromechanicalPlant StartContactTrace "%s/contact-transitions.csv" 100000 true\n' "$D" >> "$D/motor-setup.commands"
 printf 'mach set "motor"\nsysbus.electromechanicalPlant StopContactTrace\nsysbus.electromechanicalPlant ContactRowsWritten\nsysbus.electromechanicalPlant ContactDroppedRows\nsysbus.electromechanicalPlant ContactLastError\nsysbus.electromechanicalPlant IntegrationCalls\nmach set "main"\n' >> "$D/main-final.commands"
fi
cp "$ROOT/rv1106-at32-link/tests/nozzle-ntc-tmc.commands" "$D/nozzle-setup.commands"
if [[ "${RECOVERED_NOZZLE_NTC:-0}" == 1 ]]; then
 printf 'include @scripts/virtual-nozzle-recovered-ntc.resc\ninclude @scripts/virtual-tmc2209.resc\n' > "$D/nozzle-setup.commands"
fi
EXTRA=(--nozzle-tmc-model "$NOZZLE_TMC_MODEL" --stop-request "$D/stop-request" --motor-enable-wiring "${MOTOR_ENABLE_WIRING:-direct-bridge-gate}")
if [[ "$THERMAL_PROFILE" != none ]]; then EXTRA+=(--thermal-profile "$THERMAL_PROFILE"); fi
if [[ "$Z_PROBE_PROFILE" != none ]]; then
 EXTRA+=(--z-probe-profile "$Z_PROBE_PROFILE")
 for PARAM in "${Z_PARAMETERS[@]}"; do
  KEY="Z_$PARAM"
  if [[ -v "$KEY" ]]; then OPTION="z-${PARAM,,}"; OPTION="${OPTION//_/-}"; EXTRA+=("--$OPTION" "${!KEY}"); fi
 done
fi
if [[ "${PASSIVE_NOZZLE_TRACE:-0}" == 1 && "$THERMAL_PROFILE" == none ]]; then
 printf 'include @scripts/passive-nozzle-thermal-observer.resc\nsysbus.passiveNozzleThermalObserver Start "%s/nozzle-thermal-live.csv"\n' "$D" >> "$D/nozzle-setup.commands"
 printf 'pause\nsysbus.passiveNozzleThermalObserver WriteCsv "%s/nozzle-thermal.csv"\nsysbus.passiveNozzleThermalObserver Stop\nsysbus.passiveNozzleThermalObserver WriteStreamStatus "%s/nozzle-thermal-live-status.json"\n' "$D" "$D" > "$D/nozzle-final.commands"
 EXTRA+=(--nozzle-final-commands "$D/nozzle-final.commands")
fi
if [[ "${PASSIVE_TMC_TRACE:-0}" == 1 ]]; then
 printf 'include @scripts/passive-tmc-timing-observer.resc\n' >> "$D/nozzle-setup.commands"
 printf 'pause\nsysbus.tmcTimingObserver WriteCsv "%s/nozzle-tmc-edges.csv"\nsysbus.tmcTimingObserver Dropped\n' "$D" >> "$D/nozzle-final.commands"
 if [[ "${PASSIVE_NOZZLE_TRACE:-0}" != 1 || "$THERMAL_PROFILE" != none ]]; then EXTRA+=(--nozzle-final-commands "$D/nozzle-final.commands"); fi
fi
if [[ "${NATIVE_NOZZLE_HEATER:-0}" == 1 ]]; then
 printf 'include @scripts/native-nozzle-heater-binding.resc\n' >> "$D/nozzle-setup.commands"
 printf 'pause\nsysbus.nativeNozzleHeaterBinding WriteStatus "%s/nozzle-heater-binding.json"\n' "$D" >> "$D/nozzle-final.commands"
 if [[ "${PASSIVE_NOZZLE_TRACE:-0}" != 1 && "${PASSIVE_TMC_TRACE:-0}" != 1 ]]; then EXTRA+=(--nozzle-final-commands "$D/nozzle-final.commands"); fi
fi
# Shared setup runs these commands before its initial RunFor. Keep the default
# scheduling resolution unchanged; 1us is an explicit experiment, not a clock fix.
printf 'emulation SetGlobalQuantum "%s"\n' "$GLOBAL_QUANTUM_SECONDS" >> "$D/nozzle-setup.commands"
cat > "$D/scheduling-experiment.json" <<JSON
{"global_quantum_us": $GLOBAL_QUANTUM_US, "global_quantum_seconds": "$GLOBAL_QUANTUM_SECONDS", "experimental": $([[ "$GLOBAL_QUANTUM_US" == 1 ]] && echo true || echo false), "scope": "Explicit scheduling and external TMC model selection", "clock_and_frequency_changes": false, "firmware_changes": false, "tmc_model_changes": $([[ "$NOZZLE_TMC_MODEL" == autobaud ]] && echo true || echo false), "tmc_model": "$NOZZLE_TMC_MODEL", "tmc_nominal_baud": 40000, "tmc_reply_baud": "$([[ "$NOZZLE_TMC_MODEL" == autobaud ]] && echo learned-per-datagram || echo fixed-40000)"}
JSON
if [[ "${PASSIVE_HOMING_GPIO:-0}" == 1 ]]; then EXTRA+=(--trace-homing-gpio); fi
if [[ "${ASSUMED_XY_DIAG_CABLE:-0}" == 1 ]]; then EXTRA+=(--assumed-xy-diag-cable); fi
cat >> "$D/main-final.commands" <<COMMANDS
mach set "main"
sysbus.gpioA ReadDoubleWord 0
sysbus.gpioA ReadDoubleWord 4
sysbus.gpioA ReadDoubleWord 8
sysbus.gpioA ReadDoubleWord 12
sysbus.gpioC ReadDoubleWord 0
sysbus.gpioC ReadDoubleWord 4
sysbus.gpioC ReadDoubleWord 8
sysbus.gpioC ReadDoubleWord 12
mach set "motor"
dump_file 0x20000000 0x18000 @$D/final-motor-sram.bin
sysbus.gpioB ReadDoubleWord 0
sysbus.gpioB ReadDoubleWord 4
sysbus.gpioB ReadDoubleWord 8
sysbus.gpioB ReadDoubleWord 12
dump_file 0x40000000 0x50 @$D/final-motor-tmr2.bin
dump_file 0x40000400 0x50 @$D/final-motor-tmr3.bin
dump_file 0x40012c00 0x50 @$D/final-motor-tmr1.bin
dump_file 0x40000800 0x50 @$D/final-motor-tmr4.bin
mach set "main"
COMMANDS
if [[ "${PASSIVE_HOMING_GPIO:-0}" == 1 ]]; then
 printf 'mach set "main"\nsysbus.homingEdges DroppedRows\nsysbus.homingEdges LastError\nmach set "motor"\nsysbus.homingEdges DroppedRows\nsysbus.homingEdges LastError\nmach set "main"\n' >> "$D/main-final.commands"
fi
source "$ROOT/build-deps/env.sh"
export HOME="$ROOT/at32-runtime/home" XDG_CONFIG_HOME="$ROOT/at32-runtime/home/.config"
export DISK="$ROOT/inputs/offline-emmc.img" MCU_IMAGE="$ROOT/inputs/mcu.bin" NOZZLE_IMAGE="$ROOT/inputs/nozzle.bin"
exec "$ROOT/rv1106-at32-link/scripts/run_combined.sh" \
 --qemu "${QEMU_BINARY:-$ROOT/evidence/exact-generic-timer/exact24-runtime/run-qemu-system-arm-exact24}" \
 --renode "$ROOT/at32-runtime/renode_1.17.0-portable/renode" \
 --motor-image "$ROOT/inputs/motor.bin" --shared-mcus --motor-plant electromechanical-driver \
 --motor-setup-commands "$D/motor-setup.commands" \
 --nozzle-setup-commands "$D/nozzle-setup.commands" \
 --clock-coupled --clock-source qom-deadline --clock-lockstep --qemu-icount-shift "${ICOUNT_SHIFT:-0}" \
 --console-commands "$ROOT/rv1106-at32-link/tests/native-main-startup.commands" --timeout "${RUN_SECONDS:-600}" \
 --console-input "$D/console-input.commands" \
 "${EXTRA[@]}" --mcu-final-commands "$D/main-final.commands" --log-dir "$D" --screenshot "$D/display.ppm" \
 >"$D/launcher.log" 2>&1
