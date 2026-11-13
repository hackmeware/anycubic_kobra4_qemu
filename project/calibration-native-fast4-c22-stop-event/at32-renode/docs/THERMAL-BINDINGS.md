# Commanded thermal bindings: evidence and limits

> Status update, 2026-11-05: the sections below preserve the earlier investigation. The nozzle gap described there has since been partially resolved. The recovered custom NTC curve and optional `nozzle-renode/scripts/native-nozzle-heater-binding.resc` bind actual resolved PB8 output to the thermal plant. In `runs/native-home-x-heater`, the unchanged native firmware generated 81 PB8 pulses after normal target-35 input, producing 25 → 32.807070 °C, then cooled after normal target-0 input. PB9 remains observed but thermally unbound. Independent PWM replay agreed within 0.000002 °C. This proves that low-temperature response only: target 35 was stopped before being reached; high-temperature control, PID calibration, bed closed-loop control and complete print readiness are not established. The synthetic 40 W / 20 J K⁻¹ / 0.2 W K⁻¹ nozzle parameters imply a 225 °C equilibrium at full duty and 25 °C ambient, so they cannot sustain a 230 °C request. Do not treat these illustrative parameters as measured Kobra4 hardware properties. See the verified `native-x-home-and-heating-final-v2-20261105.tar.gz` checkpoint, SHA256 `cf93715b1f041b619f585763d5acd42e119fc0c81beb7fc755a7993fd5f38d4a`.

The optional `platforms/virtual-commanded-bed.repl` connects the main MCU's PA0 electrical output to the existing `virtualBedNTC` plant. Load it **after** `virtual-bed-ntc.repl`. No nozzle heater binding is currently provided.

## Main bed: command-correlated mapping

Source experiment: `rv1106-at32-link/test-results/three-mcu-heater-trace/`, using original native application commands and unchanged MCU firmware. The host started a file containing M140 S35, G4 P3000, M140 S0, M400. Host logging recorded target 35 at guest 43.937 s and target0 at 45.209 s. These host timestamps and MCU clocks are separate, so they are not directly subtracted.

The marked bed-only interval in the main trace begins around 70.6448 s and ends 99.4911 s. Within it PA0 rises at 72.888149 s and falls at 74.388149 s: exactly 1.500 s active high. Its configuration nibble is 1, a general-purpose push-pull output. It remains low during the subsequent nozzle-only probe. The captured runtime configuration independently identifies heater_pin PA0 and sensor_pin PB0, matching the previously proven ADC1 channel 8 input.

This establishes a command-correlated **emulated** bed output. It does not establish physical board behavior or accuracy of the chosen 200 W / 600 J/K / 1.5 W/K thermal parameters. The runtime sensor type is `NTC 100K beta 3950`; the 4.7k divider pullup and physical sensor calibration remain unverified.

## Nozzle: heater activation not yet established, no binding

Runtime configuration identifies heater_pin `nozzle_mcu:PB8`, sensor_pin `nozzle_mcu:PA0`, and custom sensor type `NTC ZM3863 HNS112HC4570G0`. The current generic 100k/B3950 model is illustrative and does not reproduce that custom sensor's recovered calibration, which is not yet available.

During the independent native M104 S35/0 experiment, PB8 remains low with general-purpose-output configuration 1. Instead PB9 rises at 97.420655 s and falls at 100.385913 s in the nozzle's clock: 2.965258 s active. This is command-correlated but does not on its own distinguish a heater output from an associated fan or firmware pin-encoding issue. The illustrative sensor curve may cause the host to interpret ambient above 35 C, yielding no heater demand while an associated fan activates. Actual interpreted temperature or a higher-target probe is needed. Neither PB8 nor PB9 is connected to the thermal plant pending that distinction. Absence of a nozzle thermal response is a disclosed remaining gap, not a successful closed-loop test.

## Artifacts and reproducibility

- `tools/extract_thermal_config_evidence.py`: extracts only relevant page-local STL string nodes from the existing runtime capture, validating key/type.
- `docs/thermal-runtime-config-evidence.json`: source SHA256, precise offsets, sensor/pin values and limits.
- `peripherals/VirtualGPIOTrace.cs` and `tests/run-gpio-trace.sh`: timestamped passive tracing and tested multiple-sink behavior.
- `tests/run-commanded-bed.sh`: synthetic electrical-wiring regression against the actual GPIO, ADC and thermal peripheral. This regression is separate from the native-command evidence above.

Fault injection and MCU-reset heat retention remain active with the binding. The environmental maximum/latch is a simulation limit, not firmware safety validation.
