# Optional synthetic 230°C nozzle / 60°C bed fixture

This is an **explicitly hypothetical virtual scenario**, not measured printer hardware, a real calibration, a completed native PID test, or print readiness. It is inactive by default. No firmware, central source, ordinary profile, shared launcher, historical evidence, or `at32-renode/docs/THERMAL-BINDINGS.md` was edited. The original native low-temperature result remains separate evidence.

## Parameter choice and limits

At ambient 25°C, the unchanged plant solves `C dT/dt = P duty - G (T - 25)` over each existing 10ms PWM integration window. Its equilibrium is `25 + P duty / G` and time constant is `C/G`.

| Fixture | Hypothetical P | C | G, no fan | Initial full-power rate | Full-duty equilibrium | Duty maintaining target | Ideal full-power time from ambient |
|---|---:|---:|---:|---:|---:|---:|---:|
| Nozzle, target 230°C | 60 W | 20 J/K | 0.2 W/K | 3°C/s | 325°C | 68.3333% | 114.990558 s |
| Bed, target 60°C | 200 W | 600 J/K | 1.5 W/K | 0.333333°C/s | 158.333°C before model guard | 26.25% | 121.795676 s |

Only the **optional nozzle power** changes from the existing illustrative 40W. The previous 40W/20J/K/0.2W/K plant asymptotes to 225°C and cannot sustain 230°C. Choosing 60W leaves about 31.7% power headroom at 230°C without changing the existing 100s thermal time constant. It is a declared scenario choice, not fitted from a printer, a claim of an installed 60W heater, or a way of making firmware calibration pass. Bed parameters remain exactly the existing illustrative values because they already support 60°C.

The bare nozzle full-high equilibrium is above the recovered native 320°C limit. That is not permission to heat there in native operation: original native guards must act first. The offline equilibrium test has no native firmware and deliberately distinguishes plant behavior from native safety. The bed's 150°C environmental maximum similarly precedes its mathematical 158.333°C equilibrium. No guard is raised or disabled.

These are single-state linear models. There is no measured heater power, identified heat capacity/loss, radiation, sensor lag, airflow distribution, heat-break dynamics, material-dependent heat transfer, electrical sag, or thermal interaction between bed and nozzle. Full-power times are analytic plant predictions, **not native PID completion times**.

## Sensors, pins, and original guards

- Nozzle: actual resolved PB8 -> heater input 0; physical temperature -> unchanged full recovered `NTC ZM3863 HNS112HC4570G0` curve -> ADC0/PA0. Verified 4700Ω pullup and 12-bit ADC. At 25°C code4023, at 230°C code468. The entire recovered table and native inverse interpolation remain in the unchanged nozzle peripheral.
- Bed: actual resolved PA0 -> heater input 0; physical temperature -> unchanged existing B3950/100kΩ/4700Ω model -> ADC8/PB0. Runtime sensor type B3950 is recovered, but the 4700Ω bed divider and physical bed calibration remain unverified assumptions. At 25°C code3911, at 60°C code3444. **This is not a newly recovered bed curve.**
- Both original thermal classes are compiled unchanged. Nozzle environmental maximum400°C and bed maximum150°C, stop-at-maximum latches, 10ms automatic updates, GPIO duty integration, ADC fault rails and reset behavior are preserved.
- Open/short faults alter sensing only, not stored physical heat. MCU-style reset retains heat, faults and latch history while clearing accumulated command duty. Bindings do not reassert a stale pre-reset high.
- Nozzle temperatures outside the recovered −40..360°C table remain visibly invalid, with `SensorCurveOutOfRange` and an ADC fault rail. They are not clamped to a plausible sensor temperature.
- The profile and bindings never use `SetDutyCycle`, `SetFanDutyCycle`, `Advance`, `ColdReset`, or temperature writes. Tests exercise `Advance` rejection while automatic integration is running, but do not advance physics manually. Explicit sensor faults exist only in negative tests.

Recovered nozzle runtime limits: min0°C, max/max_safe320°C, min_extrude60°C, max_power1, PWM0.1s, smoothing1s. Recovered bed max_safe100°C and max120°C. Native ADC guards remain original: nozzle 8-sample sum962..32593, bed15205..32309, error limit4. The target codes are within these original ranges. Original PID values and heating watchdog behavior have **not** been validated with this hypothetical plant. No recovered heat-up watchdog/check_gain_time/heating_gain values were found in the inspected evidence; upstream defaults must not be substituted as evidence.

## PB9 stays observed and thermally unbound

Recovered configuration calls PB9 `heater_fan extruder_fan`, with heater_temp50°C, fan_speed1 and shutdown_speed1. Native traces show activation even at 25°C when target demand is nonzero. It is not established as a generic part-cooling fan, and a temperature-only invented fan controller would be wrong.

The physical thermal coupling of this heat-break fan is unknown. Therefore PB9 is not connected to thermal input1; the existing passive observer may still record its real level. LastFanDuty must remain0. The unused generic +0.3W/K fan conductance is not measured evidence: connecting it would drop the 60W plant's equilibrium to145°C and defeat the intended scenario. This limitation must remain visible in any later calibration result. Leaving it unbound is an explicit simplification, not proof that real fan cooling is negligible.

## Optional setup for a future paused run

This directory does **not** modify the central launcher. The parent/integrator must select it explicitly and avoid loading another thermal writer for the same ADC channel.

1. Use a fresh paused setup, before firmware execution. Do not hot-swap a live thermal plant, erase retained heat, or attach this on top of an existing thermal fixture.
2. Nozzle: load unchanged `nozzle-renode/peripherals/VirtualPrinterThermal.cs` and `NativeNozzleHeaterBinding.cs`, then this directory's `nozzle.repl` **instead of** the usual recovered-nozzle fixture and binding profile. PB9 remains unbound.
3. Main: load unchanged `at32-renode/peripherals/VirtualPrinterThermal.cs` plus this directory's `ResolvedBedHeaterBinding.cs`, then `bed.repl` **instead of** the usual `virtual-bed-ntc.repl` and `virtual-commanded-bed.repl`.
4. For shared namespace generation, substitute source prefix `Antmicro.Renode.Peripherals.AT32` with `...PrinterNozzle` for nozzle sources and `...PrinterMain` for main sources, including the new bed binding. In respective REPL files change type prefix `AT32.` to `PrinterNozzle.` or `PrinterMain.`. `ThermalExperimental` remains unchanged. The CPU-free runner compiles and loads these exact generated profiles.
5. Keep initial resolved pad synchronization, edge forwarding and status exports. No source GPIO configuration/write is performed by either binding. PA0/PB8 must be the actual firmware outputs, not a monitor-generated high or direct duty override in native runs.
6. Existing nozzle binding export: `sysbus.nativeNozzleHeaterBinding WriteStatus <path>`. Bed export: `sysbus.syntheticBedHeaterBinding WriteStatus <path>`. Existing passive nozzle observer can be added independently and must keep its stream/status/drop accounting.

The new `ResolvedBedHeaterBinding` only addresses initial resolved PA0 state and subsequent real edges, analogous to the already-tested nozzle binding. It preserves other GPIO sinks. Its constructor requires automatic integration; it must be used with this fresh active-high profile and not mixed with direct-duty experiments. Reset does not drive PA0 or reassert old command state. It is not a new controller or safety guard.

## CPU-free offline tests

Run from the snapshot root:

```
python3 printer-shared-mcu/experimental/synthetic-calibration-thermal/run_tests.py
```

The runner creates a temporary isolated Renode machine with **no CPU or firmware image**. It uses the actual production GPIO/ADC/thermal implementations, namespace-rewritten only in temporary copies. Test inputs are synthetic GPIO register writes. The test class is not part of either optional runtime profile.

Final run: **93 actual C# assertions and28 explicit profile-value checks passed**, about16s wall time for1390 virtual seconds, with0 dropped observations. Independent analysis checked2782 ADC readings across1391 trace rows against the original recovered nozzle coefficients and unchanged bed equation. `results/test-summary.json` records original/compiled source hashes and verifies firmware, central plant sources, original profiles and the historical-status document unchanged during the run.

Coverage:

- Loading both actual optional profiles; initial low, initial high, input-mode high-latch distinction, disabled timer rejection, non-PA0 callback rejection; no setup GPIO writes.
- Actual 2.5ms-high/7.5ms-low PWM. Both plants match the quarter-duty analytic result;202 edges include the final boundary rise and immediate low.
- Full-power initial rates, physical target crossings and actual ADC-register delivery. First full-second rises were2.97762444°C nozzle and0.33270920°C bed after the preceding quarter-duty warmup.
- Full power starts at virtual1s. Actual crossings occur at115.75s nozzle and122.55s bed, within a 20ms observation allowance of the analytical trajectory from their already slightly warm states. These are **not** native target acceptance or closed-loop regulation results.
-20s of cooling after actual output-low; PB9 is high but modeled fan duty stays0.
- Both open/short rails, continued physical heating under open sensing, reset heat/fault retention, and no stale-high reassertion. A separate GPIO-first reset sequence on the same primary fixtures followed by genuine low/high edges resumes physical heating. This tests that explicit ordering, not every whole-machine reset order.
- Actual full-duty long-run nozzle asymptote324.998429°C versus unchanged default224.998953°C.
- A **separate negative-only no-cooling fixture** sets G=0 while retaining60W/20J/K and the original400°C guard. It reaches physical370°C and publishes out-of-table code0, then trips400°C and remains latched across open/short, reset and renewed GPIO edges. This is not the proposed nominal plant.
- A separate normal-parameter bed held high trips the original150°C environmental latch then cools. Reset/faults/renewed edges cannot reopen it.

`results/actual-plant.csv` is a bounded passive one-second trace of the primary fixtures; long-negative assertions and final values are in the log/JSON. Sensor ADC checks verify both conversion and actual register delivery. The runner requires machine-readable completion markers for every stage and the exact assertion count, rejects monitor/compiler errors, clears old result manifests before reruns, and emits its aggregate manifest only after the independent analysis passes. The tests prove the model's causal plumbing and existing model guards, not native firmware watchdog performance or hardware safety.

## Proposed later native high-temperature test, not performed

1. Preserve the existing low-temperature run and snapshots. Create a separately labeled opt-in run with source hashes and this hypothetical parameter manifest. Verify baseline physical/ADC/native temperatures and faults before commanding heat.
2. Use a separately verified normal native temperature-setting route. The current diagnostic `make_grpc_probe.py --temperature-c` remains intentionally bounded0..35; do not silently extend it or pretend it sent230°C. This package sends no requests.
3. Test heaters separately first: normal nozzle230°C, then normal bed60°C. Keep original firmware PID, safety thresholds, heartbeat, ADC guards and shutdown paths. No readiness, target, duty, homed, sensor or success flag may be synthesized.
4. Capture accepted native target, actual GPIO/PWM edges, physical temperature, ADC and native interpreted temperature, PB9 observation, sensor fault/out-of-range/latch state, and transport/observer errors. Compare independently integrated GPIO power against the physical trace. Do not subtract different clock domains without the existing verified mapping.
5. For a first bounded **step-response test**, propose an external cap of240 virtual seconds from accepted target, and early normal target-zero if physical nozzle reaches250°C or bed75°C, a native shutdown/fault occurs, telemetry becomes stale, or a source/clock failure is reported. These are experiment stop criteria, not changes to native safety. Require a stable native/physical band (for example target±2°C for30s) only as a reporting criterion; failure is a negative result, not reason to change constants or extend the cap automatically. This cap does not claim to cover a complete multi-cycle PID calibration.
6. Send normal target-zero on completion or abort. Verify its native response, actual PB8/PA0 returning low and subsequent physical cooling. A client/RPC timeout alone does **not** clear demand. If command transport cannot be confirmed, pause/stop the virtual run and preserve state/evidence rather than claiming successful shutdown or resetting the hot plant to ambient.
7. In separate authorized native negative runs, verify open/short shutdown with the new profile, warm reset behavior, and heater-disconnected/no-rise behavior. Prior native sensor fault evidence is preserved, but it does not replace this integration check. Recover actual heat-up watchdog behavior before asserting its timeout compatibility. Model no-cooling/stuck-high limits remain offline-only until a distinct native negative is explicitly scoped.

No native high-temperature, bed closed-loop, PID calibration, force probe, homing or print run was performed here.

## Evidence and restoration

- Original equation/guards: `nozzle-renode/peripherals/VirtualPrinterThermal.cs`, `at32-renode/peripherals/VirtualPrinterThermal.cs`.
- Recovered nozzle table, pullup, configured limits and PB9 role: `evidence/recovered-nozzle-thermal/nozzle-thermal-recovered-evidence.json`, with original RAM/ELF hashes and offsets.
- Bed config and uncertainty: `at32-renode/docs/thermal-runtime-config-evidence.json`, `at32-renode/docs/THERMAL-BINDINGS.md`.
- Original native ADC limits: both board `docs/verified-adc-configuration.json` files. Prior native fault results: `evidence/sensor-fault-summary.json`.
- Existing native low-temperature evidence: `evidence/native-nozzle-heating-response/README.md`; only25→32.807°C then cooling is established there.

The checkpoint contains only this isolated experimental directory, its report and test artifacts. Restore by extracting at the snapshot root. It does not replace firmware, original profiles, central sources or launcher. The manifest lists every packaged file; original dependency hashes are in `results/test-summary.json`. No integration/default switch is included.
