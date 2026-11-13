# Isolated CS1237 protocol-conformance core

This experiment models the documented **digital transaction structure** of a Chipsea CS1237, using explicitly synthetic signed24-bit samples and synthetic monotonic nanoseconds. It is not attached to any GPIO, native firmware, heater, rotor, nozzle, bed or probe endstop. It cannot declare homing success. Production/default sources and profiles remain unchanged.

Run the actual C# tests, without a CPU or firmware:

```
python nozzle-renode/experimental/cs1237-protocol/run_tests.py
```

The existing Renode runtime is used only to compile the two C# files and invoke a test method. No `RunFor`, CPU, firmware image, GPIO peripheral, native request, network call or live run is involved. Logs and source hashes go to `evidence/cs1237-protocol/`.

## Manufacturer evidence

Chipsea CS1237 Rev1.1,2014-10-17,19 pages. The official product page listsV1.1:
https://en.chipsea.com/product/details/?id=1155&pid=77

Manufacturer-authored PDF obtained through the public SnapEDA mirror:
https://s3.amazonaws.com/snapeda/datasheet/CS1237_CHIPSEA.pdf

PDF SHA256 `3c682b95f2d9f96e57fc1f3a8498a9a12df76e4bcb2fcbb83d75c8de64ed61a3`. The official download wrapper returned403; it was not bypassed. The independently available mirror was obtained before that denial. Official-versus-mirror byte identity is unverified.

The PDF, extracted text, inspected page images13–18, provenance and detailed findings are in `evidence/cs1237-protocol/protocol-verification.txt` and companion files. The prior original-firmware/capture evidence remains separately frozen at `evidence/z-probe-sensor-path/`.

Verified details:
- POR Config0x0c. Recovered Config value0x3c selects REFOUT enabled,1280 samples/s,PGA128,channelA. It is a value, not an addressed register number. Page17.
- Signed24-bit two's complement, MSB first, output advances on rising SCLK edges.0xffffff is valid−1. Full-scale rails0x7fffff/0x800000. Page14; the printed negative-limit threshold has an apparent sign typo.
- Clocks1–24 data,25 Config-written flag,26 reserved0,27 force-high.28–29 input turnaround,30–36 command0x65 write or0x56 read,37 turnaround,38–45 Config byte,46 device-output/high. Page16.
- Continuous conversion; nominal periods100/25/1.5625/0.78125 ms. Read completion/clock27 does not restart the conversion timer. Page15.
- Typical initial settling:2 ms plus3 periods at10/40Hz or4 periods at640/1280Hz after power-on/wake/channel change. PGA/rate changes use0.8µs plus the same digital settling. Page13.
- SCLK high and low minimum455ns. Update exclusion interval26.13µs typical. Power-down after high>100µs, wake low minimum10µs; Config retained. Pages12,15,18.

## Deliberate test contracts, not extra silicon guarantees

The datasheet is insufficient for a cycle-accurate/native drop-in model. This core is intentionally restricted:

1. **Output propagation is chosen explicitly.** Constructor requires `outputDelayNanoseconds >=455`; tests choose500ns. The datasheet prints455ns under MIN for new-data delay, not MAX. Old-data hold is only guaranteed for227.5ns minimum, with455ns maximum. For a changed driven bit, the core exposes `OutputTransition=true` and an unavailable/null result from228ns (integer-nanosecond ceiling) until its explicitly chosen new-data time. This is distinct from the released host-input phase. A future GPIO adapter must never misinterpret an unknown transition as a valid low or a real high-impedance guarantee.
2. **Host input bits must cover the whole high phase.** The input capture edge/setup/hold are not specified. The core checks the bit at rising and falling edges and rejects any change during high, then accounts for the bit at falling. This is a conservative transaction-test contract, not proof that silicon captures on falling edges. Finite setup/hold margins still need validation for native integration.
3. **Turnaround instants are conventions.** The core releases at clock29's chosen delay, chooses a dummy high at the read separator37, and drives high at46. The datasheet gives clock ranges/direction, not exact sub-edge moments. Both conflicting and same-level simultaneous host/device drive are rejected outside released ownership. This can deliberately reject flows that real silicon might tolerate; it must not be loosened merely to make native startup succeed.
4. **Timing uses nominal/typical values.**302ms default power-on,3.1258ms for0x0c→0x3c rate settling,5.125ms wake at0x3c, and26.13µs update windows are modeled typical values, not guaranteed upper-bound readiness. Power-down is represented at100001ns, a strict `>100µs` convention; exact boundary behavior is not established.
5. **Unsupported input is visible.** Pre-ready short clocks, unrecognized commands, partial transactions across updates, stop25/26, extra clocks, illegal/reserved settings, too-short pulses, ambiguous input changes and ownership faults latch `ProtocolFault`, increment `Errors`, retain `LastError`, and expose no valid device output. These are model diagnostics, not undocumented chip error codes. SCLK-high power-down is handled separately. An explicit power-on reset or a proper power-down/wake transition resets protocol state; no firmware reset hook exists.
6. **No implicit analog source.** At conversion time, absence/removal of an explicit `SetSyntheticCode` source raises a model error. It does not return0,−1, a saturation sentinel or fake ready. Disconnected analog behavior is not specified by the datasheet. `SaturateIdealCode` is a mathematical test helper only, not a force/voltage calibration. Channel settings do not manufacture temperature or internal-short data; the external test source remains explicitly synthetic.
7. **REFOUT switching is unsupported.** Config settings that change B6 are rejected because this pass did not establish analog settling for that change. Reserved channel01, B7=1 and temperature mode with PGA other than1 are rejected. Valid digital Config readback does not establish any analog accuracy.

## API and scope

`Cs1237Protocol(outputDelayNanoseconds)` creates the isolated state machine at time0. `SetSyntheticCode` assigns only laboratory data. `SetHostDout(bool?,time)` uses null for host release. `SetSclk(level,time)` supplies actual test clock edges; repeating a level creates no edge. `AdvanceTo(time)` processes conversion, update, propagation and power-down deadlines. Time cannot go backwards.

Inspect `DeviceDout`, `OutputTransition`, `ResolvedDout`, `ClockCount`, `Config`, `NextReadyNanoseconds`, conversion/read/write counters, and fault diagnostics. `Ready` means a conversion frame is available, not that every low data bit is a new DRDY event. `PowerOnReset` is actual device power-on behavior, not an MCU reset or a homing reset. It retains the explicitly supplied laboratory source and diagnostics while resetting Config/readiness. This isolated reset requires the caller to supply idle-low SCLK and released host DOUT first; it rejects other host states rather than pretending a chip reset can reset host-driven pins.

## Tests and future gate

Coverage includes signed rails and−1, bit order/propagation, complete27/46-clock frames, all rates and settling, update/status flags, continuous unread replacement,24-only LSB hold, power-down retention, wake-low minimum, POR defaults, saturation helper, invalid/missing sources, short clocks, pre-ready clocks, host ownership/conflicts, unstable input, unsupported settings/commands, all valid PGA choices and temperature-mode configuration, missing command inputs, partial command/configuration, extra clock47, and final clocks24/27/46 crossing an update window. The latter boundary tests include both a high final clock and a low clock with pending propagation; a complete-word count waits for both the final falling edge and data propagation. A long explicit delay test ensures a stale clock46 force-high cannot overwrite a new conversion-ready edge.

The original constructor does not explicitly wait for DRDY, but that does **not** prove a timing violation: an ADC powered with the board may already have settled before the host sends configuration. Before any native hookup, verify actual device power-on/ready time versus the first clock, output timing, bidirectional ownership and the unspecific write-capture behavior. Do not accept pre-ready clocks as a shortcut.

A future causal physical model still needs sourced or explicitly chosen bed/nozzle datum, initial clearance, travel sign, contact compliance and force→counts transfer. None is inferred here. Original filtering, arming, trigger generation, retries, motion limits and all safety guards remain untouched. No PA7→PB2 bridge is provided.

Restoring this checkpoint means unpacking only this experimental directory and its evidence. It does not change active/default profiles or restore live state. No integration is authorized by a unit-test pass.
