# Timer and compare clock consistency

The bundled Renode 1.17 `STM32_Timer` inherits the parent `LimitTimer.Frequency`
setter without propagating frequency changes to its four private capture/compare
`LimitTimer` instances. A timer constructed at 8 MHz and subsequently clocked at
120 MHz by CRM therefore used 120 MHz for overflow and 8 MHz for compare events.
This was reproduced in the recovered snapshot, with the explicit failing assertion
`compare clock must match parent: 8000000 vs 120000000`.

`AT32Timer.Frequency` now updates the parent and all four compare clocks. CRM uses
the concrete timer property, rather than the inherited property on its
`STM32_Timer` reference. Observer notifications bracket the clock change. Reset
resynchronizes the compare clocks to the parent's reset frequency and leaves the
existing AT32 zero-period, disabled reset behavior intact.

The Renode compare channels are private. The adapter binds their timer references
once using a narrowly scoped reflection bridge, checks the expected four-channel
layout, and fails explicitly if the bundled runtime layout changes. This is a
version-specific compatibility measure, not a general upstream timer fix. Code
that changes an AT32 timer clock must use its concrete `Frequency` property (or
the corrected CRM path), not cast it to `LimitTimer`/`STM32_Timer` first.

Run `tests/run-timer-frequency.sh` (or set `RENODE` and `RENODE_HOME` for another
installation). The 30 checks cover:

- Initial parent/compare clocks at 8 MHz.
- CRM attachment and switch to an illustrative 120 MHz timer clock.
- All four compare events after 50 microseconds, absent at 25 and present at 75.
- A live switch to 60 MHz preserving parent enable and counter state.
- Rearmed compare events after 100 microseconds, absent at 50 and present at 125.
- Reset clock consistency and disabled state.

Existing motor-trigger tests also pass (31 checks). These are emulator-only tests;
no firmware image, firmware state, protection guard, or physical motor is changed.
The clock values test model consistency and do not establish the actual board's
oscillator, PLL encoding, or clock speed.
