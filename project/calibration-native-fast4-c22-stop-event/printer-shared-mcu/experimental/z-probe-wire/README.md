# Optional causal Z-probe wire

This is a **synthetic, noninverting fixture assumption**, not a verified physical nozzle-to-main cable. It connects only the actual resolved nozzle PA7 output to the main PB2 external input. The original nozzle firmware must still obtain CS1237 samples, apply its filters/arming/guards, and drive PA7 itself. Main GPIO configuration and the original OID3/endstop logic remain authoritative. The separately established ordinary trigger request is active-high; this fixture does not add an inverter or reinterpret trigger polarity.

Nothing is enabled by default. No production launcher, fixture, firmware, firmware RAM, homed state, motor plant, force provider, threshold or timing profile is changed. There is no custom peripheral that manufactures a probe signal. Standard Renode GPIOConnector is sufficient for **initialization when the destination is attached first**.

## Generate and enable

From the snapshot root:

```sh
python3 printer-shared-mcu/experimental/z-probe-wire/prepare_wire.py \
  --output /absolute/path/to/run/z-probe-wire \
  --assume-pa7-pb2-noninverting --return-machine motor
```

This creates files only. After the actual main/nozzle GPIO overlays exist, append the generated `connect.commands` once, before the first emulation start/RunFor. Its exact executable commands are:

```text
mach set "main"
emulation CreateGPIOConnector "syntheticZProbe"
connector Connect sysbus.gpioB syntheticZProbe
syntheticZProbe SelectDestinationPin sysbus.gpioB 2
mach set "nozzle"
connector Connect sysbus.gpioA syntheticZProbe
syntheticZProbe SelectSourcePin sysbus.gpioA 7
mach set "motor"
```

There are deliberately no GPIO writes, source priming pulses, RunFor, SyncTime, additional timers, force reads or physical-integration calls. The connector follows source GPIO events through Renode's existing cross-machine queue. Do not add an external PA7 level to make startup work. Parent integration must opt in explicitly and retain the assumption label. The generator's manifest records the command hashes. No `shared_mcu.py` change is included here.

## Verified behavior and strict lifecycle limits

CPU-free two-machine tests use real AT32GPIO ports and the explicit Cs1237NativeGpio source wrapper, both standalone and rewritten PrinterMain/PrinterNozzle namespaces:

- Pre-existing source high reaches PB2 with destination-first attachment. Independently pre-existing low overrides a target pullup. A new PA7→PB2 attachment also restores the actual low following target reset.
- Both actual rising and falling source levels propagate without inversion. Same-level writes do not create a destination edge. An external low applied against a push-pull source high does not leak through: the resolved source remains authoritative.
- PA6 changes do not affect PB2; independent PB3 and untouched PB4 remain isolated. Existing passive source observers survive initial hookup, source reset, destination-only detach and fresh-connector reattachment.
- Source GPIO reset's actual low propagates. **Destination GPIO reset clears AT32GPIO's external-drive state.** An unchanged source is not automatically resent. A target pullup can then read high despite a still-low source. This is a known model limitation, not a valid probe event. Stop/rebuild the fixture after destination or full machine reset; do not silently continue a calibration. Tests demonstrate a fresh destination-first connector restoring the actual low at a paused boundary, but no automatic reset recovery is installed.
- At a paused, queue-drained boundary, destination-only `DetachFrom sysbus.gpioB` stops future forwarding but leaves the previous external drive latched. `sysbus.gpioB ReleasePin 2` explicitly models unplug by releasing that external driver. The configured target pull then determines the level. With a pullup it becomes high; no claim is made that unplug means safe/untriggered. The generated `disconnect.commands` implements only this narrowly tested operation.
- No arbitrary-time hot-unplug or pending-event cancellation guarantee is made. A dangling source-side connector subscription is intentionally retained after destination-only detach, avoiding source fanout disruption. Prefer a fresh fixture for reuse.
- Negative regression: source-first attachment loses a pre-existing high. **Repeating SelectSourcePin on an existing connector disconnects other source observers.** It is not a resynchronization API and must not be used to recover reset state. The initial code path calls it exactly once on a new connector.
- Cs1237NativeGpio.Synchronizations remains zero in these CPU-free tests. No plant is instantiated or integrated. This verifies no added synchronization/integration mechanism; it is not a native CPU timing claim.

The first target attachment can have a connector-default transient before queued source initialization. All setup is before native execution; only the settled value after normal queue processing is asserted. Exact edge delivery timing, analog drive strength, source high-impedance propagation, electrical contention, cable identity, unplug debounce and physical delays are not modeled or validated here. Ordinary standard-connector quantum/queue semantics remain unchanged.

## Reproduce

```sh
python3 printer-shared-mcu/experimental/z-probe-wire/run_tests.py
python3 printer-shared-mcu/experimental/z-probe-wire/run_tests.py --negative-reselect
python3 printer-shared-mcu/experimental/z-probe-wire/run_tests.py --shared-namespaces --negative-reselect
```

The ordinary run has 28 assertions. Negative mode adds four intentional limitation assertions, for 32 total. They are **passing tests of known bad usage**, not fixes for that usage. Logs, generated executable scripts, compiled source copies and hash summaries are under `evidence/z-probe-wire/`. The emitted connection sequence is imported directly from `prepare_wire.py`, so the tested startup order and deliverable cannot drift independently.

No original-firmware or host replay is run by this suite. It does not demonstrate native Z homing, complete calibration, safe physical probing, a verified PCB mapping or successful printing. The contact→force→CS1237 adapter remains a separate upstream experiment. This wire does not permit any force/position→PB2 shortcut.
