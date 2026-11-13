# Accelerated synthetic thermal functional fixtures

**Inactive, explicitly synthetic and non-realistic. Not real-printer calibration, native PID validation, stable regulation, print readiness, or a native watchdog result.**

This isolated package reduces only heat capacities relative to the existing optional 60W nozzle / 200W bed synthetic fixture. The current live run, firmware, central launcher, controller, original models, dependencies and all existing profiles are untouched. No accelerated native run has been performed. Files written for this preparation are confined to this new directory.

## Choice and trade-off

**Selected first native functional profile: 4x, as requested by the parent after confirming the user was promised4x.** Keep 2x only as a separately reviewed fallback if4x fails, and 10x only as a stress comparison. The generator's explicit default output is 4x, but generating it does not activate it. No default launcher profile is changed. The 1x profile is a control. Do not begin any new native run until the current slower run has completed verified normal target-zero, heater-off and cooling teardown.

Only `heatCapacityJoulesPerKelvin` changes. For `C dT/dt = P duty - G(T-25)`, lowering C by factor f multiplies the instantaneous heating/cooling rate by f and divides the thermal time constant by f. At a constant duty it divides ideal target-crossing time by f. Power, loss, required holding duty and mathematical equilibrium do not change. With a fixed, time-varying native PWM sequence it is not a simple time-scaled replay: the controller and sensor still run at their original pace.

| Factor | Nozzle C J/K | Bed C J/K | Initial nozzle / bed rate °C/s | Nozzle / bed time constant s | Ideal ambient→230°C / 60°C s |
|---|---:|---:|---:|---:|---:|
| 1x control | 20 | 600 | 3 / 0.3333 | 100 / 400 | 114.991 / 121.796 |
| 2x | 10 | 300 | 6 / 0.6667 | 50 / 200 | 57.495 / 60.898 |
| 4x | 5 | 150 | 12 / 1.3333 | 25 / 100 | 28.748 / 30.449 |
| 10x | 2 | 60 | 30 / 3.3333 | 10 / 40 | 11.499 / 12.180 |

All factors retain nozzle P=60W, G=0.2W/K, ambient25°C and bed P=200W, G=1.5W/K, ambient25°C. Full-duty equilibria are nozzle 325°C and bed 158.333°C mathematically. The bed's unchanged 150°C model latch acts before its mathematical equilibrium. The nozzle's native320°C limit acts before its model400°C latch if functioning normally. Those limits must not be raised. Holding duties remain68.3333% nozzle and 26.25% bed at the stated targets.

The ideal timings are open-loop plant calculations, not native completion forecasts. CPU execution speed, virtual time, scheduler deadlines, update period, sensor smoothing, PWM period, ADC conversion, telemetry timing and firmware guards are not accelerated. Cold setup remains25°C; temperature is never teleported to a target. Cooling also accelerates because this is a smaller hypothetical thermal mass, not a heater-only speed knob.

## Timing risk and selected4x trade-off

The recovered native PWM period is 0.1s and sensor smoothing is 1s. The physical update remains10ms. At fixed power these unchanged observation/control intervals cover larger temperature movements:

| Factor | Nozzle rise in first 0.1s °C | Nozzle rise in first 1s °C | Extra rise after 1s full-high from 230°C °C | Bed rise in first 1s °C |
|---|---:|---:|---:|---:|
| 1x | 0.300 | 2.985 | 0.945 | 0.333 |
| 2x | 0.599 | 5.940 | 1.881 | 0.665 |
| 4x | 1.198 | 11.763 | 3.725 | 1.327 |
| 10x | 2.985 | 28.549 | 9.040 | 3.292 |

These are full-high trajectory calculations, not assumed sensor delay or observed overshoot. They show that2x has a smaller control/sensor timing mismatch than 4x, while10x is much more aggressive. The selected4x first experiment deliberately accepts that larger synthetic mismatch to shorten warmup, with overshoot explicitly observed and all original guards retained. If4x fails, preserve that negative result before considering a separate2x fallback; never silently switch or relabel it. A lower heat capacity changes the plant seen by the original PID. Overshoot, oscillation, native heater verification failures, ADC guards or thermal shutdown are valid negative outcomes. **Never retune PID, alter a watchdog, lower a target automatically, hide a fault, extend a cap automatically, or mark readiness to make the run pass.** Actual native heat-up watchdog/check_gain_time/heating_gain values remain unrecovered; compatibility is unknown.

At the parent-observed approximate76 wall-seconds per virtual second, ideal full-high nozzle warmup alone would be approximately73min at 2x,36min at 4x or15min at 10x. This is only illustrative: that measured slow execution ratio is not guaranteed for another run, and boot, command acceptance, native control, observations and cooling add time. This preparation does not improve CPU/VM throughput.

## Unchanged sensing, GPIO and guard boundaries

- Actual resolved nozzle PB8 feeds heater input0. Nozzle physical temperature feeds the unchanged complete recovered NTC ZM3863 HNS112HC4570G0 conversion, verified4700Ω/12-bit ADC0 onPA0. Codes remain4023 at 25°C and 468 at 230°C.
- Actual resolved main PA0 feeds bed heater input0. The unchanged B3950/100kΩ/4700Ω model feeds ADC8 onPB0. Codes remain3911 at 25°C and 3444 at 60°C. B3950 is recovered configuration; the bed divider/calibration remain unverified physical assumptions.
- PB9 remains passively observable and thermally unbound. The generic unmeasured fan loss is not enabled. No invented temperature-triggered fan controller is added. This omission is a visible simplification, not evidence that real cooling is negligible.
- Both original `VirtualPrinterThermal.cs` sources, the original nozzle binding and existing resolved bed binding are compiled unchanged, with namespace substitutions in temporary copies only. Model maxima400°C/150°C, stop-at-maximum latches, automatic10ms integration, exact exponential updates and PWM duty integration are retained.
- Nozzle out-of-table physical temperature outside−40..360°C remains visibly invalid and publishes the original fault rail; no plausible sensor clamp is added.
- Open/short tests change sensing only. MCU-style resets retain physical heat, sensor faults and latch history, clear accumulated command duty, and never reassert stale pre-reset high. Genuine later GPIO edges can restart only an unlatched heater.
- Original native ADC guards remain nozzle eight-sample sum962..32593, bed 15205..32309, error limit 4. Original native nozzle min0/max320/max_safe320/min_extrude60 and bed max_safe100/max120 remain outside this package and unchanged. These static facts do not prove runtime guard behavior in an accelerated native run.

## Validation actually performed

A source/text checkpoint was created before model execution. **89 analytic/static checks and 628 actual C# assertions passed across 1x/2x/4x/10x, in one CPU-free Renode process lasting22.165 wall seconds.** There was no firmware image, native execution, multi-MCU VM, direct duty override, temperature injection, time jump or live-run modification. All protected source, controller, original-profile and firmware hashes were unchanged across validation.

The actual production GPIO, ADC, thermal models and bindings were compiled and loaded, not reimplemented in Python. The Python recurrence is independent analytical corroboration and is labeled separately. The actual C# uses normal automatic10ms callbacks. Tests generate GPIO register writes only in their isolated CPU-free machine. Those writes are not part of a native runtime profile.

Coverage for each factor,157 assertions:

- Loaded real candidate profiles; no setup GPIO configuration/latch writes; initial low, initially high resolved nozzle and bed pads, high latch in input mode, disabled automatic timer rejection, and non-PA0 callback rejection.
- Real2.5ms-high/7.5ms-low PWM, quarter-duty response,202 forwarded edges including the final boundary transitions; full-power rates; measured target crossings; ADC register delivery; PB9 high with zero modeled fan duty.
- Physical cooling after actual GPIO-low; open and short rails; physical heating independent of open sensing; retained heat/faults across reset; no stale-high revival; explicit GPIO-first reset sequence and genuine-edge recovery.
- Nominal nozzle approach to 325°C; unchanged 40W default comparison remaining below225°C. Separate negative-only zero-conductance nozzle reaches370°C/out-of-table rail then the original 400°C latch. Nominal bed sustained high reaches its original 150°C latch then cools. Faults, resets and renewed edges do not reopen either latch. The zero-conductance negative is never a selectable runtime profile.
- Main observed models and quiet duplicate models receive the same real GPIO stimuli/faults/resets. Temperature, ADC, integrated duty and latch values remain equal at each stage boundary despite frequent reads of the observed pair. This is model-level observational invariance, not a native telemetry/transport performance result.
- All52,652 trace ADC readings across 25,826 rows independently matched the recovered nozzle coefficients and unchanged bed conversion. Zero dropped rows. Every stage marker was required before aggregate pass publication.

| Factor | Actual nozzle / bed target crossing after full-high start s | Actual nozzle / bed first full-second rise °C |
|---|---:|---:|
| 1x | 114.75 / 121.55 | 2.9776 / 0.3327 |
| 2x | 57.25 / 60.65 | 5.9110 / 0.6642 |
| 4x | 28.51 / 30.20 | 11.6479 / 1.3234 |
| 10x | 11.26 / 11.94 | 27.8696 / 3.2717 |

These actual crossings start after a preceding1s quarter-duty warmup, so they are slightly earlier than ambient-start calculations. Each was compared with the exact trajectory from its own measured warm starting state within 21ms. The fixed 10ms integration interval is not divided by factor.

`evidence/analytic-static.json`, `parameter-comparison.csv`, and `evidence/actual-csharp/summary.json` contain machine-readable results, full source/compiled hashes and factor-specific trace manifests. C# tests do not prove native PID or native watchdog compatibility, real hardware parameters, whole-machine reset ordering, closed-loop bed behavior, or print readiness.

## Reproduce and select later

From the snapshot root:

```
python3 -B printer-shared-mcu/experimental/accelerated-functional-thermal/generate.py --all
python3 -B printer-shared-mcu/experimental/accelerated-functional-thermal/checks.py
```

The first generates profiles only; the second does not start a machine. Invalid factors, NaN/infinity, bools and unsupported intermediate scales are rejected. To rerun the actual C# suite in an explicitly scheduled lightweight slot:

```
python3 -B printer-shared-mcu/experimental/accelerated-functional-thermal/checks.py --execute-csharp
```

It has a 30-wall-second upper bound, compiles once, creates CPU-free factor fixtures sequentially, and requires all stages plus independent analysis before emitting the aggregate pass. See `INTEGRATION.md` for later native selection and the deliberately separate functional criterion. Existing controllerV3 and launcher integration are not edited or automatically extended by this package.

## Checkpoint and restoration

`checkpoints/accelerated-functional-pre-csharp-source.tar.gz` is the pre-use source/text checkpoint. The final archive and hashes are listed in `checkpoints/final-v3.json`. Both contain only this isolated package plus source dependency copies under `dependency-snapshot/`; no firmware binaries, memory snapshots or VM state. See `RESTORE.md`. External protected-input hashes allow comparison without changing those files. The copied dependencies are reference material, never an instruction to overwrite live dependencies.
