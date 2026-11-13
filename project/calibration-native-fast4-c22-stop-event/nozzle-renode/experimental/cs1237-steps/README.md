# Original-nozzle threshold tests with explicitly synthetic ADC steps

Fourteen independent original-nozzle tests pass in the previously documented **isolated8-MIPS, host-priority CS1237 fixture**. These are not production timing, physical sensor calibration, mechanical contact, Z homing or host calibration. Original firmware, sensitivity−1200, filters and guards are unchanged. The fixture supplies only ADC samples and ordinary sensor commands; actual firmware alone drives PA7. PB2 is unconnected.

## Results

After ordinary command77 `[9,1]` enables sampling, command78 `[9,3]` arms the original sensor and requests native filter reset. Baseline is retained through more than32 subsequent samples. The first changed conversion is650.290550ms in these runs.

| Baseline | Raw step | Native outcome | First trigger sample | Observed conversion-to-PA7 latency |
|---|---:|---|---:|---:|
| 0 | 0 | Stable, no trigger | none | none |
| 123456 | 0 | Stable after native arm/reset, no trigger | none | none |
| 0 | ±2400 | No trigger; filtered magnitude peaks1154 | none | none |
| 0 | +3000 | PA7 high, filtered1218 | 30 |22.911450ms |
| 0 | −3000 | PA7 high, filtered−1218 | 30 |22.912450ms |
| 0 | ±10000 | PA7 high, filtered±1275 | 6 |4.161450ms |
| 0 | ±51200 | Filtered±1200 does not trigger; next sample±2354 does | 2 |1.026450ms |
| 123456 | +10000 | PA7 high | 4 |2.599450ms |
| 123456 | −10000 | PA7 high | 8 |5.724450ms |

The nonzero baseline had residual filtered difference354 immediately before the step. Phase3 seeds slow from the existing fast filter, not raw. Hence the different ±step latencies are expected history dependence, not evidence of a one-sided threshold. Independent signed-integer recurrence predicts the zero-baseline native crossing sample counts exactly.

**Zero is not rejected as a sentinel in this nozzle path.** It is sampled, averaged, filtered and held while armed without a false trigger. The full worker contains no special raw0/raw−1 invalid check. This does not validate host-side calibration acceptance or justify synthetic zero as a disconnected-sensor response.

The trigger is symmetric: D=fast−slow; with T=−1200 it requires D<−1200 or D>+1200, settling=32, zero debounce/latch and native arm. Equality is excluded. Actual successful native UART responses are CRC-validated response181/OID9/phase4. This does not establish physical force-count orientation; a future positive-counts-per-newton choice remains a declared virtual convention.

## Original reset and missing-source negatives

After a real native trigger, phase0 requests PA7 low. Observed falling edge801.879ms. Baseline is restored, then another phase3 arm/reset permits a second actual trigger at1004.452ms. UART phases are3,4,0,3,4.

**Phase0 is not a complete disarm.** It clears+0x26 and requests deferred output-low via+0x24, but does not clear arm+0x25 or the trigger latch. In this test arm was already cleared by the preceding trigger. Phase1 also has separate release-request semantics. Do not infer a general safe disarm from an output-low response.

Removing the laboratory sample provider at650ms produces the existing model fault at650.290550ms: `No explicitly configured synthetic sample source`. PA7 remains low; no new conversion is invented. A passive fault-edge observer saves state before the original firmware attempts its next read, which the adapter rejects and stops the standalone process. This is a **fail-closed model-input negative**, not a modeled physical unplug response or proof that native host disconnect detection worked. Chipsea does not specify a deterministic disconnected-bridge value.

## Original offsets and passive evidence

- Command78:0x080098f8, descriptor0x0800cab8. Phase3 at0x0800993e sets arm+0x25, pending reset+0x38 and baseline+0x28.
- Reset path0x08009f3a clears native settle/debounce/latch and lowers PA7 before normal processing.
- Recurrence0x08009c1a..9c4e: slow+=trunc((raw−slow)/128); fast+=trunc((raw−fast)/32). First32 reset samples overwrite slow=fast.
- Strict signed comparison0x08009c50..9c64; trigger/gates0x08009f1a..9fbc. Trigger writes PA7 before storing latch/arm cleanup, explaining the pre-cleanup fields in the exact edge snapshot.
- Globals: fast0x200001e8, slow0x200003d8, settle0x20000200, debounce0x200001ec, latch0x200001f0. OID9 actual address0x200006f0; raw+0x18, average+0x1c, difference+0x3c.
- Original image SHA256 `ae09264667ff4a72905706026b1591bdede91e1f250755319fec531328e54e2f`. File offset=address−0x08004000.

`Cs1237StepFixture.cs` has a pure scheduled sample provider and a100µs passive native-state timer plus actual PA7-edge sink. It never calls SyncTime or writes firmware/GPIO. Edge timestamps use the existing GPIO clock;1µs global execution quantum means quoted latencies are virtual observations, not physical sub-microsecond guarantees. `Cs1237FailureCapture.cs` is passive file export only. Trace rows are bounded and all tests remain below limits.

## PA6 ownership review and14 CPU-free tests

Actual native PA6 configurations are nibble0x1 (MODE01/CNF00 general push-pull),0x8 (input pull) and initial0x4. Native use of open drain was not observed.

The adapter already distinguishes CNF01: open-drain ODR high is released/null for MODE1/2/3; low drives low. Fourteen CPU-free checks confirm release/pad behavior, no false overlap for released-high, and strict conflict for driven-low against device-high. Both alternate-function types are explicitly unsupported/rejected, not treated as strong push-pull. Native data reads currently require input mode, a conservative additional restriction not exercised by native open-drain sampling.

Frozen baseline378 overlap observations are classified exactly:
- Before clock1: one host-high/device-low; one same-low.
- Clock46: two same-high observations.
- After clock27:187 host-low/device-high and187 same-high, one pair per actual native sample.

Chipsea Rev1.1 pp14–16 explicitly describes holding the final bit after24, output-high at27, switching to input at28–29, and output/high at46. Page7 specifies VOH≥DVDD−0.4 at Ioh1mA and VOL≤0.2DVDD at Iol1mA. The document does not expressly identify push-pull/open-drain topology, quantify contention current/tolerance, or provide a bidirectional MCU application circuit resolving the overlap. Logical output ownership is supported; precise physical drive strength and board circuitry are not. Rejecting all same-level dual drive is a conservative core test contract, not a silicon-damage claim. Host-priority remains an explicit virtual assumption.

## Timing limitations and provenance correction

Default100-MIPS remains blocked in the strict model. The unchanged helper0x08008508 waits for DWT delta>20 each phase;21ticks/72MHz is291.67ns before other instruction/bus effects. The surrogate MIPS throughput and CRM-driven DWT frequency are independent here. GPIO applies writes without modeled bus delay; flash access0x12 is stored without inserting instruction waits.

Do not add arbitrary delay or assume two flash wait states means two extra cycles per instruction. Independent read-only timing review verified Arm DDI0337H §§3.3.1–3.3.2/3.5 and ST RM0008 §3.3.3: branch/prefetch/write buffering matter. The poll8518..851e fits one64-bit flash block. After the successful DWT read there are four simple instructions before the falling store; untaken branch does not refill. APB minimum two-cycle transfer duration is not necessarily added pulse width, because edge latencies may cancel. Physical MCU identity and oscillator assumptions remain provisional. Missing enough latency to reach455ns is **not proven**.

Sources:
- https://documentation-service.arm.com/static/5e8e107f88295d1e18d34714?token=
- https://www.st.com/resource/en/reference_manual/rm0008-stm32f101xx-stm32f102xx-stm32f103xx-stm32f105xx-and-stm32f107xx-advanced-arm-based-32-bit-mcus-stmicroelectronics.pdf
- https://documentation-service.arm.com/static/60d5b617677cf7536a55c273
- Repository `nozzle-renode/docs/startup-clock.asm`, `F1BootFlash.cs`, `AT32F403A_System.cs`, `AT32F403A_DWT.cs` and GPIO source.

**Erratum to prior baseline checkpoint:** preliminary `passive-gpio-72mips.csv` lacks a matching successful run log/metadata. Its paired log is a later compile failure; the older README's description of that pair as an export-command failure was mistaken. Treat72-MIPS exploratory provenance as unproven. The final100-MIPS negative and8-MIPS positive directories have matching exact source hashes and are unaffected.

## Reproduce and restore

```
python nozzle-renode/experimental/cs1237-steps/run_steps.py
python nozzle-renode/experimental/cs1237-steps/run_ownership_tests.py
python evidence/cs1237-native-steps/analyze.py
```

Each condition runs a fresh standalone original-nozzle process. Early multi-machine disposal attempts were rejected and are not counted; final per-case artifacts have matching source hashes. No RV/main/motor machine or Z request is used. The model-source removal intentionally terminates its test process with a visible error and pre-error evidence.

Restore this checkpoint at snapshot root. It contains only this new experimental directory and its evidence; it depends on the frozen `cs1237-native-baseline-20261105.tar.gz` source checkpoint SHA256 `7fe53a586064a29eef8494b9b75ca3694f52c7dd2057fc5599a8654a5f92dabf`. Production/default source and timing remain unchanged. A subsequent separately authorized idealized functional profile must not rewrite these strict results.
