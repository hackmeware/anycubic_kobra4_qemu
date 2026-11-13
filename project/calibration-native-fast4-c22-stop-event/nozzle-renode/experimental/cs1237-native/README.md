# Experimental original-nozzle CS1237 GPIO adapter

This is an opt-in **isolated electrical-interface experiment**, not a production profile, physical calibration, Z-home result or force/bed model. It runs the original `inputs/nozzle.bin` without patching firmware, its RAM, averaging, filtering, thresholds, phase/arm logic or safety checks. Only external PA6 is driven. PA7 remains entirely firmware-generated; main PB2 is not connected.

## Verified result and blockers

CPU-free C# tests pass **1,421 strict protocol assertions plus20 adapter assertions**. The frozen strict core is not modified. `Cs1237NativeProtocol.cs` is a separate copy adding deadline introspection and an explicitly default-off host-priority overlap option; all455ns pulse checks and existing negative tests remain intact.

Two standalone original-firmware tests, with synthetic samples+123456 and−123456, each produced:

- One native Config0x3c write,187 actual24-bit sample words, and188 completed protocol reads including the constructor's discarded word.
- Every reconstructed sampled word matches the supplied signed source. Actual native OID9 at0x200006f0 contains matching raw and25-sample rolling-average values.
- Zero protocol/adapter errors, zero dropped trace rows, and PA7 low throughout. Phase/arm bytes remain000000; only ordinary sampling enable is requested.

These passes require **explicit test assumptions**, not established silicon behavior:

1. CPU execution is8MIPS while original CRM/DWT remains72MHz. This is a deliberately separate execution-speed fixture, not a recovered CPU calibration. Observed PA5 high pulses1125–1750ns and native sampling3125–9750ns after rising edges meet the unchanged455ns minimum and chosen500ns propagation delay.
2. Host-priority PA6 arbitration is explicitly enabled. The original MCU drives PA6 outside documented command ownership: initial high, a roughly100µs low preamble, high through clock46, and low/high after each27-clock data read. The fixture records378 overlap observations per positive run. Host push-pull dominates the external pad while output; no electrical current/damage is modeled. This is **not a physical CS1237 compatibility claim**. The strict default rejects the first conflicting drive.
3. Original captured startup bytes are replayed with200µs interbyte gaps. This is a legal laboratory pacing assumption, not recovered real host timing. Fast20µs replay at8MIPS did not configure the sensor and is not counted as a pass.
4. DOUT propagation is explicitly500ns. During the core's unknown transition interval the Boolean GPIO retains its last stable level, but a native read is rejected. No interrupt is manufactured from an indeterminate level. This virtual observation convention does not model analog transition/IRQ susceptibility.

**Shared/default100-MIPS integration is blocked:** strict mode faults on initial PA6 conflicting drive. Allowing host priority still faults on PA5 high phases330–370ns (and some low phases440ns), below455ns. Neither guard was weakened. Do not enable this in the shared/default profile based on the isolated8-MIPS result. Execution timing and PA3 UART behavior require separate coordination before any combined profile.

## Startup alignment and original evidence

In the final positive fixture, the sensor is explicitly powered from virtual time0. Nominal datasheet first-ready is302.000ms, native first PA6 drive is500.694250ms, Config write completes501.071000ms, and first native sample is504.235250ms. These are measured **isolated-fixture** timestamps. The host replay start0.4s and interbyte gaps are chosen. Actual full-system ADC power-on versus native host configuration timing is not established by this experiment.

Source of first503 UART bytes: unchanged `runs/native-home-x-heater/rv-nozzle-tx.bin`, through the actual sensor configuration at offset0x1ea. A newly CRC-encoded ordinary command77 `[9,1]`, next sequence0x18, enables sampling. There is no command78 phase/arm, finalize/homing command, factory mode or Z request. The static minimal handshake+allocate/config alternative did not execute the constructor in initial tests; it is not used or claimed as verified.

Original addresses, offsets and full disassembly are frozen in `evidence/z-probe-sensor-path/`:
- Constructor0x0800a390, file0x6390; command80/OID9/PA7/PA6/PA5/0x3c/−1200 from actual capture.
- PA5 pulse helper0x08008508 drives high at8514, low at8522, with native DWT waits.
- Native sample IDT read is0x08009a52, after high/fall/low-wait,24 bits MSB-first and three trailing clocks.
- Native post-read PA6 low/high at9a80/9a88. Sampling enable command77 handler0x08008c34. No phase command78 is sent.
- Signed conversion/averaging at9b0a..9b46, filtering at9c1a..9c64, original trigger path9f98..9fbc remains unchanged.

Manufacturer provenance, timing uncertainties and full strict protocol evidence remain in `evidence/cs1237-protocol/`. This experiment does not resolve undocumented physical host-drive tolerance or make8MIPS a real CPU timing model.

## Components and API

- `Cs1237NativeGpio`: experimental subclass of the production GPIO. It observes configuration/latch writes, including changes that produce no pad edge. Only PA5/PA6-affecting writes and the exact original sample read PC synchronize CPU time. PA3-only accesses do not call SyncTime; shared-port timing consequences remain possible. Other pins' configuration and native writes are not rewritten.
- `Cs1237NativeAdapter(machine, port, syntheticBaseline, outputDelayNanoseconds=500, allowHostPriorityOverlap=false)`: external PA6 interface driven by actual PA5 clocks, host PA6 ownership and conversion deadlines. No model activation unless explicitly instantiated. It never writes PA7/PB2 or firmware memory.
- `Source: Func<int>` supplies a constant laboratory signed24-bit baseline in the verified tests. Missing/out-of-range/throwing sources fail visibly; there is no implicit valid zero. `TimedSource: Func<long,int>` is an **unvalidated future boundary**, passing ADC-domain nanoseconds. A dynamic source must return the sample for that exact time. It must be pure because a competing deadline can cancel a candidate conversion. Do not bind a present-state motor getter to historical catch-up deadlines or assume cross-machine epochs match.
- `Protocol` exposes read-only diagnostics and the isolated protocol interface for tests. No production source or native launcher references it.
- `WriteTrace(path)` and `WriteStatus(path)` export bounded diagnostic memory. Native traces cap at200000 rows and report dropped rows. This is not streaming; paths are explicit laboratory outputs and may be overwritten by a rerun.
- Adapter errors release external PA6 and latch. Invalid native reads stop with an exception rather than return a pull/default level. Analog PA6, host-owned/released-device reads, unsupported AF ownership, source errors and unknown output intervals cannot be mistaken for sensor data.
- GPIO reset reconciles actual host SCLK/PA6 ownership and restores the still-powered sensor drive. It does not reset ADC framing/readiness/configuration. A partial frame interrupted by MCU GPIO reset remains a visible protocol fault at its deadline. Whole-emulation time rewind/power cycling is not validated.

Do not use `Protocol.SetSyntheticCode`, a monitor write or a provider to synthesize probe success. A future force fixture belongs upstream of the ADC input; original filters/arming/thresholds must continue deciding PA7. No force integration is included or approved by these tests.

## Reproduction

From snapshot root:

```
python nozzle-renode/experimental/cs1237-native/run_tests.py
python nozzle-renode/experimental/cs1237-native/run_native.py --mode strict --mips 100
python nozzle-renode/experimental/cs1237-native/run_native.py --mode host-priority --mips 100
python nozzle-renode/experimental/cs1237-native/run_native.py --mode host-priority --mips 8
python nozzle-renode/experimental/cs1237-native/run_native.py --mode host-priority --mips 8 --baseline -123456
python evidence/cs1237-native-startup/analyze.py
```

Each native test is a separate0.65-virtual-second nozzle-only boot with no RV host/main/motor machine. All inputs are local. The CPU-free tests do not load a CPU or firmware. Reruns change evidence files and require a new manifest/checkpoint.

Evidence and exact source hashes are in `evidence/cs1237-native-startup/analysis.json`, per-run metadata, unit-test manifest and `SHA256SUMS`. The original images and production GPIO/thermal/base platform are unchanged. The parent independently changed the shared launcher during this task; its changed hash is recorded rather than falsely reported unchanged.

Restore the checkpoint at snapshot root. It restores only this experimental directory and `evidence/cs1237-native-startup/`, never production/default profiles, live state, firmware, previous core checkpoint or shared launcher.
