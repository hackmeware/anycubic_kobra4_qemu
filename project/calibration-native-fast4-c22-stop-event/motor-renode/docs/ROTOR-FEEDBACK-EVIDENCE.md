# Rotor feedback boundary: static firmware evidence

This is a bounded static analysis of original motor v1.6.01. It does not assert the absence of every possible unused encoder path. No firmware state, commands, faults or peripherals were changed during this investigation.

## Commanded electrical angle is not measured rotor angle

The current-control record is `0x20004180 + motor*0x6c`. Its16-bit electrical angle is at+0x0c, speed-like quantity at+0x10, phase-current pair at+0x2a, transformed current pair at+0x32 and control-effort pair at+0x42.

- Current-loop routine0x08009738 calls angle dispatcher0x08014b14.
- The dispatcher selects using byte `0x2000000a + motor`. Modes0–5 include RAM-generated ramps, fixed/test angles, serial-trajectory interpolation and another software-generated trajectory.
- Specifically mode4 takes0x08014bf0→0x08018574→0x08012220. The latter reads trajectory record `0x200078f0 + motor*0x46dc`, interpolates its position/velocity/acceleration using a timer counter read through0x0801a880, and returns the planned position. The downstream function scales it into electrical angle.
- This is a command-derived commutation reference. It is not evidence that the physical rotor follows that reference. A physical model must **never copy it into its rotor position**.
- The runtime selection bytes should be independently sampled in a native session before claiming which dispatcher branch is currently active. Static reachability alone is insufficient.

Instruction evidence: `firmware-evidence/command-angle-path.asm`.

## Concrete electrical-residual detection

The measured input path is already established: injected ADC pairs→offset/gain/channel correction0x0800a43c→sine/cosine0x080136f4→rotating-frame current transform0x08018b18. The supplied angle is the controller reference described above.

At0x08009824–52, the current loop passes routine0x08019aac:

- a parameter record at `0x20007504 + motor*0x24`;
- the transformed measured-current pair from control record+0x32;
- the stored control-effort pair from+0x42;
- speed from+0x10;
- the controller angle and detector state at `0x20003a2c + motor*0x54`.

The arithmetic is consistent with a rotating-frame resistive/inductive/back-EMF residual. In deliberately neutral integer notation, with two signed current components c0/c1, two effort components u0/u1, parameter words A/B and normalized speed s, the two pre-absolute residuals have the structure:

```
e0 = u1 - trunc(A*c0 / 32768) + trunc(trunc(B*c1 / 32768)*s / 16384)
e1 = u0 - trunc(A*c1 / 32768) - trunc(trunc(B*c0 / 32768)*s / 16384)
```

The actual implementation applies signed16-bit truncation and absolute-value helpers, then several fixed-point low-pass/difference filters and speed-dependent qualification. At0x08019d86–88, a qualified event sets detector state+0x50. The exact parameter SI scaling and every detection threshold have **not** been reconstructed. These expressions must not be treated as calibrated physical voltage/inductance values.

This is evidence for **sensorless electrical load/stall detection**, not proof of an absolute rotor-angle observer. No external SPI encoder, quadrature encoder counter or analog-angle channel feeding the inspected commutation path was identified. That is a scoped finding, not a whole-firmware impossibility claim.

## Digital detection outputs and alternate external input path

Routine0x08018d70 consumes detection state and writes genuine GPIO outputs through the standard set helper0x08017b5c:

| Motor index | Output |
|---|---|
|0|PB5|
|1|PB4|
|2|PB15|

Both calls0x08018e54 and0x08018e8e set the selected bit. Configuration/control path0x08018478 clears through0x08017b58. These are suitable **observation endpoints** for firmware-generated diagnostic behavior. Their physical connector mapping to the main board has not been established by this code alone.

An alternate gated path0x08013da0 reads GPIO IDT through0x08017df8: motor0 PB4, motor1 PB5, motor2 PD2. It debounces comparison with configured polarity and sets a state flag. These are digital external-condition inputs, not measured rotor angles. Their sharing/cross-coupling with the output pins requires actual board/wiring evidence; do not silently connect them to geometric stops.

Instruction evidence: `firmware-evidence/sensorless-residual-and-gpio.asm`.

## Defensible generic dynamic model

A separate physical rotor model can be driven only by actual gated PWM voltages and virtual elapsed time, returning only current-derived ADC samples through the already established channels. Its independent rotor motion changes back-EMF and therefore the currents seen by the firmware's original detector. This provides a causal physical feedback route without inventing an encoder, writing DIAG levels or mirroring commanded position.

Use explicitly assumed two-phase PM flux linkage, pole count, inertia, winding R/L, damping, load and optional compliant contacts. Generic validation can establish energy reciprocity and causal current changes. It cannot establish actual printer calibration, accurate StallGuard thresholds or successful native homing until those behaviors are observed under the unchanged firmware.
