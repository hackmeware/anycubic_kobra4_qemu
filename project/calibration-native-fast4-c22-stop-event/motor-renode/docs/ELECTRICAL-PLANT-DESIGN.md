# Electrical plant scope and firmware evidence

This records the initial digital-mapping investigation. A later explicitly assumed generic electrical fixture is described in `GENERIC-STATIONARY-RL.md`; it does not claim identification of the exact board. The tested zero-current calibration component remains unchanged. No current samples, fault bits or state transitions are manipulated to make the response test pass.

## Proven digital mapping

The motor index is assigned in injected ADC IRQ handlers `0x08008a94` and `0x08008b18`:

| Firmware motor | PWM timer | Timer base | Current ADC | Injected channels |
|---|---|---|---|---|
|0|TMR3|0x40000400|ADC1|CH0, CH4|
|1|TMR1|0x40012c00|ADC2|CH5, CH6|
|2|TMR4|0x40000800|ADC3|CH12, CH10|

`0x08011758` reads four halfword compare values and calls `0x0800f6ec`. That function selects the timer by motor index and writes C1DT/C2DT/C3DT/C4DT at offsets0x34/0x38/0x3c/0x40. PWM preparation `0x0801a1a4` calculates two compare pairs from two signed phase commands. It applies a per-motor pair-swap flag at `0x0801a406` before storing the four outputs.

Polarity is independent of compare values. Control code stages four polarity bits in RAM0x20000904..0a and motor index at0x20004040, then enables the TMR1 update IRQ through `0x080169dc`. Handler `0x08013470` loads the staged values and calls `0x0800f69c`, which changes CCER bits1,5,9,13 on the selected motor's timer. A plant reading only compare values would lose command direction and is incorrect.

Drive enable `0x0800f564` selects the motor timer and calls `0x0800f614`. The latter selects PWM mode6 on all four channels, default polarities0/1/0/1, and compares3736/264/3736/264. Stop helper `0x080117b8` selects the timer and calls `0x0800f58c`, which selects forced-inactive mode4 on all four channels and polarity0. These output modes, channel enables, timer enable, and TMR1 main-output enable must all gate drive. Zero duty does not necessarily mean an open circuit: recirculation depends on the actual bridge.

Timers are initialized with period4000 and center-aligned operation. TMR3 setup `0x0801c15a..176` and TMR4 setup `0x0801c2f4..310` use trigger slave mode6 and IS1 (SMCR0x16). A future PWM testbench must connect their IS1 to TMR2 enable TRGO as specified by the reference-manual trigger matrix. The existing calibration-only component connects TMR1/TMR8 but intentionally does not yet model running TMR3/TMR4 drive paths.

For the standard two-input bridge interpretation, a channel's average high fraction in PWM mode6 is its compare/period (clamped0..1), inverted when its polarity bit is set. Adjacent channel pairs then describe signed phase voltage through their high-fraction difference. Firmware's positive/negative branches in `0x0801a1a4` are consistent with this interpretation, including minimum edge spacing264. This establishes the digital waveform interpretation, but not the board's unprovided bridge truth table or analog transfer.

## ADC sign and scale

At `0x0800a43c`, each raw injected ADC sample has its calibrated offset subtracted. The differences are multiplied by two per-motor16-bit gains at `0x20000742 + motor*12` and `0x20000744 + motor*12`; results are stored as16-bit signed quantities. A flag at `0x2000073e + motor*12` swaps the two measured phases. Initializer `0x0800f0ea..124` clears this flag and initializes both gains to+1. Thus default internal phase feedback is exactly raw sample minus offset, in ADC counts. Gain0xffff behaves as-1 through16-bit truncation. These are not permanent gains: PWM preparation writes them at `0x0801a44c/0x0801a450` using command polarity. The original-firmware0.3s snapshot has(+1,-1) for all three motors, after initial(+1,+1). This is direct evidence that converting physical coil current into sensed ADC values must account for bridge/current-sense topology; a fixed signed-coil-current transfer is not justified.

`0x080136f4` provides angle-dependent sine/cosine values. Transform `0x08018b18` computes, with signed arithmetic and truncation towardzero:

- first output = (phase1*cos + phase2*sin)/1024;
- second output = (phase2*cos - phase1*sin)/1024.

The sine/cosine table is Q14, so at cardinal angles the first output has16 units per ADC count. Fault0x40's target/2 threshold3971 is therefore in transformed internal units, not amperes. The raw-count overcurrent check in `0x0800a4c2..4ec` also remains active and must not be bypassed by the plant.

## Missing physical parameters and implementation gate

Not established by the firmware trace alone:

- bridge device and input truth table, enable/fault GPIO wiring, high-impedance versus braking states, dead-time and recirculation paths;
- actual supply voltage, winding resistance and inductance, driver on-resistance;
- current-sense resistance/amplifier gain, ADC reference voltage, polarity of each physical winding relative to the digital phase;
- rotor/encoder coupling, electrical angle, back-EMF constant and mechanical parameters for motion.

A stationary RL model is defensible only with an explicitly selected bridge interpretation and explicit physical parameters. Its state would be two coil currents per motor, updated using elapsed virtual time and actual gated differential PWM voltage: di/dt=(Vphase-R*i)/L, followed by a documented current-to-ADC transfer with saturation and the existing trigger-qualified sample path. It must honor disable/forced-inactive/output-enable/polarity changes and compare preloads, and must not read firmware test state or fault thresholds to choose its response.

Before implementation, verify the board driver/current-sense mapping or clearly authorize a generic assumed electrical testbench, and inspect what Renode's timer retains for channel modes, enable, polarity and shadow compares. Tests must include disabled-drive decay, zero supply, reversed polarity, disconnected/open winding, saturation and fault preservation. Passing one startup current-response check would still not establish motion, encoder behavior or complete printing.

## Verified wiring correction and timer configuration support

An initial trace incorrectly labelled the TMR3/TMR4 source as TMR1 IS0. It confused `0x0801ad1c` (MMS setter at CTRL2+4) with `0x0801ad5c` (TS setter at SMCR+8). The latter is called with1 for both timers. Read-only original-firmware snapshot at0.3s confirms SMCR0x16 for both: SMS6, TS1. RM table14-12 maps IS1 to TMR2 for both timers. The correct wiring is **TMR2 enable TRGO→TMR3 IS1 and TMR4 IS1**. The incorrect earlier inference must not be used.

Optional `scripts/pwm-trigger-wiring.resc` loads only this proven digital wiring, via addressless-sysbus `VirtualMotorPWMTriggers`. Use it alongside the stationary calibration overlay when needed. It has no electrical state and does not set ADC samples. The saved raw runtime snapshot is `tests/results/pwm-register-snapshot.log`.

Upstream Renode already retains functional output compare modes, channel enables and polarity bits. The motor adapter now additionally retains the otherwise discarded output fast/preload/clear configuration bits and the low16 break/dead-time register bits, including MOE, for accurate readback. This is configuration retention only: **compare preload/shadow latching, break input, dead-time, complementary drive and MOE output gating are not implemented by this change**. Native compare writes take effect immediately; electrical simulation must not mistake diagnostic readback for these physical behaviors.

`tests/run-motor-trigger.sh` passes31 assertions, including component instantiation, stopped-before-trigger and both PWM timers starting on the selected TMR2 enable edge, mode/preload retention, independent polarity reversals, BDTR/MOE readback and reset. `tests/run-pwm-runtime.sh` runs the original firmware without firmware/RAM patches and strictly checks all three PWM timers enabled with SMCR0x16 and period4000 at0.3s, while original state6 current-response testing is active. `tests/run-calibration-contrast.sh` still validates both2048 and0 inputs after the configuration-readback changes.

Exact-board investigation stopping condition: digital timer/ADC mapping and the fault path are established; missing board bridge/current-sense facts prevent claiming an identified physical model. The subsequent authorized generic testbench uses explicitly assumed R/L, supply and sense parameters, documented separately in `GENERIC-STATIONARY-RL.md`.
