# Later integration recommendation: explicitly synthetic functional test

## Status and prerequisite

Prepared and model-tested only. No central integration, native accelerated run, hot swap, or controller change is included. Preserve the existing `native-nozzle-230-synthetic-r3` run and its frozen V7/controllerV3 evidence. Do not silently replace its thermal plant, rescale its clock, erase retained heat, or reinterpret its success criterion.

Do not begin a new native run until the existing slower test completes verified normal target-zero, heater-off and physical-cooling teardown. After that, select a fresh paused run only when the parent schedules the native test slot. Checkpoint its exact launch configuration, source hashes and parameter manifest before native execution. Explicitly name the factor and synthetic/non-realistic status in the run directory and result. Selected first factor: 4x, matching the user commitment confirmed by the parent. Example label: `native-nozzle-230-accelerated-functional-4x-r1`. Keep 2x only as an explicitly reviewed fallback after a 4x failure, and 10x as a stress comparison. Prefer nozzle-only first, bed off and independently verified. A future bed test remains separate.

## Exact profile substitution, not merge

1. Select `profiles/4x` for the first functional run. The separate2x pair is a fallback only after a documented4x failure and review;10x is stress-only, and 1x is a control. Confirm before launch that only C differs from the approved optional synthetic baseline and that all guard values match. Do not attach two writers to a single ADC channel.
2. Load the unchanged `nozzle-renode/peripherals/VirtualPrinterThermal.cs` and `NativeNozzleHeaterBinding.cs`. Use this package's selected `nozzle.repl` INSTEAD OF the baseline synthetic nozzle thermal/binding profile.
3. Load the unchanged `at 32-renode/peripherals/VirtualPrinterThermal.cs` and existing `printer-shared-mcu/experimental/synthetic-calibration-thermal/ResolvedBedHeaterBinding.cs`. Use the selected `bed.repl` INSTEAD OF the baseline bed thermal/binding profiles. Merely choosing a bed profile does not authorize a native bed-heating command.
4. Shared namespace generation substitutes `Antmicro.Renode.Peripherals.AT32` with `...PrinterNozzle` for nozzle sources and `...PrinterMain` for main sources, including the existing bed binding. Corresponding REPL type prefixes become `PrinterNozzle.` and `PrinterMain.`; `ThermalExperimental` stays unchanged. This is the only source transformation used by the validated suite. Existing object names and input wiring are preserved.
5. Preserve actual resolved PB8/PA0 initial synchronization and edge forwarding. PB9 remains thermally unbound. Retain the existing passive observations, time mapping, drop accounting and fault exports. Do not load the test class or its synthetic GPIO writes into a native run.
6. Record baseline physical/ADC/native temperatures, accepted target zero, heater outputs low, sensor fault none, curve valid, latches false, bed off and fresh clocks before issuing a native heating request. If the machine is already warm, preserve it and record the actual state; do not manufacture25°C. Start a separately cold scenario only by a genuine fresh setup, never by resetting retained heat inside the old run.

## Keep controllerV3 and the 30-second regulation criterion intact

The current controller's stable target±2°C for 30 virtual seconds criterion must remain exactly that criterion. A future accelerated run using it may pass or fail, but even a pass is synthetic-loop evidence, not validation of real printer PID. No shortened observation can be labeled equivalent stable regulation or PID calibration.

To save time specifically for plumbing validation, prepare a **separate, explicitly selected external `functional-reach-and-off` criterion** in a new source/checkpoint revision. This document proposes it; no controller implementation is changed here. It must use the normal native command path and native target acceptance, without modifying firmware wait, PID, guard, watchdog or shutdown logic.

Proposed functional procedure and outcome:

- Test the approved target, initially nozzle 230°C with bed 0. Confirm native accepted target via the same verified normal route. Mere client transmission or a successful RPC alone is insufficient.
- Capture actual GPIO/PWM edges, physical model temperature, unchanged ADC values and native interpreted temperature, sensor fault/range/latch state, PB9 observations, time mapping, transport errors and observation drops.
- Require real physical heating and at least one fresh, mapped native/physical observation pair in the predeclared target region (nozzle 220..240°C; bed 55..65°C in a separately authorized bed test). Record arrival only, never readiness or regulation. If native/physical observations cannot be compared using the existing verified clock mapping, report inconclusive rather than inventing simultaneity.
- Observe up to an additional 5 virtual seconds of response, then issue normal target-zero. Five seconds is an external data window, not a firmware wait change, stability test or PID qualification. Do not wait out that window if an abort condition occurs.
- Proposed absolute external cap from accepted target:120 virtual seconds at 2x,60 at 4x,30 at 10x. These are bounded experiment caps, not promises of reachability or firmware compatibility. A timeout is a negative/incomplete functional result; never extend automatically or reinterpret it as success.
- Abort earlier on physical nozzle≥250°C or bed≥75°C, any native shutdown/fault, invalid sensor/curve/latch state, stale required telemetry, transport failure, source change, clock failure, or loss of reliable observation. These are external experiment-stop thresholds, not replacements for native safety. Faster heating can cross one before the next observation; preserve that result.
- On completion or abort, use normal native target-zero. Confirm native acceptance, actual PB8/PA0 low, zero integrated heater duty and subsequent physical cooling with fresh increasing timestamps. Cooling means an actual decrease over a measured interval, not an ADC fault rail. A client/RPC timeout does not clear demand.
- If shutdown cannot be verified, pause/stop the virtual run, preserve warm state and all evidence, and report unresolved shutdown. Never cold-reset to ambient or synthesize an off/success flag.

Report **functional reach-and-off pass** only if target acceptance, real GPIO/thermal/ADC/native response and confirmed ordinary shutdown/cooling are all observed without a fault. A shorter temperature excursion, guard trip or incomplete shutdown is a negative or inconclusive result with its actual reason. A pass makes no assertion of sustained regulation, PID suitability, native heat-up-watchdog timing, real-world physical fidelity, bed closed-loop behavior, force/homing or print readiness.

## Decision gates

Model-level tests support the capacity-only implementation, not native compatibility. The parent selected4x first to match the user commitment. Fixed1s smoothing corresponds to about3.73°C full-high continued rise from 230°C at 4x, versus1.88°C at 2x and 9.04°C at 10x. Explicitly observe overshoot and accept a native guard trip as a valid negative result. If4x fails, preserve its evidence before the parent selects a separate2x fallback. Do not automatically switch factors or retune native controls. Parent/integrator chooses the test slot, target and reporting criterion before launch, after target-zero, heater-off and cooling teardown of the existing slower run.

A later source integration should be a new isolated launcher/profile/controller revision, not an edit to any active frozen dependency. Freeze it, verify exact differences, and run relevant controller tests before use. Reuse the existing unchanged native safety mechanisms; never retune them as part of this feature.
