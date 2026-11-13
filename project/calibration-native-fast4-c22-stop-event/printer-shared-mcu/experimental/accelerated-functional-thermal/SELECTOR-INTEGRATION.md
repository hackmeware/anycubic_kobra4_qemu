# Explicit accelerated selector integration

This is a separate, opt-in capacity-only functional environment. It is not a
realistic printer thermal model, real PID validation, calibration completion,
or print readiness. Original native PID, PWM, sensor smoothing, firmware,
NTC conversions,10ms thermal updates, environmental latches, native safety
limits and actual GPIO heater inputs remain unchanged.

## Selection

- First authorized choice: `--thermal-profile accelerated-functional-4x`, or
  `THERMAL_PROFILE=accelerated-functional-4x` with the existing event wrapper.
- Separate fallback: `accelerated-functional-2x`, only after the parent records
  a4x failure and explicitly selects it. No automatic fallback is implemented.
- Both require explicit `GLOBAL_QUANTUM_US=1`, shared MCUs and the existing
  electromechanical-driver profile. No emulation clock is accelerated.
-4x capacities are nozzle5J/K and bed150J/K.2x capacities are10J/K and300J/K.
  Powers remain60W/200W; losses remain0.2W/K/1.5W/K. Selecting the fixture does
  not itself command either heater or authorize a bed-heating test.
-10x is not an accepted native launcher choice. It remains isolated model
  stress evidence only. Existing `none` and `synthetic-calibration` are unchanged.
- Keep `NATIVE_NOZZLE_HEATER=0` or unset. Profile ownership creates the single
  actual PB8/PA0 binding and the existing bounded bed/nozzle observers.

## How legacy bytes are preserved

`thermal_profile_selection.py` is unchanged, including its source hash.
The new `accelerated_thermal_profile_selection.py` dispatcher delegates `none`
and `synthetic-calibration` to it without changing inputs, outputs or metadata.
Only imports in run_link/shared_mcu and the explicit wrapper choices changed.

For an accelerated selection, generation prepares the established isolated
setup, then replaces its two sole selected REPL files with the reviewed
capacity-only variants before any generated setup executes. It does not load
another writer, modify a running plant, erase retained heat, or call an extra
physics integration. All original setup/final-diagnostic restrictions apply.

Hashes pin the reviewed2x/4x files, parameter manifests, generator and original
selector. In addition to hashes, the dispatcher independently compares every
significant REPL line against the baseline and rejects any difference except
the single declared heat capacity. Arbitrary duty, sensor, GPIO/ADC, guard,
clock or MIPS overrides remain rejected by the original setup policy.

## Manifest and telemetry

Existing `thermal-profile.json` fields and `shared-profile.json.thermal_profile`
remain consistent. Fast selections change `selection`, the two heat capacities,
selected source/generated hashes, and add:

- `functional_acceleration_factor`:4 or2.
- `unrealistic_dynamics`:true, `real_pid_validation`:false.
- `capacity_scaling_only`:true.
- `native_pid_and_sensor_smoothing_unchanged`:true.
- `emulation_clock_scale`:1, `automatic_factor_fallback`:false.
- `accelerated_scenario`:the exact selected parameters.json.
- `baseline_integration_helper_sha256` and the new dispatcher's
  `integration_helper_sha256`.

Streams, bounds, original model fault/latch exports, PB9 observation and final
status counters retain the existing schema. PB9 remains thermally unbound.
Native target acceptance, interpreted temperature, external observation
criterion and normal-zero/off/cooling must be verified by the separately
versioned controller. This selector does not relax its criterion or synthesize
success. Changing thermal dynamics can still cause native faults or overshoot;
those remain valid negative results, not reasons to alter original guards.

## Verification

- Five new Python test methods cover complete legacy byte identity, explicit
  composition for both factors, inherited restrictions, source hashes plus
  independent capacity-only semantics, and wrapper rejection of10x.
- Byte identity includes all generated source/scripts/manifests/log artifacts
  for electrical/default, electromechanical/default, default Z+autobaud, slow
  thermal alone, and slow thermal with Z+autobaud.
- The existing19 Python shared/Z/slow-thermal tests continue to pass.
- Both fast selections load the generated three-MCU+Z+autobaud composition at
  zero with no firmware loaded, no CPU execution and no time advance. Original
  ambient ADCs4023/3911, model guard state, exclusive bindings, no fan duty,
  original Z100us state-age/1us lead bounds and zero observer loss/errors pass.
- No production peripheral, original firmware, original thermal selector,
  slow profile or Z source changed. The component worker's previously reported
  capacity-only model tests remain separate evidence.

The preceding slow native run was fully stopped and exported before application.
Its native zero/off/cooling was NOT verified because a console-capture collision
aborted the attempt. Preserve that result as incomplete; do not require an
impossible retroactive verification or relabel it successful. Parent authorization
allowed central edits only after final export. The next4x test is a genuinely
fresh cold virtual scenario, never a hot swap or temperature reset inside the
old run. The controller-owned graceful-stop hook and console serialization fix
are prerequisites for launching it. No native accelerated run was started here.

The selected controller criterion is physical AND fresh native target±2°C each
sustained5 consecutive source/controller virtual seconds, explicitly reported
as functional-only. The accelerated heat cap is60 virtual seconds, with normal
zero initiated by52s; external nozzle250°C/bed75°C caps remain unchanged. This
is not the earlier arrival-in220..240°C plus5s response proposal, and it is not
real PID validation or calibration completion. Slow mode retains its original
30s stability/240s cap. No automatic fallback, native retuning or cap extension
is authorized by the selector.

Source pins for the controller are in `integration-plan/runtime-source-pins.json`.
Final test evidence is under `evidence/integration-*.json` and
`evidence/integration-smoke-{4x,2x}-r1/`. The focused checkpoint excludes the
controller's concurrent changes and does not replace the parent's whole-source
freeze before the next native run.
