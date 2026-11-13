# Current verified state

2026-11-04, thermistor-enabled diagnostic baseline.

## Working together in one session

- Original RV1106 Linux kernel and original native main/UI applications.
- Main v1.3.3 firmware in the AT32 model, UART3, identified and initialized.
- Nozzle v1.2.9 firmware in a provisional F1-compatible model, UART0, identified
  and initialized. Exact physical nozzle chip remains unverified.
- Virtual-time 576000-baud host-to-MCU wire scheduling, hardware RX depth one.
- Explicit illustrative bed/nozzle thermistor environment inputs.
- Native framebuffer capture and optional live SDL viewer/touch input.
- Guest writes isolated in QEMU snapshot overlays. No external network adapter.

The combined profile intentionally uses 128 MiB RAM and a reduced diagnostic
DT. That is not a claim about physical RAM capacity or full board peripherals.

## Reproduce

From the directory containing all sibling emulator/model projects:

```
DISK=/path/to/kobra4-offline-gpt.img \
MCU_IMAGE=/path/to/mcu_firmware_v1.3.3_20260311.bin \
NOZZLE_IMAGE=/path/to/nozzle_firmware_v1.2.9_20260120.bin \
rv1106-at32-link/scripts/run_combined.sh
```

Default: a 75-second observation, raw UART logs, actual PPM framebuffer, then all
processes stop. Add `--live-display --timeout 3600` for a local SDL window for up
to an hour; `--live-display --live-headless` tests the live renderer without a
window. A desktop SDL window needs the system SDL2 library and graphical session.
Original firmware inputs are separate; this integration archive alone does not
contain them, QEMU, Renode, model projects, disk image, or the generated Linux ELF.

## Verified fault preservation

All four original-firmware experiments passed: nozzle open/short produces native
shutdown25 + host10124; bed open/short produces shutdown25 + host10123. The actual
model ADC values0/4095 were checked. No firmware instructions or safety limits
were changed. See THERMISTOR-VALIDATION.md and sensor-fault-summary.json.

## Remaining blocker and limits

Both normal thermistor inputs clear NTC errors, but native startup currently
fails waiting for a response (msgtag=-4), shortly after TMC stepper_x setup.
The actual screen says “Unknown error occurred”. This package deliberately
preserves that real failure instead of pretending the printer is ready.

No completed virtual print, homing, stepper response, heater-control loop, actual
motion, physical sensor calibration, or hardware safety certification is claimed.
Heater/fan GPIOs are not yet connected to the illustrative thermal environment.
Residual clock mismatch warnings remain; this is not deterministic lockstep or
cycle-accurate simulation. Full details and historical evidence are retained in
REAL-APPLICATION.md and test-results/.
