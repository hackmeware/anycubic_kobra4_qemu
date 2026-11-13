# Nozzle timer clock consistency

The original nozzle image runs with a modeled 72 MHz core and TIM4 clock, while
stock Renode 1.17 STM32_Timer left all four private compare clocks at their
constructor's 8 MHz. A read-only original-firmware boot probe reproduced that
mismatch. The parent timer count/overflow and compare events therefore used
different time scales.

Nozzle.ClockedSTM32Timer is a minimal subclass of STM32_Timer. Its only behavior
addition is propagating its concrete Frequency setter to the four private compare
timers and resynchronizing clocks after the stock Reset. It does not override
register reads/writes, set AT32 reset ARR=0, add plus-mode, introduce motor trigger
routing, or alter firmware state. The existing platform's initialLimit=0xFFFF
and all inherited STM32 register behavior remain in place. CRM now dispatches to
the concrete Frequency property, and the platform/load script selects/includes
the adapter.

Renode exposes no public compare clock setter. The compatibility bridge binds its
private four-channel layout once and fails explicitly on an incompatible layout.
Use the concrete adapter property or corrected CRM path for clock changes; a
base-class cast bypasses this bridge.

Validation on bundled Renode 1.17:

- tests/run-timer-frequency.sh: 33 assertions. CRM switch to 72 MHz reaches all
  channels. Compare=3600 has no event at 25 us and all four events by 75 us. After
  a live switch to 36 MHz and rearming, no event at 50 us and all four by 125 us.
  Live changes preserve enable/count; reset clocks agree at 8 MHz, the timer is
  disabled, ARR is 65535, and control/prescaler are zero.
- tests/run-firmware-clock.sh /path/to/nozzle.bin: 9 assertions on the original
  SHA256-checked image, mirroring the existing Robot boot/clock and timer update
  checks without requiring Robot. Checks idle PC, fault registers, vector table,
  UART baud, 72 MHz system clock, DWT delta 7200000 over 0.1s and timer overflow.
  This tests the ordinary synthetic-zero-config boot, not the separate erased
  config-prefix branch of nozzle.robot. No input firmware is modified.
- Existing tests/tmc.resc: 16 TMC checks and GPIO waveform pass.
- Original-firmware probe after 0.2s: parent and all four compare clocks at 72 MHz,
  ARR=65535 and timer disabled before host configuration.

This fixes a demonstrated internal clock mismatch only. It does not establish a
fix for native TMC CRC failures or independent QEMU/Renode clock drift. PWM pin
routing to a physical heater or fan remains unmodeled; no thermal drive or
physical-board clock measurement is inferred. No hardware was used.
