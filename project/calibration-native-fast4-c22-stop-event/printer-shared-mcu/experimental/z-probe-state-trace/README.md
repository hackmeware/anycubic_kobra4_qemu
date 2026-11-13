# Optional original-nozzle PA7 edge-state observer

**Prepared only, not integrated or run with native CPUs.** This is a passive, optional observer for a later explicitly selected virtual Z/calibration run. It does not supply a sensor sample, produce a probe signal, alter calibration logic, or promise physical hardware fidelity.

All new files are confined to this directory and its `evidence/`. No source, fixture, launcher, strict protocol, functional adapter, central integration, heater controller, original firmware file or model default outside this directory was changed.

## What it can add

`PassiveZProbeStateTrace.cs` adds a normal additive `GPIO.Connect` sink to the real resolved nozzle PA7. It streams one initial-level row, then only genuine level changes. No per-bit capture buffer is involved. Default capacity is 4096 rows, bounded to at most 100000. Each successful row is flushed immediately to a new CSV file. JSON status exposes cap losses, stream losses/errors, rejected layouts, snapshot errors, reset observations and uncertain writes. No prior rows are retained in an unbounded in-memory list.

At each uncapped edge it verifies the loaded original image hash, validates the OID9 table entry and native PA7/PA6/PA5 descriptors, and reads raw, average, sensitivity, filtered difference, baseline, stored trigger difference, native state bytes, slow/fast filter globals and counters. It also reads existing CS1237 protocol counters, last latched signed code, next event/conversion deadlines, and cached adapter scheduling diagnostics. Original GPIO mode/latch/pads and source synchronization count are included.

This can capture native trigger-time raw/filter state without tracing every SCLK bit. It does **not** reconstruct missing contact-time ADC commits or CPU-read words in an old run, and the last sensor latch is not automatically the sample that caused the trigger. It must remain alongside the existing contact, force-query, PA7/PB2 and native completion evidence.

## Critical original instruction order

Original image: `inputs/nozzle.bin`, 37469 bytes, SHA256:

`ae09264667ff4a72905706026b1591bdede91e1f250755319fec531328e54e2f`

Load base is 0x08004000. Original constructor 0x0800a390, stored Thumb pointer 0x0800a391, allocates a 0x40-byte object. The dynamic table is at the pointer in 0x20000074, with byte count at 0x20000070 and 8-byte entries. OID9 must have that constructor. The original run's final OID9 object is 0x200006f0; the observer resolves it dynamically and does not hard-code that object address. It bounds and aligns the full table/object within the actual 20 KiB SRAM. Native global descriptors must be PA7 output (GPIOA/mask0x80), PA6 DOUT (GPIOA/mask0x40) and PA5 SCLK (GPIOA/mask0x20).

The filter-trigger path commits these fields **before** raising PA7:

- Average +0x1c at 0x08009b42, raw +0x18 at 0x08009b46.
- Slow global 0x200003d8 at 0x08009c30 and fast global 0x200001e8 at 0x08009c40.
- Filtered difference +0x3c at 0x08009c50, before the signed threshold comparisons and settling/latch/arming gates.
- Baseline +0x28 comes from the earlier arm/reset command. Sensitivity +0x10 is the current native setting, not an observer setting.

The high path calls the GPIO helper at 0x08009fa0. The actual atomic-set/reset register store is at 0x080098cc. A synchronous PA7 sink therefore runs during that store, **before** the call returns. Only after it returns does the firmware store latch=1 (0x08009faa), clear arm +0x25 (0x08009fb4), and write `baseline - raw` into trigger difference +0x20 (0x08009fba).

**Consequently, rising-edge `stored_trigger_difference_signed` is the previous stored value. It is not the new trigger result.** Latch and arm bytes are also pre-cleanup. Raw, average, slow/fast, sensitivity and filtered difference are already committed for the filter-trigger path. The observer does not substitute a calculated value for an original field. An offline analysis can separately label a calculated baseline-minus-raw prediction, never a captured write.

A falling edge gives exact committed state at that later output transition, not a delayed equivalent of the rising snapshot. Native reset/release paths and source resets can lower PA7. Those fields may already have changed. No execution hook, deferred CPU callback, timer or follow-up sample is invented to capture the subsequent +0x20 write. A row alone is not proof that an edge was a successful probe, that the nozzle released, or that the host accepted calibration.

`verify_original_layout.py` byte-checks all 608 instruction rows in the prior original disassembly and the additional GPIO helper instructions, confirms the original image and saved final SRAM hashes, and validates the actual archived OID9/descriptors. It writes `evidence/original-layout-verification.json` and `verified-original-instruction-order.asm`. The archived SRAM remains final-only evidence.

## Timestamp and snapshot semantics

All three time fields are nozzle-source-local virtual nanoseconds. They are deliberately not merged:

- `published_machine_ns`: `machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds`, comparable to the existing source-edge trace's published machine epoch. A published boundary may lead the current peripheral clock.
- `peripheral_clock_ns`: existing `machine.ClockSource.CurrentValue.TotalNanoseconds` as observed in the callback, without forcing synchronization.
- `protocol_now_ns`: the existing protocol's last processed timestamp. It need not equal either machine timestamp.

The observer **does not read `Cs1237NativeGpio.Nanoseconds`** because its `LimitTimer.Value` getter may flush clock accounting and dispatch pending model work. It adds no timer, does not call SyncTime, and never reads a motor/force getter or advances physics. The existing protocol/adapter properties used here do not execute model transitions. Schedule-entry/after-setter/suppressed-tick fields are retained diagnostics from earlier adapter work, not clock samples taken simultaneously with this edge.

The GPIO fanout callback happens inside the GPIO base write, before `Cs1237NativeGpio.WriteDoubleWord` performs its subsequent `Access` notification and trace recording. Protocol state is thus state committed at callback entry, not state after that outer access returns. The callback runs synchronously with the source store, but no claim is made about exact CPU instruction time: CPU time is not synchronized. `has_current_cpu` and `pc` report available bus execution context, not an instruction hook. In CPU-free tests no CPU context exists.

A valid edge row is a same-machine synchronous set of read-only memory/property reads. It is not an atomic snapshot across nozzle/main/motor machines or the host. No guest/shared offset is guessed. The existing source→PB2 connector queue remains independent.

## Initialization, reset, errors and evidence accounting

- Construct and start while paused, before the future run, **after** the existing connector has selected its source exactly once. The observer uses additive Connect only and never calls Disconnect or SelectSourcePin. It seeds the actual level before attachment; neither initial high nor low is called an edge.
- `Start` verifies the exact disk image and the loaded mapped flash bytes. Each uncapped capture rechecks mapped image bytes before decoding SRAM. Missing/wrong firmware at startup rejects Start without an interpreted trace. Changed live firmware or wrong/missing OID/layout emits an invalid-layout row with native fields blank. An absent OID in the initial pre-constructor row is expected and distinguishable from an invalid edge. Protocol fields remain literal observations.
- The named `sram` and `flash` arguments must reference the actual original nozzle memories. The overlay does so; there is no alternate memory or synthetic state in production observer code.
- Real source GPIO reset can produce a real low edge and it is retained. Observer Reset only increments its own counter. The edge has no invented reset/physical-release classification. Full machine or destination reset still requires stopping/rebuilding the fixture under the existing cable lifecycle rules. Do not continue calibration merely because the observer survived.
- Callback failures are caught so they cannot abort subsequent independent source sinks. Snapshot failures lose the row and count it. Write failure closes the observer stream, counts a loss and marks its result uncertain because a partial write may exist. No retry appends a possible duplicate. Future missing rows are counted, not fabricated.
- The attempt cap is shared by initialization and edges. Once reached, it avoids further SRAM/hash work. `rows_attempted = rows_written + cap_drops + stream_drops`; snapshot errors are included in stream_drops. Layout rejection produces a row, not a hidden loss. Inactive edges are separately counted. The firmware-verified flag describes the latest actual check, not a new check after cap/stop.
- `Stop` closes the file but leaves a harmless inactive sink, preserving other fanout. A fresh fixture/observer is required for another capture. It never overwrites an existing CSV. Export JSON status at the ordinary paused final boundary using a separate path. Counters are live properties but **the JSON export is explicit**, not an autonomous periodic writer. If the process dies before status export, the flushed CSV survives but final loss counters may be unavailable.

## Optional integration, not enabled here

The deliverable `observer.repl` names the existing nozzle `gpioA`, `sensor`, `sram`, and `flash`. `attach.commands.in` is a deliberately unexpanded integration template. A future integrator can include the observer after the already-selected unchanged sensor sources and normal connector wiring, load this overlay in machine `nozzle`, and call Start with the verified original image and a fresh run-output CSV. No source rewrite of this observer is needed for shared namespaces. Stop then WriteStatus at the existing final paused boundary; restore the selected machine explicitly.

Do not include the test class in a native run. Do not run the template with placeholders. Nothing in a default launcher or current runtime selects this observer. It supplies no new force source, PA7/PB2 connection, timeout, reset command, threshold, timer or heater behavior.

## Verification and limits

Run from the snapshot root:

```
python3 printer-shared-mcu/experimental/z-probe-state-trace/verify_original_layout.py
python3 printer-shared-mcu/experimental/z-probe-state-trace/run_tests.py
python3 printer-shared-mcu/experimental/z-probe-state-trace/run_tests.py --shared-namespaces
```

Both namespace variants pass 41 CPU-free assertions plus CSV column-count/JSON parsing checks, using the actual unchanged AT32GPIO, Cs1237NativeGpio, Cs1237FunctionalProtocol and Cs1237FunctionalAdapter. Two real model instances receive identical test GPIO stimuli, one observed and one control. Their protocol properties, counters, adapter diagnostics and GPIO state match after initialization, reset, caps, errors and the existing conversion deadline at 0.300 s. They remain identical after 0.303 s and a subsequent edge. All synchronization counts are zero. No motor plant is instantiated.

Tests cover initial high/low, exact genuine rise/fall, repeated same-level writes, independent source fanout, source reset, observer reset, stopped capture, bounds, disk and loaded-image rejection, changed live flash, missing/wrong/out-of-range/unaligned OID data, wrong native pin descriptors, cap accounting, stream-open and mid-write failures, and non-overwrite rules. The test-only reflection closes only the observer's own output stream to inject a failure. Test SRAM/register writes are clearly isolated stimuli with no CPU present, not native or calibration evidence. Logs and synthetic CSV files are under `evidence/{standalone,shared}/captures/`; failed development compile output is retained separately from successful summaries.

**No original native replay was performed.** CPU-free invariance is not native timing validation. The next authorized run must verify source/dependency hashes, zero lost/error edge rows, valid layout on relevant edges, unchanged original firmware/guards and intact independent PA7→PB2 fanout. Even then, this observer closes the trigger-filter snapshot gap only; it cannot alone prove the complete per-conversion/per-bit causal chain, calibration completion, printing, real sensor electrical timing or physical calibration.
