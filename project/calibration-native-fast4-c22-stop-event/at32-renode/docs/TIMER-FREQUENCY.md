# Main MCU timer compare clock consistency

The bundled Renode 1.17 STM32_Timer inherits a parent Frequency setter that does
not update its four private capture/compare timers. Every main MCU timer starts
at 8 MHz. A read-only boot probe with the original main firmware at 0x08004000 and
the existing 24 MHz HEXT profile confirmed all 14 parents at 120 MHz but all 56
compare clocks still at 8 MHz after 0.2 seconds of virtual time.

The main AT32Timer now exposes a concrete Frequency setter that updates both
parent and compare clocks. CRM dispatches to that concrete setter rather than
the inherited STM32_Timer setter. Reset resynchronizes all compare clocks.
The bridge binds Renode's private four-channel layout once and fails explicitly
if that layout is incompatible. Code must change clocks through the concrete
AT32Timer property or corrected CRM path, not a cast to the base timer type.

Only clock propagation was ported from the motor adapter. Main's original
zero-period reset, disabled reset state, 16-bit masking, TMR2/TMR5 plus-mode and
mode-clear truncation behavior remain unchanged. No motor trigger routing,
electrical observers, PWM tagging, firmware state writes or safety changes were
added. No nozzle files were changed.

Validation:

- tests/run-timer-frequency.sh: 30 clock/timing assertions. At 120 MHz, compare
  events on all four channels are absent at 25 us and present at 75 us for a
  6000-tick compare. At 60 MHz, they are absent at 50 us and present at 125 us.
  The suite exercises the actual CRM attachment path, direct live frequency
  changes, enable/counter preservation and reset clock consistency.
- The same runner executes 16 main adapter semantics assertions, mirroring the
  existing timer-adapter.robot cases without requiring Robot dependencies.
- Existing tests/run-system.sh: 51 assertions passed.
- Original main firmware boot probe: all 14 parents and all 56 compare timers
  now report 120 MHz. At this pre-host-configuration stage all timers are still
  disabled, so the probe does not establish an active output improvement.

This is a model consistency correction, not a measured physical-board clock.
It does not establish a fix for native TMC CRC failures, UART transport latency,
DWT behavior, or independent QEMU/Renode clock synchronization. Full native
calibration replay is separate validation.
