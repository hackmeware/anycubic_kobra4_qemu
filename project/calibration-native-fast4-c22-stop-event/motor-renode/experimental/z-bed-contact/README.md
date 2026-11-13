# Experimental synthetic Z bed-contact fixture

This is **opt-in, synthetic laboratory geometry and force calibration**, not recovered physical Kobra4 geometry and not proof of successful native probing, homing, calibration or printing. It leaves original firmware thresholds, GPIO, DIAG, endstop and homed-state handling untouched. No firmware, native application or physical hardware is accessed by the included tests.

## Status and exact scope

- New files live only in this experimental directory. Production `GenericStepperElectromechanical.cs` is unchanged.
- `disable-contact.patch` proposes **two additive methods**: `GenericStepperRotor.DisableContact()` and `GenericStepperElectromechanical.DisableRelativeContact(axis)`. The wrapper integrates the existing contact through the current virtual timestamp before disabling it. Review/apply this patch separately before integrating the fixture.
- `run_tests.py` creates a temporary extended copy for tests, never patches production. It runs the pre-existing 24 equation checks against both original and extended cores, plus CPU-free fixture tests with actual timer-driven current/rotor integration.
- The current default run profiles never load this fixture. No native calibration/print run was attempted here.
- The isolated CS1237 adapter is separate work. `ReadSyntheticAdcSample` is a `Func<int>`-compatible sample source; this fixture does not wire the ADC, drive its pins, drive the native Z probe, or set firmware thresholds.

## One mechanical cause, one force source

The fixture configures the existing core's unilateral compliant contacts. That same spring/dashpot torque enters the motor's integrated equation of motion, changes speed and back-EMF, and changes its current feedback. Sensor force is read directly from `plant.GetContactTorqueNewtonMeters(2)`, not recomputed from commanded motion or a second contact law.

Recovered **software** rotation distance is 8 mm/revolution. Assume a rigid, lossless ideal lead screw with positive motor rotation increasing relative Z:

```
l_mm = 8 / (2*pi) mm/rad
l_m  = l_mm / 1000 m/rad
F_bed = max(0, bed_direction * actual_contact_torque_Nm) / l_m
bed_direction = +1 for a minimum-side bed, -1 for a maximum-side bed
```

Thus 1 N corresponds to 0.001273239544735163 N m. Mechanical power is consistent: `F*v = torque*omega`. Opposite-stop reaction is not nozzle/bed load and maps to zero. The assumed ratio does not model screw efficiency, friction, backlash, gravity, a second Z actuator, nozzle/bed shape, XY-dependent height, or thermal expansion. Actual native Z rotor sign relative to downward probing remains to be verified.

Linear stiffness and damping are converted to the exact units expected by the existing generic contact:

```
angular_stiffness_Nm_per_rad = stiffness_N_per_mm * l_mm^2 / 1000
angular_damping_Nm_s_per_rad = damping_N_s_per_mm * l_mm^2 / 1000
```

The existing core produces zero force until penetration is strictly positive, including zero damping force at the boundary. On penetration, damping only resists motion farther into the stop. During separation, the spring can still push outward until penetration reaches zero; it never pulls into the bed. This is the existing non-adhesive contact assumption, not an added probe-trigger rule.

## Explicit scenario defaults

| Parameter | Synthetic default | Meaning |
|---|---:|---|
| Enabled | false | Loading alone has no contact effect |
| Bed relative position | -10 mm | Initial rotor Z=0 is assumed 10 mm above the bed |
| Opposite stop | +252 mm | Assumed opposite physical bound, 262 mm above the bed |
| Bed side | minimum | Decreasing rotor-relative Z approaches the bed |
| Linear stiffness | 20 N/mm | 0.05 mm compression gives 1 N at zero speed |
| Inward-only damping | 0.05 N s/mm | 2 mm/s inward motion adds 0.1 N during penetration |
| ADC baseline | 0 counts | Synthetic force-free code |
| ADC sensitivity | 10000 counts/N | Arbitrary explicitly chosen virtual calibration |
| ADC signal polarity | +1 | Positive force increases the signed code |

The original host configuration says Z home=0, software limits -4..262 mm. Those are not measured hard stops. The fixture does **not** use -4 mm as a physical bed, does not assign the firmware an initial coordinate, and does not mark an axis homed. The +252 mm upper bound follows the separately assumed 10 mm initial clearance and an assumed 262 mm bed-to-upper span. Both contact positions are configurable. For an upper-side bed, set `bedIsMinimum: false` and give `bedRelativeMillimeters` greater than the opposite bound.

Geometry inputs must be finite and within +/-1000 mm, stiffness `(0,10000]` N/mm, damping `[0,100]` N s/mm, ADC sensitivity `(0,1e9]` counts/N, baseline in signed 24-bit range, and polarity +/-1. These bounds avoid nonsensical setup; they are not a physical safety certification or force limiter. Numerical divergence still fails explicitly in the existing core.

## Disabling, ownership and observation

`SetEnabled false` really disables the Z rotor contact. It does not park stops far away or merely hide force. Position, velocity and current remain continuous. Removing an externally imposed compressed fixture also removes its spring potential energy; this is an explicit external fixture-removal intervention, **not** an energy-conserving release. For a natural release, move away while the fixture remains enabled.

Enabling requires the current state to lie between the configured stops. The wrapper rechecks after the core advances old dynamics to now; it rejects installation into already penetrated material. MCU reset does not move, enable or disable the fixture. The fixture exclusively owns Z contact configuration while loaded; do not call the core's Z `ConfigureRelativeContact` independently or attach a second fixture. X/Y contacts are unaffected.

All sensor getters are read-only: they never advance time, integrate motion, read firmware memory, publish current ADCs, or drive pins. `StateTimeSeconds` is the most recent Z integration timestamp. A future CS1237 adapter should latch `ReadSyntheticAdcSample()` only on real modeled conversion deadlines and record this state time to expose staleness. Sampling does not itself synchronize a stale plant.

Signed 24-bit output is rounded halfway away from zero and saturates to `[-8388608, 8388607]`. `AdcWouldSaturate` exposes analog full-scale overflow. This limits the ADC representation only; it does not cap the physical force or alter firmware detection thresholds. No claim is made that this arbitrary calibration is the physical ADC/load-cell transfer curve. The CS1237 adapter owns channel/gain/protocol semantics; this fixture's code is only a clearly labeled force-channel source.

## Reproduce the lightweight checks

From the snapshot root:

```sh
python3 motor-renode/experimental/z-bed-contact/run_tests.py
```

Expected: original 24 equation checks; extended-core 24; fixture equation, observer and disable-timing passes. Evidence is written under `evidence/synthetic-z-bed-contact/`, including exact source hashes. No CPUs or firmware images are loaded. The timer-driven test uses a **separate tiny laboratory bed at -0.01 mm** to reach contact within 1 ms; it does not validate the default 10 mm-clearance scenario or native firmware direction.

Coverage includes disabled/no-excitation baseline; inward velocity before contact; exact boundary; force/torque/power/energy conversion; inward damping; separation; upper-side direction; opposite-stop exclusion; actual rotor response; true disable; unchanged angle/current/velocity on removal; reset retention; invalid setup rejection; ADC full-scale/polarity/rounding; read-only repeated sampling; and old loaded contact integration through the disable timestamp. Original 24 checks run on both source variants establish existing regression coverage, not exhaustive byte-for-byte numerical equivalence for all scenarios.

## Proposed integration commands, after review only

The commands below change the core only if the reviewer chooses to apply the explicitly separate patch. Do not apply during a release freeze.

```sh
# Review first. This is NOT executed by the test runner or overlay generator.
patch --dry-run -p1 < motor-renode/experimental/z-bed-contact/disable-contact.patch
patch -p1 < motor-renode/experimental/z-bed-contact/disable-contact.patch

# Regenerate namespace-isolated core copies through the normal shared-MCU workflow.
# Then generate a separate optional overlay. --shared targets PrinterMotor types.
python3 motor-renode/experimental/z-bed-contact/create_overlay.py \
  --shared --output /tmp/synthetic-z-overlay

# Append this to an otherwise explicitly selected motor setup profile.
cat rv1106-at32-link/tests/assumed-centered-xy-contact.commands \
  /tmp/synthetic-z-overlay/enable.commands > /tmp/xyz-synthetic-contact.commands
# Pass --motor-setup-commands /tmp/xyz-synthetic-contact.commands to the existing
# --shared-mcus --motor-plant electromechanical-driver experimental run command.
```

`create_overlay.py` refuses to generate an integration overlay until the proposed methods exist in the production core. It does not apply the patch. Edit the generated `fixture.repl` before loading to choose different explicit synthetic geometry/calibration; preserve it with that run's evidence. `load.commands` creates the fixture disabled; `enable.commands` adds the explicit enable command. The monitor supports:

```
sysbus.zBedContactFixture SetEnabled true
sysbus.zBedContactFixture ReadForceNewtons
sysbus.zBedContactFixture ReadSyntheticAdcSample
sysbus.zBedContactFixture AdcWouldSaturate
sysbus.zBedContactFixture StateTimeSeconds
sysbus.zBedContactFixture SetEnabled false
```

Remaining integration blockers: review/apply the two-method extension; load the overlay only in a deliberately experimental run; bind the CS1237 source with correct native electrical ownership/timing; verify native Z direction and contact-to-firmware probe propagation; then verify full native calibration/print behavior. No stage beyond the CPU-free fixture has been claimed complete.
