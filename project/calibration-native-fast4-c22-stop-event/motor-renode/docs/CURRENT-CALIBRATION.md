# Evidence-based stationary current-calibration testbench

This optional motor-only testbench supplies six mid-supply, zero-current ADC samples and models the firmware-configured timer trigger chain. It does not move motors, fake encoder feedback, clear faults, patch firmware or force software states. Existing 24 MHz HEXT and already-running LICK boot-state assumptions remain explicit in `scripts/board-clock-and-rtc.resc`.

## Static firmware evidence

Original motor image: `motor_firmware_v1.6.01_20260313.bin`, load address `0x08008000`.

- `0x08018020..0x0801802e` sets each motor's requested state to5 through `0x08018630`. Startup waits at `0x0801807c` while any of RAM `0x20000710..12` remains5.
- The state handler `0x0800db88` runs from injected-ADC IRQ handlers `0x08008a94` and `0x08008b18`. Calls at `0x08008ae6/0x08008b50` pass the two injected conversion results to it.
- State5 dispatches to `0x0800dc46`. Calibration records are at `0x20003b60 + motor*16`.
- Initializer `0x0801158c` sets a500-event settling count, a2048-event averaging count, zero accumulators and initial offset2048 for both samples.
- `0x0800dd14..0x0800dd3a` accumulates the two samples. `0x0800e090..0x0800e0d2` divides each sum by2048 and checks the result against [1675,2420]. Out-of-range sets faultbit0x08 through `0x08011724`; the original checks remain active.
- ADC setup `0x0801b334`, `0x0801b440`, `0x0801b504` programs two injected channels: ADC1 CH0/CH4, ADC2 CH5/CH6, ADC3 CH12/CH10. All select preempt trigger15 and enable it through `0x08014364`.
- AT32's official ADC header identifies trigger15 as TMR8_TRGOUT. CTRL2 bit24 is PCTESEL_H, not a repeat-mode bit. The actual `0x011EF001` configuration is correctly treated as an external trigger selection.
- TMR2 configuration sets MMS1 (enable signal) at `0x0801bfe2`. Startup enables TMR2 at `0x08018010..16`.
- TMR1 (`0x40012c00`) setup at `0x0801bd70` selects trigger mode6, IS1, and update TRGO(MMS2). It uses period4000, center-aligned mode and repetition1.
- TMR8 (`0x40013400`) setup at `0x0801c4a0` selects trigger mode6, IS0, one-pulse mode, period4071 and update TRGO(MMS2).
- Reference manual Rev2.06 table14-12 maps TMR1 IS1←TMR2 and TMR8 IS0←TMR1. Thus the actual chain is **TMR2 enable→TMR1 count/update→TMR8 one-shot/update→three injected ADCs**. Firmware rotates injected IRQ enables ADC1→ADC2→ADC3→ADC1.

## Implementation

`AT32F403A_Timer.cs` retains AT32 master-mode bits, which upstream Renode only tags and does not retain, and exposes TriggerOutput. It uses the existing native `LimitReached` event, not a second free-running clock. Input pins16..19 represent IS0..3. Only the selected rising input in trigger mode6 starts a stopped timer and sets CEN. One-shot stopping remains native. Master enable, update-event repetition, software update and UDIS gating control TRGO.

`AT32F403A_System.cs` adds `TriggerPreempt(source)` to the motor-only ADC. ADCEN, PCTEN and full PCTESEL must match. GPIO inputs carry trigger-source numbers. The six assigned samples are ordinary testbench inputs; zero samples still produce zero conversion values.

`VirtualMotorCurrentCalibration` connects the proven chain and assigns2048 to the six proven channels. Load it explicitly with `include @scripts/stationary-current-plant.resc` after the motor platform. It is registered addresslessly at sysbus so its constructor is actually instantiated.

Timer timing inherits native Renode counter-event granularity and center-aligned approximations. RCR divides the counter-boundary events; tests cover RCR1. This is not a complete analog, PWM, power-stage or rotor-dynamics model. Only MMS enable/update and slave trigger-mode6 are added. Other timer trigger modes are not claimed.

## Validation and limits

`tests/run-motor-trigger.sh` passes31 assertions in Renode1.17.0: reset, retained MMS, wrong internal-trigger rejection, selected edge sets CEN, one-shot stop/rearm, software disable/update, UDIS, RCR1, disabled/wrong-source ADC rejection, IRQ clearing and zero-input integrity. Nine additional assertions cover optional TMR2→TMR3/TMR4 IS1 wiring and retained PWM/polarity/preload/MOE configuration. Configuration retention is not electrical behavior; see `ELECTRICAL-PLANT-DESIGN.md`.

`tests/run-calibration-contrast.sh` runs the original firmware twice with identical timer/clock setup and different physical inputs. It checks raw RAM dumps for all3 motors: wait/sample counters0, sums=input×2048, offsets=input and original calibration-faultbit0x08 set only for zero inputs.

Observed2048 run: sums0x00400000, offsets2048; remaining faultword0x00090040. Zero-input run: sums/offsets0; faultword0x00090008. Both naturally leave startup's state5 wait and later reach state4. **State4 is not evidence of successful physical motion or a fault-free printer.** Remaining faults are preserved and require separate investigation. Passing current-offset calibration does not validate encoder feedback, commutation, motor dynamics, endstops or the complete printer.

## Remaining fault0x40: current response, not offset calibration

The contrast runner completed successfully and saved logs and raw calibration/fault dumps under `tests/results/calibration/`. The original22 timer/ADC assertions (now expanded to31) are recorded in `tests/results/motor-trigger.log`.

After offset calibration, startup requests state6 at `0x080181b8`, `0x080181c0` and `0x080181e0`. The injected-ADC state handler dispatches state6 at `0x0800dc6c` into `0x0800f718`, a multi-stage excitation/current-response routine. Its initializer `0x080106d4` selects record `0x20002038 + motor*0x1f4`, initializes iteration count at+0x14 to0, timeout at+0x18 to1000, and signed target at+0x34 to0x1f07(7943).

At `0x0800fca8`, after the timeout, firmware compares the signed measured transformed-current at record+0x0c with target/2. A result below3971 takes `0x0800fcc4`, writes internal substate8 and passes faultmask0x40 into `0x08011724` through `0x0800fd0a`. This is a real current-response failure. It is not an encoder-idle flag, and leaving state5 does not satisfy it.

The measured current originates in the injected ADC pair. `0x08010592` calls `0x0800a43c`, which subtracts the calibrated offsets and applies configured scaling and channel selection. The pair is transformed through `0x08018b18`, and the resulting pair is stored at record+0x0c by `0x080105ca`. Constant2048 samples minus2048 offsets give zero current. The stationary zero-current testbench therefore correctly fails the subsequent excitation test and preserves fault0x40.

A future electrical model must derive current from the real PWM/bridge drive and explicit winding/supply parameters. Feeding threshold-crossing samples, clearing fault bits or changing firmware state would bypass the original check and is not an acceptable substitute. No such bypass is present here.
