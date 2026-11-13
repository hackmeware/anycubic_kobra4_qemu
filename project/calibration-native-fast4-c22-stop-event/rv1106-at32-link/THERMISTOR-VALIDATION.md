# Thermistor environment and original-firmware protection

The explicit profiles feed modeled ADC inputs; they do not patch firmware,
change temperature limits, suppress shutdowns, or pretend a real sensor exists.
No heater or fan output is connected to these thermal objects yet. Physical
heater GPIO roles and closed-loop heating behavior remain unverified.

## Mapping established from actual native host configuration

- **Hotend:** original nozzle v1.2.9, OID10, ADC1 channel0 / PA0. Eight-sample
  sum must remain 962–32593. Native UI names its failure “Extruder NTC error”,
  code 10124. Current zero input produced the original firmware's shutdown 25.
- **Hotbed:** original main v1.3.3, OID18, ADC1 channel8 / PB0. Eight-sample
  sum must remain 15205–32309. Native UI names its failure “Hotbed NTC error”,
  code 10123. The original firmware likewise reports shutdown 25.

Mappings were recovered from each actual MCU's configured SRAM objects and
cross-checked against native UI error text, not inferred from adjacent pins.
The parsers are version-specific and included in the model packages. Raw MCU
and Linux RAM dumps are private diagnostics and should not be distributed.

## Explicit normal input

The opt-in thermal environment uses an illustrative 100kΩ/B3950 thermistor with
4.7kΩ pull-up, initialized to 25°C. That model supplies raw ADC 3911, giving an
eight-sample sum 31288 inside both native configured ranges. The curve and circuit
values are **not independently recovered PCB calibration**. Model temperature
is therefore not a claim about calibrated physical temperature.

Profiles:
- Main: `include @scripts/virtual-bed-ntc.resc`
- Nozzle: `include @scripts/virtual-nozzle-ntc.resc`

The normal combined test at `test-results/combined-normal-thermistors/` initializes
both MCUs without either NTC shutdown. It then stops in original host startup on
`Timeout waiting for response (msgtag=-4)` following TMC stepper_x initialization.
That remaining peripheral/protocol blocker is not hidden by the thermal profile.

## Fault experiments

Run with original firmware paths and the offline raw disk:

```
python3 tests/run_sensor_faults.py --disk /path/offline.img \
  --main /path/mcu_firmware_v1.3.3_20260311.bin \
  --nozzle /path/nozzle_firmware_v1.2.9_20260120.bin
```

The runner boots fresh original host/main/nozzle firmware for each case,
keeps the other sensor normal, injects short(raw 0) or open(raw 4095) into the
external thermal environment, and requires both the native MCU shutdown 25 and
correct native host error 10123/10124. The observed model raw ADC value is also
checked. Thresholds and firmware remain unchanged; QEMU snapshot mode protects
all original disk files from writes.

The authoritative completed result is `test-results/sensor-fault-summary.json`.
Per-case evidence is in `fault-nozzle-short`, `fault-nozzle-open`,
`fault-bed-short`, and `fault-bed-open`. These tests validate modeled failure
handling, not physical wiring, component accuracy, or a safety certification.
