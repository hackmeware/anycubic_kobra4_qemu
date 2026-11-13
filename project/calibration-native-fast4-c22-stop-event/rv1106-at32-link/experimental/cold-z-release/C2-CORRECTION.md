# c2 finite log boundary correction

Only the concrete c1 L21 failure is corrected. No native execution or restart occurred. c1 overlay, frozen installed profile and failed-run evidence were not edited.

Runtime delta:
- cold_protocol.py adds LOG_BATCH_LIMIT=200 and Boundary.log_command_batch with an explicit L1..L200 allowlist. It retains exact token validation, identical octal-encoded marker prefix, original fixed marker suffix helper, the same two read-only tail commands, one-line batch and768-byte cap. Both older log_command_batch and _marker_setup stop at L20, so neither is altered or used to format new cold log prefixes.
- observer.py uses the shared200 limit and the cold-specific formatter. No timing, motion, thermal, acceptance, cleanup or export behavior changes.
- cold_physical.py is byte-identical to c1.

Tests:
- All200 actual formatter labels exercised; labels1..20 are byte-identical to original formatter output. Existing strict bounded-region helper accepts their synthetic capture markers. Invalid tokens, injection-like labels, zero/leading-zero labels and labels beyond200 fail.
- Mocked runtime now uses the REAL cold formatter, not a fake LOG command builder. Only shell execution and returned log contents remain mocked.
- A late-Ready full-runtime regression crosses L21 and completes the same fixed ten-stage synthetic lifecycle.
- All34 offline tests pass. Existing representative45-second report remains525537 bytes.

Review minimal-runtime.diff for the complete production-code delta. source-sha256.txt records final hashes. Run offline suite with PYTHONDONTWRITEBYTECODE=1 python sensor_run_check/cold-release-c2/observer-overlay/run_offline_tests.py.
