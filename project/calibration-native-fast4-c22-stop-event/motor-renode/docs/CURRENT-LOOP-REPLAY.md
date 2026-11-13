# Native current-loop replay and transient integration correction

The full native stack reported masks0x0810/0x0800/0: current fault0x10 on X in addition to timer/synchronization fault0x0800 on X/Y. Defaults and firmware safety thresholds were preserved while investigating. The controlled replay reproduces the same fault chain, with0x10 on both X/Y under its different arrival schedule; this is not evidence of identical sub-cycle timing to the live stack.

## Reproduction before correction

Capture: `rv1106-at32-link/test-results/three-mcu-electrical/main-motor-decoded.json`,404 frames. `tests/replay-native-current.py` replays those exact frame bytes through the timed576kbaud serial-wire adapter. The chosen deterministic2ms gaps are a controlled replay schedule, not a claim to preserve original wall-clock arrival timing. `CurrentLoopTrace.cs` is a read-only observer.

- First71 initialization frames, including all native TMC writes and cmd0x2f, followed by1.2s: fault masks remain0. X/Y complete state7 measurement; maximum absolute phase current is0.972A. This does not support blaming the requested TMC current settings.
- All404 frames, including cmd0x10 clock updates:0x0800 first appears after packet81, virtual time about1.164s.0x10 first appears after packet158, about1.318s, on both X/Y. Final masks are0x0810/0x0810/0.
- First current crossing occurs at1.31702166s for X: -3.8980243A. Maximum absolute current reaches6.1999484A. These are generated physical-state values, not a fabricated status.
- At the offending sample boundaries the timer configuration is forced-inactive mode `CCMR1=CCMR2=0x4848` with temporarily retained/inverted output polarity `CCER=0x3131`. Under the explicit ideal bridge assumption this combination applies-24V. Firmware normally clears polarity as part of its stop sequence, while an outstanding timer IRQ can restore staged polarity.

The original model read the latest drive only at the ADC trigger and applied it retroactively to the entire preceding roughly33us interval. This can assign a register-reconfiguration transient too much energy. The event-time experiment below shows that this approximation contributed to the peak, but was not the sole cause of the fault. The original firmware correctly detected the current produced by the chosen model; changing the fault threshold is not justified.

Before-correction evidence: `tests/results/current-loop-full/` contains per-packet fault/configuration dumps and `currents.csv`. The clean initialization-only comparison is `tests/results/current-loop-long/`.

## Correction

The motor timer exposes before/after configuration-change events. The generic RL plant caches each axis's effective drive voltage. Before a relevant timer register changes, it integrates the old drive to that actual virtual timestamp. After the write, it caches the new drive. At ADC trigger time it integrates only the remaining interval and publishes current-derived samples. Accepted slave starts, timer resets and native one-pulse stopping are covered. Same-timestamp writes add no energy.

The averaged PWM voltage is independent of timer frequency while running; actual timer frequency controls the real trigger cadence and elapsed virtual time. Exact switching and compare-preload timing remain separate limitations. Reset still clears stored electrical energy when the plant itself resets, as explicitly documented.

No R/L, supply, ADC scale, target, threshold, fault bit or firmware code was adjusted. Brief opposite-polarity voltages still contribute their actual elapsed-time energy; they are not suppressed because they are inconvenient.

`tests/run-generic-rl.sh` passes26 assertions. The new transient test deliberately applies-24V through a forced-inactive/inverted-leg configuration for1us, removes it for32us, then generates a real timer update ADC event. Current matches the analytic1us pulse plus32us RL decay, rather than a fictitious33us full-voltage pulse.


## Event-time replay result and remaining cause

The identical404-frame replay with event-time integration **still reports0x0810/0x0810/0**. Peak absolute currents decrease to5.58574A and5.59861A on X/Y, but the original overcurrent checks still trip. The assertion requiring no0x10 intentionally failed; this is not a successful overcurrent-fault fix. Evidence and machine-readable summary are under `tests/results/current-loop-event-time/`.

Per-packet state dumps establish a second, important behavior: after0x0800, requested X/Y states become4, but their actual states remain7. In `0x0800dfc0..0x0800dfe4`, firmware stops output while waiting for state7's measurement-complete flag. Subsequent ADC callbacks still execute `0x08010910` and stage new PWM polarities before the requested-state stop path runs again. Pending TMR1 update IRQ `0x08013470` writes those staged polarities through `0x0800f69c`. This is not merely one isolated startup pulse.

The reference manual describes mode4 as forcing **CxORAW** low; output polarity is a later stage. Therefore a forced-raw-low output with inverted polarity is not automatically a low pin under the current ideal direct-input bridge assumption. Setting all forced-inactive outputs tozero voltage regardless of polarity would hide the observed configuration instead of modeling it.

The missing physical main-to-motor synchronization is being investigated separately. Removing that originating0x0800 condition may avoid this fault-stop sequence. The generic bridge topology remains an explicit assumption, not verified board hardware. No alternate bridge topology, driver-enable wiring, R/L parameter or success current has been invented to clear0x10. Keep the event-time change as a tested accuracy improvement, not a claim that the full fault chain is resolved.

## Native shared-machine confirmation

The subsequent native shared-machine run used actual main-MCU PA8 synchronization, a10us scheduler quantum (independently validated for serial delivery), and the event-time RL source above. No R/L, ADC scale or firmware threshold changed.

Verified artifacts under `rv1106-at32-link/test-results/shared-mcu-10us/`:

- The original motor UART stream contains status reply `7e2608010300000000000040f5`, reporting zero selected-axis faults.
- Final `motor-status.bin` contains zero primary fault masks for all three axes.
- `motor-cpu-faults.bin` is eight zero bytes.

This supports the observed chain: missing synchronization produces0x0800, its stop-during-state7 sequence produces opposite-polarity drive under the generic bridge assumptions, and the original overcurrent check can then add0x10. Providing the actual synchronization removes the originating condition and avoids the fault chain. The event-time change is still justified by the analytic transient tests, but is not alone responsible for clearing these native faults. This is electrical/control integration evidence, not proof of motion or an exact physical board model.

## Final regression and frozen source

After the event-time change, all requested regressions completed:

-26 RL assertions, including real-time short-pulse energy and same-timestamp mutation tests.
-31 timer/ADC trigger and configuration assertions.
- Original firmware with normal assumed parameters: all three primary fault masks0 and all motor states0 at1s.
- Original firmware with zero supply or open winding: all three primary masks0x40; offset-calibration fault0x08 remains clear.

Frozen SHA256 values:

- `AT32F403A_Timer.cs`: `6fda000001dc7bcfa1e21098e62cb1b011848992233286c9a3dc9ec388ec5a39`
- `GenericStationaryMotorRL.cs`: `96e1a5bb4344c45ff48ba353d2b83d33e8f4ee86c8cbfc0d6e564ddd9022d5f3`

The source manifest is `tests/results/current-loop-event-time/source-sha256.json`. Normal/negative results are in `tests/results/generic-rl/results.json`; the native shared-machine success is independent evidence from the bridge integration run.
