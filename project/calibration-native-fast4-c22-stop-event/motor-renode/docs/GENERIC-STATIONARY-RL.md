# Generic stationary RL motor testbench

This optional component is an **explicitly assumed electrical testbench**, not a reconstruction of the exact printer board. It supplies physically evolved coil currents to the original motor firmware. It does not inspect firmware RAM, requested motor states, targets, fault masks or success thresholds. It does not clear faults or patch the image.

## Why model this boundary rather than a physical TMC2209

The [TMC2209 datasheet, revision1.09](https://www.analog.com/media/en/technical-documentation/data-sheets/TMC2209_datasheet_rev1.09.pdf) describes an integrated two-phase stepper driver with internal bridges/current regulation, STEP/DIR and UART interfaces. Its standard register protocol is useful evidence, but it does not have the four phase-PWM command inputs used by this motor MCU's local control loop.

The original motor firmware implements the UART register table itself. Its IHOLD_IRUN and CHOPCONF callbacks write local current-control configuration instead of forwarding to an external UART. See `TMC2209-ARCHITECTURE-ASSESSMENT.md` and `ELECTRICAL-PLANT-DESIGN.md`. This supports modeling the proven MCU PWM/current-ADC boundary while keeping bridge and analog parameters explicit assumptions. It does not establish every physical component on the board or imply that the hardware is exotic.

## Model and assumed defaults

Each of three axes has two stationary RL coils. Defaults were chosen before running firmware and were not adjusted to pass its checks:

|Parameter|Assumed value|
|---|---|
|DC bus voltage|24V|
|Winding resistance|2ohms|
|Winding inductance|0.003H|
|Current-to-ADC gain|500 counts/A|
|Zero-current offset|2048 counts|
|Rotor velocity/back-EMF|0|

`Configure` exposes these parameters and rejects non-finite or invalid values. These are illustrative generic values, not measured printer motor specifications.

- Motor0 uses TMR3 and ADC1 CH0/4; motor1 uses TMR1 and ADC2 CH5/6; motor2 uses TMR4 and ADC3 CH12/10.
- Four timer channels form two ideal differential bridge-input pairs. PWM modes6/7, forced active/inactive modes, output enable and polarity are read from actual timer registers. Timer disable and TMR1 MOE gate applied drive. Unmodeled waveform modes produce no invented drive.
- Average phase voltage is Vbus times the difference between the two pin high fractions. Within a held interval, current evolves analytically as Inew=V/R+(Iold-V/R)exp(-dtR/L).
- The generic ideal low-side sampling convention multiplies physical current by the first leg's polarity sign before ADC scaling. This is an explicit topology assumption consistent with the firmware's dynamically selected±1 correction, derived from actual CCER bits rather than reading those correction variables.
- Samples are rounded and clipped to0..4095; clipping is counted. There is no special-case current response based on firmware state or fault threshold.
- Electrical integration advances at actual drive-configuration changes and at the real, configured TMR8 TRGO. Only that TRGO invokes ADC triggering. ADC enable, selected trigger and interrupt behavior remain in the ADC model. The component wires TMR2→TMR1/TMR3/TMR4 IS1 and TMR1→TMR8 IS0.

## Use

After `scripts/load.resc` and the existing explicit `scripts/board-clock-and-rtc.resc`, load `scripts/generic-stationary-rl.resc`.

This is an **alternative** to `stationary-current-plant.resc` and `pwm-trigger-wiring.resc`. Do not load both sets: the generic component owns the trigger routing and ADC inputs. The stationary zero-current fixture remains unchanged and available as a negative baseline.

## Validation and observed firmware behavior

`tests/run-generic-rl.sh` passes26 assertions: exact RL step, gated differential voltage, current continuity on polarity reversal, disabled-drive decay, zero/low supply, open winding, MOE gating, ADC positive/negative clipping, reset, no autonomous sample clock, actual timer-trigger sampling and stopped-trigger silence. Four additional assertions cover a one-microsecond forced-inactive/polarity transient, same-timestamp writes and its correctly decayed current at the later ADC boundary.

The original user-provided firmware, loaded unchanged at0x08008000 with the existing24MHz/LICK assumptions, was run with the defaults above:

- At0.5s the three fault masks were0, all motors were still in state6 identification, and motor0 phase current was about2.055A.
- At1.0s all three fault masks remained0, all motor state bytes were0, PC was0x08018318, and phase current had decayed essentially tozero. Trigger count was29946; ADC clipping count was0.
- This replaces the stationary fixture's genuine no-current-response fault0x40 through ordinary feedback. It does not bypass the check.

The full trace is `tests/results/generic-rl-firmware.log`. `tests/run-generic-rl-firmware.sh` also runs zero-supply and open-winding fault fixtures, checks the original fault0x40 remains set for all motors, and checks current-offset calibration fault0x08 remains clear.

## Explicit limitations

- This uses averaged PWM within intervals bounded by actual timer configuration changes. Each axis integrates its cached old drive before a register mutation, then caches the new drive. ADC triggers advance the remaining interval. It is not a switching-edge/dead-time simulation; compare preload timing remains limited by the timer model.
- Zero applied voltage uses passive RL decay, an assumed braking/recirculation approximation, not a verified driver truth table.
- `OpenWinding` is a diagnostic ideal disconnection: current becomes zero immediately. It does not model stored inductive energy, arcing or clamp transients.
- MCU/peripheral reset currently resets stored coil energy. Real motor current would not necessarily vanish at MCU reset.
- Timer compare shadow/preload latching, complementary output/dead-time, break-input behavior and precise center-aligned switching remain limited by the timer model. The plant itself checks retained MOE, but that does not implement generic timer-pin MOE gating elsewhere.
- No rotor motion, encoder, back-EMF, load, endstop, thermal winding behavior or full printer physics is claimed. Fault-free stationary startup under an assumed electrical fixture is not evidence of verified physical printing or an exact board model.
