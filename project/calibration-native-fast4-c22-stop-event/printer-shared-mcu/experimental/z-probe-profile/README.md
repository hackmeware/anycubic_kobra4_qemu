# Explicit synthetic Z profile integration

This profile composes existing, separately tested experimental pieces into one shared-MCU model. It is **synthetic geometry and force calibration with idealized digital CS1237 behavior**, not hardware electrical timing fidelity, recovered strain-gauge calibration, validated physical wiring, completed native Z homing, calibration or printing.

## Selection and unchanged defaults

The central selector is `--z-probe-profile synthetic-functional`. The native fixture shell exposes `Z_PROBE_PROFILE=synthetic-functional`; it additionally requires the caller to choose `GLOBAL_QUANTUM_US=1`. The parser default is `none`, which changes neither generated model bytes, launch script nor profile metadata. Offline tests compare the complete generated tree and logs against the captured pre-change generator for electrical, dynamic-driver and learned-baud profiles. The strict sensor sources remain available, unchanged, under `nozzle-renode/experimental/cs1237-native` and `cs1237-protocol`; their100-MIPS failures have not been relabeled as successes.

Requirements:

- Shared MCUs and `electromechanical-driver` plant.
- An explicit final setup `emulation SetGlobalQuantum "0.000001"` before execution. Nested setup includes are checked; early execution, declared MIPS/quantum overrides and conflicting reserved Z model/contact owners are rejected. This is configuration validation, not a general sandbox for arbitrary monitor/C# programs.
- No implicit CPU-speed, clock-frequency, instruction-time or threshold adjustment. Normal CPU performance remains100 MIPS.
- Fixed tested bounds: maximum physical-state age100000 ns and maximum motor producer lead1000 ns. No automatic relaxation. A native bound failure requires investigation.
- Construct fresh emulations. MCU reset and saved-state restoration are not new epochs or automatic rebinding/reconnection.

The pre-existing learned-baud choice remains independent: `NOZZLE_TMC_MODEL=autobaud` or `--nozzle-tmc-model autobaud` still requires its own explicit1 µs setup. Selecting synthetic Z does not silently choose learned baud or heater bindings.

## Synthetic parameters

CLI names are below; corresponding shell variables are uppercase with hyphens converted to underscores. For example `--z-bed-relative-mm` is `Z_BED_RELATIVE_MM`. Supplying a Z parameter without selecting the profile is rejected.

| CLI | Default | Meaning |
| --- | ---: | --- |
| `--z-bed-relative-mm` | -10 | Assumed bed relative to initial rotor position, mm |
| `--z-opposite-stop-relative-mm` | 252 | Assumed opposite bound, mm |
| `--z-bed-side` | minimum | Decreasing relative Z approaches the bed |
| `--z-stiffness-n-per-mm` | 20 | Linear contact stiffness |
| `--z-damping-ns-per-mm` | 0.05 | Inward damping in N s/mm, not nanoseconds |
| `--z-baseline-counts` | 0 | Force-free signed24-bit ADC code |
| `--z-counts-per-n` | 10000 | Synthetic ADC sensitivity |
| `--z-signal-polarity` | 1 | Synthetic positive orientation |
| `--z-history-capacity` | 4096 | Bounded eligible physical snapshots |
| `--z-query-trace-rows` | 100000 | Bounded accepted-candidate trace rows;0 disables trace |

All parameters are validated and recorded. The fixture is explicitly enabled only in the selected profile. The original core's contact torque changes the integrated rotor/current/back-EMF response, and that same torque is the force source. No geometry-to-PB2 shortcut, direct PA7 write, firmware/homed flag write, threshold change or injected force sample is introduced.

## Composition order

1. Normal shared generation and optional learned-baud selection.
2. Apply **exactly two additive disable methods** to the generated `PrinterMotor` core copy only. Record source, pre-selection copy, reviewed patch, extension helper and result hashes. The production core stays unchanged.
3. Include the namespace-isolated native GPIO wrapper before the generated nozzle platform is loaded; replace only that platform's gpioA class.
4. Create the explicit functional sensor during nozzle setup with the same baseline as the physical fixture.
5. In the motor setup tail, load and enable the fixture; construct/capture/register the source; switch to nozzle and bind the exclusive timed provider; return to motor. All machines, GPIO clock and protocol remain at common zero.
6. Connect the actual nozzle PA7 to main PB2 using the proven destination-first GPIOConnector helper exactly once, then attach independent passive edge observers. All occurs before the first RunFor.

The source observes the existing TMR8 ADC-trigger fan-out after the plant. It does not add a physical timer or integrate from a sensor read. Conversion candidates choose actual past state only. Missing, stale, skewed, rolled-back, duplicate or conflicting ownership fails closed.

The noninverting cable is a declared synthetic fixture assumption. Initial connector-default state may be visible until normal queued source initialization settles. Main GPIO reset clears the external PB2 drive, and unchanged PA7 is not automatically resent. Source re-selection can detach observers. This integration therefore wires at startup only and makes no hot-reconnect/reset-recovery claim.

## Evidence

`z-probe-profile.json` and `shared-profile.json` record profile, synthetic parameters, bounds, wiring assumptions and generated hashes. `shared-model-manifest.json` records original/generated source transformations. The launcher automatically appends read-only final evidence when the profile is selected:

- `z-binding-status.json`: exact peripheral/deadline/machine/motor callback clocks and clock-guard diagnostics. Machine elapsed time can be a later scheduling boundary; the port is compared exactly to its owning ClockSource.
- `z-sensor-status.json`, `z-sensor.csv`: conversions, reads, config, semantic/provider errors, physical short-pulse/ownership violations and drops.
- `z-nozzle-gpio.csv`: bounded actual GPIO accesses. Drop and synchronization counters are printed in the Renode log.
- `z-force-query.csv`: selected past physical state, torque/force/code, candidate deadline and age. This is **accepted conversion-query history**, not every producer capture or proof the candidate committed.
- `z-force-status.json`: source/fixture state, actual capture/retirement/query counts, retained history, errors and min/max capture intervals.
- `nozzle-z-probe-edges.csv` and `main-z-probe-edges.csv`: genuine resolved PA7 and PB2 edges with source-local shared-time timestamps. Enabled/rows/edges/drop/error counters are printed before/after stopping. Observer reset stops its stream.
- `final-nozzle-sram.bin` (20 KiB) and `final-nozzle-fault-words.bin` (CFSR,HFSR).

The frozen adapter status says `main_pb2_connected:false` because that adapter does not own a cable. The separately installed connector is documented in profile metadata and observed by the edge traces; do not interpret that adapter-local field as a system wiring test.

Sensor and GPIO detailed in-memory traces each cap at200000 rows. They can fill early, well before a long Z run. Force queries default to100000 rows; edge streams cap at100000 per board. Dropped rows mean incomplete capture and must be disclosed. Final exports are best-effort after clean paused termination; abrupt process/model failure may prevent them. A later native Z run needs a bounded observation-window/streaming design if early detailed buffers fill. No unsupported trace reset has been added here.

## Lightweight verification and boundary

Run offline tests with:

```
python3 -m unittest discover -s rv1106-at32-link/tests -p 'test_z_probe_profile.py' -v
```

The generated-model smoke runs:

```
python3 printer-shared-mcu/experimental/z-probe-profile/run_model_smoke.py
```

It loads all three generated platforms with learned baud selected, but **loads no firmware, executes no CPU instructions and advances no time**. It verifies sensor/source binding at zero, one true initial capture, zero force and retained bounds. It refuses to reuse prior status exports; archive the previous evidence directory before repeating.

Evidence is under `evidence/synthetic-z-profile-integration/`. This checkpoint does not itself validate real startup TMR8 freshness at the autonomous302 ms sensor candidate. A separate short original-three-MCU standalone startup/sample smoke, with no QEMU, no host UART replay and no homing/heater/print commands, is the next gate. Full native Z replay is not authorized by generation or this model-only smoke.
