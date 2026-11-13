# Opt-in generic electromechanical fixture

`peripherals/GenericStepperElectromechanical.cs` is a separate assumed physical testbench. It does not replace or edit the stationary RL model. It never reads firmware RAM, target queues, control states or faults. It never writes status, encoder position, DIAG outputs or homing state. Its only firmware-facing analog outputs are the six established injected current ADC channels.

Load `scripts/generic-electromechanical.resc` **instead of** any stationary/current plant. Two plants must not write the same ADC channels or trigger chain simultaneously.

## Physics and assumptions

Each independent two-phase PM rotor has state iA, iB, mechanical angleθ and speedω. Electrical angle is pθ. Flux linkages are λA=ψcos(pθ), λB=ψsin(pθ). The implemented equations are:

```
eA = -p ψ ω sin(pθ)              eB = p ψ ω cos(pθ)
L diA/dt = VA - R iA - eA       L diB/dt = VB - R iB - eB
τ = p ψ (-iA sin(pθ) + iB cos(pθ))
dθ/dt = ω
J dω/dt = τ - Bω - loadTorque + contactTorque
```

Thus electromagnetic mechanical power τω equals electrical back-EMF power eA·iA+eB·iB. Rotor position is integrated from torque, never from requested step counts. Positive constant load torque opposes positive motion; it is an externally specified torque, not Coulomb friction. Viscous damping is separate.

Defaults are illustrative:24V supply,2Ω,3mH,10⁻⁵kg·m² inertia,0.002Wb flux linkage,50 pole pairs,0.0001N·m·s/rad damping,zero external load,500ADC counts/A and offset2048. These are **not identified hardware values**. Fifty pole pairs is a generic two-phase hybrid-stepper interpretation consistent with200 full steps/revolution, not proof of this motor's magnetic geometry.

The published relative mechanical projection uses the recovered software rotation distances39mm/revolution for X/Y and8mm/revolution for Z. It has no homed origin or verified physical calibration. No initial carriage location, gravity, belt compliance, lead-screw efficiency, winding heating, saturation, detent torque or static/Coulomb friction is modeled by default.

Optional `ConfigureRelativeContact(axis, min_mm, max_mm, stiffness, damping)` adds unilateral compliant stops relative to the model's initial angle. Stiffness is N·m/rad and contact damping N·m·s/rad, despite the positional bounds being supplied in millimeters. Contact force comes from penetration and inward velocity. It never directly writes a sensor or DIAG bit. Initial angle/current/speed are zero. Explicit test-kernel initial conditions are scenario setup, not firmware writes.

`SetRotorLocked` supplies an ideal external mechanical constraint. It accounts for removed kinetic energy and exposes reaction torque in the kernel. `SetOpenWinding` idealizes a disconnected winding with an unmodeled clamp absorbing its magnetic energy; that removed energy is recorded. It is not an arc/circuit transient model. The disabled voltage model retains an assumed zero-voltage resistive recirculation path, not a verified high-impedance bridge circuit.

## Timing and feedback

The wrapper mirrors the established actual-timer wiring: TMR2→TMR1/3/4 IS1, TMR1→TMR8 IS0, then actual TMR8 trigger advances/publishes all current channels before ADC preempt trigger15. Timer `ConfigurationChanging` first integrates the **old** cached voltage to the current virtual time; `ConfigurationChanged` then caches new drive. This preserves brief polarity/mode changes instead of applying the final register state over the entire ADC interval.

PWM interpretation, enable/MOE gates and first-leg current-sense polarity follow the existing explicit generic bridge assumptions. Forced-inactive mode is evaluated before output-polarity inversion; it is not indiscriminately replaced by zero voltage. No extra free-running clock or host-time input is used.

Unlocked dynamics use RK4 substeps bounded by20µs, electrical L/R timescale, electrical angular speed and optional contact stiffness. A locked rotor uses the exact RL exponential. MCU Reset preserves physical state; it does not zero kinetic/current energy or teleport position. Numeric divergence raises an explicit error rather than clamping a fault away.

## Observation and tests

Read-only monitor getters: `GetAngleRadians axis`, `GetVelocityRadiansPerSecond axis`, `GetCurrent axis phase`, `GetTorqueNewtonMeters axis`, `GetStoredEnergyJoules axis`, and `GetRelativeTravelMillimeters axis`. `CaptureTrace` records these actual model states; `WriteCsv path` exports bounded virtual-time samples. Automatic trace interval is1000 ADC triggers by default, capacity100000 samples; reaching capacity is explicit. Traces are labeled assumed physical-model state, not commanded or calibrated printer position.

- `tests/run-electromechanical-equations.sh`:24 actual C# assertions for passive energy, reciprocal torque/EMF power, constant torque acceleration, RL decay, locked/free response, compliant contacts, ideal-open energy accounting and invalid/finite inputs.
- `tests/run-electromechanical-timing.sh`: actual Renode GPIO/timer/ADC integration checks, including a1µs forced-inactive polarity transient, zero-time mutations,32µs decay, trigger-qualified ADC sample and retained physical state on reset.

These are standalone testbench checks. A later recovered opt-in run on 5 November 2026 combined this dynamic fixture with the active-low external driver model and motor compare-clock correction. Original firmware/native host reached ready with motor status [0,0,0]. This is independent dynamic-startup evidence, not reuse of the stationary RL result. A native G28 X file then hit preserved main scheduled-deadline shutdown3 before homing-arm or movement-queue traffic. Motion, homing and printing remain unvalidated; QEMU/shared-MCU timing is still a separate blocker.
