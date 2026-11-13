# Explicit idealized functional CS1237 profile

This separately named opt-in profile is authorized only for the virtual printer fixture. **It makes no hardware timing/electrical-fidelity claim.** Production/default profiles,100-MIPS execution, original firmware, strict protocol source, native filters, sensitivity, phase logic and safety guards are unchanged. No force provider or PA7→PB2 wiring is included.

Select `NozzleExperimental.Cs1237FunctionalAdapter` with `idealizedElectricalSemantics: true`, using the unchanged experimental `Cs1237NativeGpio` port. See `functional-profile.repl`. Omission/false is rejected. The default strict adapter remains separately available and its100-MIPS timing/ownership failures remain valid.

Functional changes are explicit:
- SCLK high/low shorter than455ns and wake-low shorter than10µs are counted with observed minima rather than rejected solely for physical timing. They do not advance conversion readiness or repair malformed framing.
- Host-priority arbitration retains separate both-high/both-low/opposing/unknown overlap counters. This is a virtual convention, not a verified physical output circuit.
- Actual24-bit wire shifting,27/46-clock structure, command/config fields, continuous conversion periods, elapsed settling/readiness, power-down/wake schedule, sample-provider requirement, signed range, invalid-command/partial-frame checks and invalid-read rejection remain in place.
- Explicit500ns propagation and the existing unknown-transition window remain. No delay is inserted into CPU/GPIO to force compatibility, and production MIPS is not lowered.

Every status export identifies `explicit-functional-CS1237-no-physical-timing-fidelity`, `physical_timing_fidelity:false`, timing violation counts/minima, classified ownership overlaps and semantic/model errors separately. CSV rows retain cumulative timing violations. Zero semantic errors must not be presented as physical conformance.

The timed provider is called with the actual candidate ADC deadline in nozzle nanoseconds, including catch-up deadlines. It must be pure and time-correct. `BindTimedSource(Func<long,int>)` deliberately replaces only the original explicit constructor baseline once; null, duplicate, previously modified laboratory source and later Source/TimedSource reassignment are rejected. `TimedProviderBound` exposes ownership. Bind while emulation is paused, before source use. Binding changes no conversion clock, firmware state or threshold. A candidate may be canceled by a tied power-down/fault boundary, so provider calls must not advance mechanics. A future cross-machine binder must reject missing/future/stale history rather than sample present state retrospectively.

CPU-free validation currently passes42 functional protocol assertions plus14 exclusive-binding/opt-in and14 provider-failure assertions. Provider failures preserve the first cause in status/CSV and are never implicitly retried; invalid reads remain rejected. Signed rails, zero,−1,±123456, short-pulse accounting, pre-ready rejection, missing source, overlap classes and retained elapsed power-down/wake behavior are covered. Final-source standalone100-MIPS validation now covers six native conditions. This is still not shared-machine/force integration.

Files under the prior `cs1237-native` and `cs1237-protocol` directories remain frozen. `Cs1237FunctionalStepFixture` and `Cs1237FunctionalFailureCapture` differ from prior test fixtures only in type names. They are isolated laboratory stimuli/passive observations, not physical-force bindings.

Reproduce CPU-free tests: `python nozzle-renode/experimental/cs1237-functional/run_tests.py`.
Bounded standalone native checks: `python nozzle-renode/experimental/cs1237-functional/run_native.py zero_stable zero_superplus zero_superminus zero_subplus zero_subminus source_removed`.

Restore source checkpoint at snapshot root. It contains this experimental directory and functional evidence only; dependencies are unchanged `cs1237-native/Cs1237NativeGpio.cs`, captured UART replay helper and existing production base platform. No shared/native launcher or live state is modified.

## Final standalone100-MIPS results

Final sources pass42 protocol+14 exclusive-binding+14 provider-failure checks, plus six separate original-nozzle native conditions:

- Stable baseline0: native raw/average0, no PA7 trigger.
- Raw steps+2400 and−2400: filtered peak magnitude1154, no trigger.
- Raw steps+10000 and−10000: original PA7 rises on changed sample6, filtered±1275, CRC-valid native phase4 response. First changed conversion650.750230ms, observed edge654.688ms, latency3.937770ms in this explicitly virtual timing fixture.
- Missing laboratory source: existing conversion deadline faults, no invented sample/PA7 trigger, subsequent invalid read stops the isolated process. This is a model-input negative, not a physical unplug model.

Each completed positive0.8s test records Config0x3c/write1,382 conversions,381 protocol reads including the constructor word,380 actual native samples, zero semantic/adapter errors and no dropped rows. **It also records10306 short-high phases and691 short-low phases**, minima330ns/420ns, independently reproduced from actual GPIO edges.763 ownership observations classify as381 both-high,1 both-low,1 host-high/device-low and380 host-low/device-high. These are transparent idealization violations, not hardware successes.

The strict protocol and native adapter source hashes still match the earlier1421/20-check checkpoint. Strict100-MIPS failures were not rewritten or replaced. Independent final review found no remaining material findings in this isolated scope. Exclusive timed binding is CPU-free tested but no mechanical provider is bound in these native tests.

Evidence: `evidence/cs1237-functional/analysis.json`, per-case raw traces/SRAM/UART/metadata in `native/`, and unit-test logs/manifests. Verify with `python evidence/cs1237-functional/analyze.py`. The validator checks current source hashes, native filter outcomes/UART responses, output freshness, strict-source hashes and physical violation counts independently. Future harness runs remove prior exports before execution so interrupted tests cannot reuse old success files.

Historical source checkpoints r1/r2/r3 preserve review progress. Use the final validated checkpoint for integration planning. New source selection must remain explicit in generated profiles, and namespace rewriting must be compile-tested without altering production defaults. Dynamic force history, inter-machine clocks and PA7→PB2 wiring remain separate integration tasks.

## Shared-profile scheduling correction (later revision)

The earlier six standalone native conditions above belong to the preserved validated checkpoint. A later shared-three-MCU constructor replay exposed an intermittent `Non-future sensor deadline` during bit output, separate from the cross-machine binder's scheduler-boundary clock mistake. The current adapter therefore contains a bounded event-preserving scheduler. The original strict protocol/adapter and native GPIO wrapper remain unchanged; this is a revision only to the explicit functional adapter. The earlier native threshold artifacts are historical evidence, not a hash match for this later revision.

Timer setters/getters may dispatch a real timer callback synchronously while the adapter is already updating. Rather than dropping due work or moving its deadline, the scheduler disables the timer, reads the authoritative peripheral ClockSource, and drains already-due protocol events through the existing exact-deadline Advance path. It then arms only the remaining interval to the unchanged next event. If timer programming advances clock accounting, it rechecks/rearms. It fails explicitly on clock rollback, protocol time ahead of the clock, nonadvancing events, or128 unsuccessful attempts. Source/provider faults remain fail-stop. No MIPS, firmware, protocol threshold, physical delay, conversion period, history-age bound or producer-lead bound changes.

A CPU-free test deliberately defers a real302ms callback under the existing updating guard. The former scheduler fails100ns later without a conversion; the revised scheduler delivers exactly one candidate at302ms and preserves the next402ms conversion. A second test drains a genuine bit invalidation/validity pair at their original228ns/500ns deadlines, with no clock advancement. Eleven policy assertions cover timer-mutation clock progress, ordered multiple events, genuine source error, rollback, nonadvancing events and bounded nonconvergence. Status exports separately count suppressed callbacks, drain passes, rearm attempts and nonconvergence errors; suppression alone is not proof of harmless behavior.

Reproduction and raw before/after evidence: `printer-shared-mcu/experimental/z-force-cs1237-binding/clock-diagnostics/` and `evidence/z-binding-clock-diagnostics/`. Bounded constructor repeats and normal host readiness remain separate gates; no new complete-Z/print or hardware timing claim is made.
