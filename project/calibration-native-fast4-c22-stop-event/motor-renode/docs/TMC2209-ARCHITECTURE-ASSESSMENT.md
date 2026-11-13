# TMC2209 versus the supplied motor controller

Independent assessment, 2026-11-04. This separates documented chip behavior, observed firmware behavior and a proposed generic testbench. It does not identify the printer's actual bridge components or current-sense wiring.

## Standard TMC2209 boundary

The Analog Devices TMC2209 datasheet Rev1.09 describes an integrated two-phase motor driver: bridge MOSFETs, current regulation, microstep sequencing, STEP/DIR control and single-wire UART configuration/status. Internal or external sense resistors are supported. A normal application does not require the host MCU to run a two-phase current-control loop through six injected ADC channels. The published pin interface does not provide four direct phase-PWM command inputs per motor. IOIN's VERSION field identifies digital version0x21.

Primary source: https://www.analog.com/media/en/technical-documentation/data-sheets/tmc2209_datasheet_rev1.09.pdf (block diagram and pin/application sections; IOIN table, printed p25). This paragraph is a brief paraphrase, not a copied datasheet.

## What this firmware proves

1. Main-to-motor command8 reaches motor function0x08012e34. It looks up a25-entry RAM register table and constructs TMC-shaped replies itself. It does not read those register values from a downstream UART transaction. The observed IOIN value0 differs from the documented silicon version field, another reason not to treat the table as a transparent view of a physical TMC2209.
2. Writes are not merely stored for later forwarding. IHOLD_IRUN callback0x08013048 extracts hold/run-current and delay fields into the motor controller's own RAM at0x20000726+motor*8 and0x200039b4+motor*40. CHOPCONF callback0x08012de0 decodes VSENSE/MRES into local settings and calls0x080124d4. That function updates the local motion structure at0x200078f0+motor*0x46dc, including scale calculations. These checked callback paths do not perform an external UART transfer.
3. Separate evidence establishes three four-output PWM timer paths and two injected ADC feedback channels per motor. The unmodified motor firmware calibrates ADC offsets, then performs a current-response test. With stationary midscale inputs, it legitimately reports fault0x40 because commanded excitation has no simulated current response.
4. The nozzle is a different boundary: its original firmware uses PA3 at40kbaud for TMC UART. The existing standard-style GPIO UART/register model has completed twelve reads and ten writes through the original nozzle firmware. This supports using a TMC2209 model there, without proving all physical motion behavior.

Consequently, the supplied motor image exposes a TMC-compatible software interface while running a local motor-control implementation. That is stronger than a guess based on a filename or a product description. It does **not** prove that there are no physical TMC2209 devices anywhere on the board, establish exact PCB wiring, or prove which supplied image runs on the identified FCES component. Those are separate hardware-mapping questions.

## Correct interpretation of current-sense uncertainty

The observed ADC calibration and sign/scaling changes are facts about firmware expectations. They are not evidence of an exotic or proprietary sensing circuit. Ordinary bridge and current-shunt arrangements can have topology-dependent signs and sampling windows. The exact arrangement remains unverified. We should not describe it as unusual, nor infer it from the existence of TMC-shaped registers.

A standard TMC2209 UART model is useful at an actual STEP/DIR/UART boundary. It cannot by itself supply the injected-ADC feedback required by this motor binary's PWM control loop. Connecting such a model directly to four phase-PWM outputs would model the wrong interface.

## Useful next implementation

Implement a **generic, explicitly parameterized two-phase bridge plus RL winding testbench** behind the verified PWM/ADC interface. It is a simulation choice, not a recovered board schematic. Configure supply voltage, winding R/L, ADC offset/gain and a documented bridge/sense interpretation in the fixture; do not label them measured printer values. Generate feedback solely from elapsed simulated time, gated PWM outputs, coil state and the selected sensing transfer. Never read firmware state numbers, target thresholds or status RAM to decide a passing sample.

Start with stationary electrical behavior; rotor dynamics and encoder coupling can follow. Validate disabled drive, zero supply, open winding, polarity reversal and saturation as negative cases. Keep firmware fault checks and overcurrent handling active. A parameter sweep should expose whether behavior depends on a narrow tuned fixture rather than hide it. Passing this generic current-response test demonstrates a functioning control-loop environment, not exact board emulation or completed printing.

In parallel, keep the standard nozzle TMC2209 model and the original motor firmware execution path distinct. Verify physical board/image mapping when schematic, board photos or reliable component identification becomes available; that evidence can replace generic fixture parameters later.

Related evidence: `ELECTRICAL-PLANT-DESIGN.md`, `CURRENT-CALIBRATION.md`, `ORIGINAL-STATUS-QUERY.md`, and the shared `motor-tmc-register-evidence.md` report. Exact TMC write callback disassembly is retained in `tmc-write-callbacks.asm`.
