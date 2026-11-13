# Experimental causal Z-force → CS1237 binding

This opt-in bridge connects the **synthetic** Z fixture's actual mechanical reaction to the separately opt-in **idealized functional** CS1237 model. It is not physical sensor calibration, electrical timing fidelity, successful native Z homing, full calibration, or a completed print. Production sources and default profiles remain unchanged. No production core patch has been applied here.

## Architecture and ownership

1. `MotorZForceSource` attaches after the electromechanical plant to the **existing TMR8 ADC trigger**, using its established multi-receiver GPIO event fan-out. It adds no timer or physical integration and reads no firmware memory.
2. Each real trigger captures immutable `ZForceSnapshot` data: physical-state timestamp, capture timestamp, underlying torque, derived force, signed ADC code, saturation, and fixture-enabled state. Physical and capture timestamps stay separate. The capture checks that the plant has already integrated at the trigger, allowing at most one nanosecond of integer-conversion discrepancy and never a future state.
3. `ZForceHistory` stores a bounded history. The nozzle's timed provider selects the newest actual physical state **at or before** each requested conversion-candidate deadline. It never extrapolates, moves a rotor, reads current/future state as historical data, or writes GPIO/firmware.
4. `Cs1237ZForceBinding` installs the provider through the functional adapter's exclusive `BindTimedSource` API. Registry names are scoped by the actual Renode emulation object, and runtime calls use a typed direct reference. Missing/duplicate registration, multiple consumers, same-machine misuse, modified/existing ADC providers, and late binding fail explicitly.
5. Both machines, the GPIO timestamp clock and ADC protocol must be at the common zero epoch before binding, before any `RunFor`. Runtime verifies the GPIO clock exactly against its owning nozzle `machine.ClockSource.CurrentValue`, not the scheduler-published `Machine.ElapsedVirtualTime`, and rejects future candidate deadlines, peripheral/producer-clock rollback, callback-deadline rollback, and excessive producer lead.

The provider is observational. Its history/query counters and optional trace record **conversion candidates**, not a guarantee that the ADC subsequently committed the conversion. A tied power-down/fault event can cancel a sampled candidate. Repeated identical candidate deadlines return the same selected snapshot while it remains within the allowed temporal window. No reset/rebinding or physical mutation is hidden in the callback.

The model uses the fixture's explicit gain/baseline/polarity. The chosen positive gain is a synthetic orientation, not a recovered physical strain-gauge polarity. The original nozzle's observed symmetric filter threshold does not establish that calibration.

## Freshness, skew and safe retirement

Freshness and history retention are distinct parameters:

- `maximumStateAgeNanoseconds`: deadline minus selected **physical-state** time. It must be supplied explicitly and justified against observed motor ADC cadence.
- `maximumProducerLeadNanoseconds`: permitted motor producer clock/capture lead over a nozzle conversion deadline. This permits bounded scheduler catch-up, not borrowing future physical data.
- `capacity`: maximum simultaneously retained immutable samples. Exhausting it while samples are still eligible **faults**, rather than silently dropping them.

Let newest capture time be `P`, permitted producer lead `L`, and maximum physical-state age `A`. An allowed future query has deadline `D >= P-L` and can only use states `S >= D-A >= P-L-A`. Therefore a sample strictly older than `P-L-A` can safely retire. This works before the first ADC conversion as well as during long operation. It avoids an inevitable buffer overflow after an initial fraction of a second. Samples exactly on the eligibility boundary remain retained. Requests outside that window fail for explicit skew/staleness; the bridge never silently expands either bound.

In the CPU-free integrated fixture the actual measured trigger interval is **33,000 ns**, the age limit is explicitly **100,000 ns**, producer lead **1,000 ns**, and capacity **16**. The existing native model's approximately 33.333 µs cadence motivates testing several cadences of freshness, but these unit-test bounds are **not validation of every native startup/motion phase**. A shared 1 µs quantum or an independent Linux/MCU 1 ms coupling interval alone does not prove freshness. Record actual capture intervals and ages in any later combined run; a bound failure needs investigation, not automatic widening.

A missing update stream eventually becomes stale and fails the ADC provider closed. MCU reset preserves physical history/fixture state; it is not treated as a new common epoch. Backward time is an error. Static source-registration state is not a saved-state restoration contract: construct/register/bind fresh emulations rather than assuming arbitrary restored snapshots retain a valid provider relationship.

## Verification completed

`run_tests.py` creates a temporary copy with the separately proposed `disable-contact.patch` extension. It never modifies the production core. The checks use two real Renode machines, **no CPUs or firmware images**, real AT32 timer events, integrated motor contact, and actual CS1237 conversion deadlines.

```sh
python3 printer-shared-mcu/experimental/z-force-cs1237-binding/run_tests.py
python3 printer-shared-mcu/experimental/z-force-cs1237-binding/run_tests.py --shared-namespaces
```

The second command compiles motor types as `PrinterMotor` and nozzle GPIO types as `PrinterNozzle`, matching shared-model namespace isolation. Exact input and compiled hashes are recorded separately.

Coverage:

- 144 history assertions: exact/past/future selection, age boundary, missing data, producer skew, physical and consumer timestamp rollback, callback ordering, duplicates, invalid setup, still-eligible overflow, 100,000 captures with safe retirement before/between sparse consumers, bounded tracing, and trace-on/off selection invariance.
- Actual cross-machine binding and first conversion, including missing/duplicate provider and future callback rejection.
- Bitwise trace-on/off physical invariance for angle, velocity, both currents, energy, integration calls and real ADC trigger count. Repeated sample reads add no integration.
- Genuine fixture disable produces the baseline at the next real conversion, without probe GPIO writes.
- Cross-machine callback skew and rollback rejection; their original causes reach ADC fail-stop at its next real deadline.
- Stopping the motor ADC trigger stream makes the later ADC conversion fail closed. No third conversion is fabricated.

Observed first conversion: candidate **302,000,000 ns**, physical state and capture **301,983,000 ns**, age **17,000 ns**, contact torque **0.0016637483136022365 N m**, force **1.3067048698587982 N**, code **13067**. After true contact disable, the **402,000,000 ns** conversion used zero force/code. The test uses a tiny laboratory bed at relative −0.01 mm and an explicit 0.002 N m external mechanical load, not original firmware motion or the default 10 mm-clearance scenario.

Evidence: `evidence/z-force-cs1237-binding/`, including normal/shared namespace logs, source-hash manifests, and bounded candidate traces. Source snapshots are taken before compilation; the manifest says whether the source files remained unchanged during the test. Adapter/protocol dependencies match the sensor owner's validated functional checkpoint, not a strict electrical fidelity claim.

## Preparing an explicitly selected shared profile

Prerequisites remain separate and must be reviewed before a native coupling attempt:

- Approve the Z fixture's two-method disable extension and use an explicitly isolated extended core or approved patch. Do not silently edit the production/default core.
- Load/configure `VirtualZBedContactFixture` for `PrinterMotor` before constructing the source. It owns Z contact geometry exclusively.
- Load the **functional** CS1237 sensor on the correct explicit native-GPIO wrapper in the nozzle machine. This bridge does not replace GPIO, choose the digital profile, or rewire PA7/main PB2.
- The sensor must still own its original explicit constructor baseline, not a step fixture or another laboratory/timed provider.
- Declare and retain age/skew bounds with the run's evidence. The following values are the tested laboratory values, not blanket validation of native startup.

Prepare sources and a **motor setup tail**, without loading anything:

```sh
python3 printer-shared-mcu/experimental/z-force-cs1237-binding/prepare_shared_sources.py \
  --output /tmp/z-force-shared \
  --maximum-state-age-ns 100000 --maximum-producer-lead-ns 1000 \
  --capacity 4096 --trace-rows 100000 \
  --fixture zBedContactFixture --sensor sensor --gpio gpioA
```

The generated `motor-tail.commands` is appended after physical-fixture setup in the explicit motor setup command file. The existing shared launcher configures nozzle extras **before** motor extras, although both are before `RunFor`. Consequently this tail registers the motor source, switches briefly to nozzle to install the binding, then restores `motor` before the launcher's remaining motor commands. This order matters. The bridge emits no native run command and changes no default profile.

Do not include the bridge classes twice or register/bind twice. Loading missing prerequisites fails visibly. The generated source registry is scoped to the current emulation; it is not a network service or external agent. `sysbus.zForceSource WriteTrace /absolute/output.csv` exports the optional bounded candidate trace. Trace exhaustion reports dropped rows without changing physical behavior; functional history is retained independently under the eligibility rule above.

Remaining unverified: combined native startup under these explicit freshness/skew limits, original firmware-driven Z contact through this force source, correct physical downward sign, full PA7→main PB2 wiring/behavior, native complete calibration and printing. Do not call those complete from these isolated tests.

## Exact peripheral clock correction after native readiness

The first shared native readiness run exposed an invalid equality in the initial binder: the GPIO1GHz timer was compared to `Machine.ElapsedVirtualTime`. Installed Renode1.17 dispatches fractional peripheral deadlines while that machine property can already show the end of the scheduler advance. A CPU-free callback at1234ns reads peripheral clock1234ns and published machine time2000ns. This is not an epoch reset and does not justify tolerance.

A bounded original-three-MCU constructor-only replay independently reproduced candidate/port/peripheral clock502086230ns versus published nozzle/motor time502087000ns. Its genuine latest physical capture502072290ns was13.940µs old and producer lead770ns. The old guard rejected the valid fractional callback before history selection. The replay used verbatim readiness-capture bytes[0:494] at explicit200µs gaps starting400ms; it reproduces the clock-domain mechanism, not the original full-host timing. No phase-arm, homing, heater or print command was sent.

The corrected binder uses exact port-to-`ClockSource.CurrentValue` equality and checks the candidate against that same peripheral domain. It independently rejects clock rollback. The original100000ns physical-state age and1000ns source lead contracts are unchanged; no time advances, source seeding, altered firmware or widened bounds are introduced. Published-machine time is retained as diagnostics, never substituted for an ADC deadline.

`WriteStatus` exports last callback deadline, port/peripheral/published-machine/motor clocks, latest physical capture, prior protocol time, mismatch observations and the first clock-guard failure. The central selected profile writes `z-binding-status.json`. Adapter error CSV timestamps can be stale `protocol.Now` from before the rejected callback; never treat them as the candidate deadline.

Tests and evidence are under `clock-diagnostics/` and `evidence/z-binding-clock-diagnostics/`: before/after fractional cross-machine calls, ±1ns clock mismatches, future candidate, negative timestamps, rollback, unchanged original history/staleness/ownership regression tests, and bounded constructor replay. Native full host readiness and full Z are separate gates.
