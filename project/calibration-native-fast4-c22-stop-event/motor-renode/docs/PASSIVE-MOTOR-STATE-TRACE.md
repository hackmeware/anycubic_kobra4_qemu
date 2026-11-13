# Optional passive motor state observer

`peripherals/PassiveMotorStateTrace.cs` is separate from the physical plant. It reads original firmware RAM and peripheral state for diagnosis; none of that RAM influences its physical rotor model. The observer never writes SRAM, firmware, GPIO, PWM, clocks, ADC samples, enable, faults, homed flags or positions. Only its own counters and CSV file change.

This addresses the enabled-bridge/no-sustained-drive observation from `runs/native-lockstep-contact`, not a method for forcing movement. In that run `GenericMotorDriver.EnableInput=True` means **logical enable active**, not raw PC13 high. The source implements `enable=!value`, and the fresh main SRAM contains PC13 digital-output OID20 at0x20002b98. Unknown `enable_pin:null` in the stepper inspector did not establish absence of a separate output object.

## Opt-in use

Default profiles and launcher wiring are unchanged. First load the dynamic plant and driver, then include `peripherals/PassiveMotorStateTrace.cs` and load `platforms/passive-motor-state-trace.repl`. On the motor machine, call `sysbus.passiveMotorStateTrace Start "/absolute/new/capture.csv"`. `Stop` closes the file; `Reset` stops observation and clears only observer state. An existing path is rejected instead of overwritten.

The constructor adds another receiver to TMR8 TriggerOutput after the plant has been constructed. Rising events on receiver input0 are counted. Defaults: every1000 triggers, maximum20000 samples. Each sample produces three axis rows, flushes the writer, and permits another process to read the file while the run continues. The bounded stream avoids accumulating a second large in-memory trace. Invalid receiver inputs and falling events are ignored. CSV write/read exceptions encountered during sampling stop only the observer and are exposed through `LastError`. Observe `Enabled`, `SampleCount`, `TriggerCount`, `CapacityReached` and `LastError` when checking coverage.

The observer itself does not hash firmware. Use it only after verifying motor SHA256 `76b439293ab08207317007f5179243a0684c1b27668442781bcb2e201ff62661`; that expected layout hash is written into the CSV comment. Do not reuse these offsets for another binary. Source load base is0x08008000.

## CSV interpretation

- `virtual_time_s` is actual shared-machine elapsed virtual time, never wall time or a firmware-derived timestamp. Sample/trigger counts describe this observer session only.
- `logical_enable` is the driver's already-inverted enable Boolean. `derived_raw_enable_level` is its logical NOT, explicitly a derivation, not an independent PC13 measurement. `bridge_enabled` and `external_fault` are actual existing driver/plant getters. GPIOB configuration/IDT/ODT are separate direct observations.
- Mode byte:0x2000000a+axis. State bytes at0x2000070d/0713/0716+axis remain raw. Status halfword:0x20000c00+axis*0x10. PB2 high-count byte0x20000538 and debounce bytes0x20000550..0554 follow the inspected0x0800ce34 input path; these are not forced or interpreted as ready.
- Detector record:0x20003a2c+axis*0x54; bytes+0x50/+0x51. Path selector/alternate event:0x2000064c/064d+axis*6. XY output suppression byte0x20003b3f. Evidence: `ROTOR-FEEDBACK-EVIDENCE.md` and `firmware-evidence/sensorless-residual-and-gpio.asm`.
- Control record:0x20004180+axis*0x6c. Angle+0x0c is the controller reference, **not measured rotor angle**. Speed word+0x10 stays raw. Halfwords+0x2a/+0x2c are measured phase-current values, +0x32/+0x34 transformed current, and +0x42/+0x44 stored effort. Additional halfwords+0x36..+0x40 are retained with raw offset labels; no target or SI-unit meaning is invented for them. Evidence: current loop0x08009738 and `firmware-evidence/command-angle-path.asm`.
- Calibration record:0x20002038+axis*0x1f4; +0x0c measured current and +0x34 target are emitted as raw unsigned16 encodings. Signed interpretation, if needed offline, requires two's-complement conversion. These are **startup calibration** fields, not a claimed current motion target. Evidence: `CURRENT-CALIBRATION.md`, initializer0x080106d4 and comparison0x0800fca8.
- PWM timer mapping: index0 TMR3 at0x40000400, index1 TMR1 at0x40012c00, index2 TMR4 at0x40000800. Columns are raw register offsets:0 control,4 secondary control,8 slave control,0x10 status,0x18/1c output modes,0x20 channel enables/polarity,0x24 counter,0x28 prescaler,0x2c period,0x30 repetition,0x34..40 compares,0x44 break/main-output state. Some advanced-timer fields have no hardware meaning on general timers; retain their readback without assigning one. TMR2 snapshots use the same offsets shown in the column names, and include its control/counter/capture compare state. No read-to-clear data/USART or GPIO lock registers are touched.
- Physical angle, velocity, currents, torque, energy and relative travel are existing read-only getters from the independent assumed rotor model. The observer does not advance that model to obtain a reading. Relative travel is not homed position or measured real-printer calibration.

## Timing and limits

Decimation can miss short-lived events and cannot establish exact instruction ordering. TMR8 trigger observation follows plant trigger registration, but it is not a guarantee that the asynchronous CPU has completed the corresponding ADC ISR. A snapshot can reflect the previous control iteration. If TMR8 stops, no further samples appear. Absence of CSV rows is therefore not proof of a frozen host. CSV flushing adds wall-time overhead but never advances virtual time explicitly. The same sampling instant is used for all three rows; SRAM is observed at that boundary, not interpreted as an atomic firmware transaction.

Next-run final full motor SRAM/GPIO/timer dumps and native serial capture remain necessary. No successful homing, contact or motion is inferred by this observer.

## Synthetic validation

`bash tests/run-passive-motor-state-trace.sh` loads the peripherals without firmware and without running CPUs. A test-only component prepares SRAM sentinels and device configuration, then manually delivers observer events. It verifies startup disabled, live header/row visibility, ignored events, decimation, bounded stop, field alignment, raw values, enable labels, preserved SRAM/GPIO/timer/driver/plant state, existing-path rejection and reset. Synthetic observations are not original-firmware execution evidence.

The 5 November 2026 run passed20 checks, including a final actual TMR8 TriggerOutput pulse delivered to both the existing plant and the new observer. Evidence: `tests/results/passive-observer/run-1GypPS/test.log` and its CSV files. This is a no-firmware synthetic unit test, not a heavy replay or a claim of motion.

## Read-only stage analysis and PWM dispatch

`python3 tools/analyze_passive_motor_state.py /path/motor-state.csv --stage startup:0:1 --stage before:10:15 --stage homing:15:22` reads one snapshot and writes JSON only to stdout. The illustrated boundaries are examples, not inferred homing timestamps. Supply verified shared-virtual-clock boundaries from the actual run. It reports per-axis state/PWM configuration sample counts, observed transition brackets, control-reference variation, and independent physical current/velocity/travel ranges. Partial final lines and incomplete trailing three-axis samples are excluded and counted; malformed interior samples are rejected. Command counters are not inputs. Four synthetic Python tests validate stage separation, mode decoding, partial-tail handling and rejection of broken interior samples.

Original firmware inspection further resolves state byte0x2000070d+axis as the current dispatch state, read at0x0800db9a by dispatcher0x0800db88 (file0x5b88). The next/requested state byte is0x20000710+axis, read at0x0800de4c and copied into current state at0x0800dfe6..dfea. This requested-state byte is **not included in CSV version1**; capture it through the separately planned final SRAM dump, or a separately versioned future observer. Do not modify a running observer or infer that byte from adjacent state fields.

- Current states0 and4 dispatch to0x0800dbbc, which calls stop helper0x080117b8. It selects the actual motor timer and calls0x0800f58c: all four channels forced-inactive mode4, polarity0, compares3736/264/3736/264. The compare values can therefore remain nonzero without active PWM.
- Current state3 dispatches to0x0800dc30 and calls current-loop0x08009738. State6 enters the separate calibration routine at0x0800dc6c.
- Drive-enable helper0x0800f564 selects the timer and calls0x0800f614: PWM mode6 on all channels, initial polarities0/1/0/1 and the same compare values. Mode7 is supported by the peripheral/plant interpretation but is not selected by this inspected helper.
- Transition code0x0800de58 tests the actual status halfword against0xefec; a nonzero masked result replaces the requested state with4. Current state0's transition branch enables PWM for requested states selected by bitmask0x1ea:1,3,5,6,7,8; other values take the stop path. Current state4's branch at0x0800df4a additionally checks status and status-record+2, then uses mask0x1ce:1,2,3,6,7,8. This is a bounded description of these branches, not a complete reconstructed state enum.

Consequently commutation mode4 (the separate angle dispatcher) and logical bridge enable1 do not establish active motor control. In the initial exact24 observation, current dispatch state0 and PWM mode4 agree with the firmware stop path. A transition to current state3, changing control angle/current effort, active PWM configuration and independent physical movement would be separate observations to correlate, not prerequisites to fabricate.
