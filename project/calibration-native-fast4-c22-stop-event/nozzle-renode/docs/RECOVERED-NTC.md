# Opt-in recovered nozzle sensor curve

The optional `scripts/virtual-nozzle-recovered-ntc.resc` uses the original host's
`NTC ZM3863 HNS112HC4570G0` calibration. It replaces the illustrative sensor
fixture only when explicitly included. Existing `virtual-nozzle-ntc.resc` and
all constructor callers without the new option retain their previous beta curve.

Load the nozzle platform first, then include this script **instead of**
`scripts/virtual-nozzle-ntc.resc`, before starting the original firmware. Both
profiles register `virtualNozzleNTC`, so they must not be loaded together.
For a future shared-MCU run, supply the optional script through that runner's
existing nozzle setup input. No launcher default or live run is changed here.

Neither heater nor fan is connected. The configuration identifies PB8 as the
heater and PB9 as `heater_fan extruder_fan`, but a native command-to-PB8 trace is
still required before binding heat. Selecting this sensor does not synthesize
firmware readiness, homing, heater success or extrusion permission.

## Source and conversion

Preserved evidence is in
`evidence/recovered-nozzle-thermal/nozzle-thermal-recovered-evidence.json` at the
snapshot root. It contains the complete 78-point factory table, 78 live native
linear segments, offsets and hashes. The named entry was followed through a
validated 21-entry sensor registry to its live factory object. Resolved
extruder configuration and the active converter independently specify a 4700-ohm
pullup. This is recovered **software calibration**, not independent physical
sensor or PCB measurement.

The peripheral embeds the full table and exact live segment coefficients.
Within -40 through 360 degrees Celsius inclusive it inverts the same native
piecewise-linear resistance-to-temperature conversion: select the first segment
whose upper resistance boundary evaluates at or below the requested temperature,
then calculate `R = (T - intercept) / slope`. The ADC is the nearest integer to
`4095 * R / (4700 + R)`, with midpoint rounding away from zero. This matches the
existing ADC quantization behavior. Exact coefficients preserve the native
implementation's small floating-point differences from ideal table interpolation.
The recovered option rejects a different pullup, ADC maximum or circuit polarity.
Beta and nominal-resistance parameters are used only by the default beta mode.

Selected points are 25 C / 261191 ohms, 200 C / 1104 ohms, and 320 C / 142.2 ohms.
At modeled 25 C the recovered profile publishes ADC4023, which the host interprets
as approximately24.898 C after quantization. The model's physical temperature
remains25 C. The old generic fixture's ADC3911 instead means approximately47.106 C
to this custom native converter, explaining the lack of heater demand at target35 C.

The recovered table is **not** the adjacent ZM3486 sensor's beta4570 registration.
Do not substitute either beta4570 or generic100k/B3950 for the ZM3863 table.

## Unsupported temperatures and unchanged guards

`SensorCurve` identifies the selected curve. `SensorCurveOutOfRange` reports
whether physical temperature is outside the recovered table. Outside its range,
this model deliberately does **not** use the native endpoint extrapolation:
below -40 C it publishes4095; above360 C it publishes0. Both are invalid readings
under the recovered original firmware limits. A warning is emitted when entering
this state. It does not clamp physical temperature to the table, to the host's
allowed range, or to a plausible ADC code. The existing physical maximum/latch
continues independently. An injected open/short overrides the curve reading and
remains visible even when temperature is unsupported.

No temperature guard is changed. The original configured nozzle limits remain
0..320 C, with minimum extrusion temperature60 C. Supported table points above
320 C or below0 C are still reported honestly and can trip the original guards.
Ideal open and short injections still produce4095 and0. MCU reset retains heat,
the injected fault and any maximum-temperature latch. Only explicit `ColdReset`
restores ambient and clears those modeled fault/trip states.

The heater power, thermal mass and cooling parameters remain illustrative.
Successful conversion tests are not proof of native heating, thermal runaway
protection or a successful print.

## Tests

Run `tests/run-recovered-nozzle-curve.sh` from any directory. It creates a small
CPU-free Renode test machine using the actual C# peripheral and optional profile.
It loads no firmware, starts no Linux guest, and uses an isolated temporary HOME.
The source-data checker first compares all embedded points and coefficients to
hash-bound native evidence and independently recalculates477 expected ADC vectors.

The C# checks cover those477 vectors, legacy defaults, actual ADC0 publication,
open/short injection, unchanged physical heating and cooling, heat retention on
reset, the existing maximum/latch, unsupported-temperature diagnostics, a genuinely
unconnected ambient timer, and synthetic GPIO PWM integration. The last test is
explicitly synthetic and does not establish the PB8 binding.

Results are written to `tests/results/recovered-nozzle-curve/` by default.
Set `RESULT_DIR` for an isolated alternate result directory, or `RENODE` to select
another existing runtime.
