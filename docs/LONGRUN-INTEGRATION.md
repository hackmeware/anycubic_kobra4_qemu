# R9 configurable virtual limit: integration overlay

Status: implemented and tested on a separate copied package. NEVER applied to the running printer or original work tree. No long firmware run was started. This is a source overlay, not a complete emulator distribution.

## Apply safely

Use an OFFLINE COPY of Kobra4-R9-Integriert-Firmwarefrei-20261113.zip's unpacked Kobra4-Emulator directory. Do not apply in a running tree. Keep original snapshot and instance disks unchanged.

```
python3 apply_overlay.py --target-copy /absolute/path/to/copied/Kobra4-Emulator
```

The script verifies every file in the original root FILE-MANIFEST, then exact before hashes (or required absence for new files), verifies every overlay after hash, writes only the14 listed files, and verifies the resulting complete root manifest. It deliberately rejects reapplication or a different/modified baseline. It never regenerates acceptance hashes from unknown input. Make a copy first; installation is not an all-files transaction if the filesystem fails mid-write.

Example future run, after applying to a copy and preparing authorized local firmware:

```
python3 start.py --inputs /private/prepared/inputs --output /private/new-run --profile r9-calibration --virtual-limit-seconds 3600 --seconds 14400 --ui --execute
```

This example is NOT claimed successfully calibrated. --virtual-limit-seconds is only accepted with r9-calibration. Default719. Integer2..86400;1 is rejected because fixed1s MCU bootstrap would already reach the deadline. --seconds remains separate HOST observation limit. Shared virtual stop is absolute since emulation start, including bootstrap. More virtual time does not speed execution. UI restrictions and offline/SLIRP behavior are unchanged.

## Trust/contract wiring

CLI validation occurs before output preparation, model execution or opening persistent instance state. Immutable RunLimits is passed into R9 plan and rendered observer, original model argv receives --lis-run-limit-seconds. The actual shared-model renderer includes the C# bound class and invokes ConfigureRunLimit BEFORE StartStatus and before bootstrap RunFor. Configuration is once-only, paused, virtual time0, before any status write. Native model status advertises the same contract. Final starter consumer compares against the trusted RUN-PLAN contract and exact paused Renode boundary; it rejects missing/mismatched long-run contracts, sensor faults, wrong time, and unpaused state. Failure returns diagnostic exit8, never a calibration-success claim.

Persistent instance binding now includes the exact run-limits digest. Changed limit/model/source binding cannot silently resume an existing disk under a different contract. Use a fresh separately preserved instance for experimental validation; do not clear bindings.

## Pins and scope

SOURCE-PINS.json updates only reviewed changed attachment and adds BoundedStatusRunLimits.cs. Precise changed hashes are propagated into execution-manifest and INSTANCE-PINS plus final FILE-MANIFEST. Every original populated pin was compared to actual original bytes before replacement. Historical evidence R5-DELTA-MANIFEST remains unchanged, as it records old executions, not current acceptance. OVERLAY-CHANGES.json contains exact before/after map. Original total file manifest verified during generation and application. Original work tree remains unchanged.

Historical native-ui-resonance/runner.py and observer.py retain their720s thresholds. The supported path here is start.py / reconstructed start_diagnostic.py, whose generated observer has its own strict stepping guard. Do NOT call this overlay a migration of historical runners. Their old behavior is deliberately preserved.

## Verification completed

-51 existing starter regression tests pass after final changes.
-5 new integration tests pass: actual CLI plan, actual run_link argument validation and shared_mcu.prepare rendering with true source gates; default719; other profiles unchanged; invalid/profile-incompatible limits rejected before output; final trusted status consumer rejects five mismatches/faults.
-C# model contract and full attachment compilation/lifecycle tests from prior candidate retained:13 checks, real3-model configuration/StartStatus/Close/Dispose with zero firmware execution.
-9 Python low-level boundary/type/cleanup/status tests retained.
-Standalone after-manifest verification on staged package and original unchanged proof pass.

First repeated renderer test correctly hit a fresh-output exclusivity error from thermal-profile.json.pending; the test was corrected to create a NEW run instead of removing/bypassing the original gate. Final integration suite passes.

No firmware, private disks, OTP/credentials, generated firmware-derived boot output or runtimes are included in this overlay ZIP. Test scripts refer to private local inputs solely for no-execution preparation and require a local matching base package to reproduce. Long calibration, persistent resume, native fault handling after hours, resource growth and maximum86400s execution remain untested.
