# Cold release observer integration

Status: ready for independent offline review, **not executed natively**. Thirty-two offline tests pass, including a mocked complete ten-RPC runtime and artifact replay. Packet generation never executes a client. CPU/firmware/emulator/client execution was not performed by this worker.

## Install and invoke

Copy `observer.py`, `cold_protocol.py`, and `cold_physical.py` together into the new profile's `rv1106-at32-link/experimental/cold-z-release/`. Keep original sensor30 observer/protocol and all pinned pure helpers unchanged. Use the existing parent's isolated Python, fresh cache, source manifest and resource/subreaper supervision; CLI is `observer.py --run-name <fresh-name> --seconds 4768`.

The only launcher path is `rv1106-at32-link/experimental/cold-z-release/run_cold_release_fixture.sh`. The fixed environment uses recovered QEMU clock-snapshot `runtime/run-baseline`, scalar clock, legacy bootstrap, quantum1us, icount0, autobaud, mcu-control-only, recovered30C, no thermal profile/heater, synthetic-functional Z, no SRAM-reading motor tracer, and the parent's fixed fixture. The launcher must reject conflicts, not silently change these values.

Parent owns immutable source closure, profile binding, host resources, inner4780/outer4800 budgets, process-group escalation and subreaping. Observer owns active4768, work4760, absolute shared45s, readiness1500host/18shared, stage1500host/18shared, release600host/5shared and an eight-second bounded child wait. Budgets are fail-closed sampled limits, not instantaneous guarantees. A cleanup timeout returns failure; parent must still terminate/reap descendants.

## Fixed behavior

Exactly: PrinterState, GetStatus, Homing X, GetStatus, Homing Y, GetStatus, Homing Z, GetStatus, one RunGcodeScript, final GetStatus. Release field1 string is exactly `G91\nG1 Z1 F60\nM400\nG90`. No alternate payload, larger lift, retry, StartPrint, heater command or thermal-controller access exists.

Each RPC has a unique token and fresh shell check. One console batch may be pending, including log polls. Build attempts and append intents are saved before action. Partial/uncertain appends are never retried. Strict two-message GetStatus semantics preserve the actual r7 first-default-zero/second30-25 pair; only message two is selected, always by sequence. Both targets must be zero. Strict successful unary transport must contain one empty protobuf for Homing/release. Empty acceptance never proves execution.

XYZ requires fresh ordered native begin/completion logs, strict RPC acceptance and native error review. Original exact auxiliary-error classification and scope are retained. The pinned original XYZ profile validator is evaluated before first motion and after export.

Physical rows are immutable prefixes with sequence0 required, finite scalars, declared geometry/torque correspondence, monotone axis clocks, age<=100us and lead<=1us. Only sequence0->1 may have a long startup gap. Before X, at least0.25source-s of contiguous <=25ms cadence beginning at sequence1 is required. All subsequent gaps fail closed. Unchanged-byte reads skip CSV parsing after prefix/final-tail checks, retaining required freshness checks; startup-only reads may omit freshness until sampling is required. A pending live partial CSV tail can complete later; final tails must end in a newline. Physical freshness is100ms after sampling starts/before RPCs; nozzle freshness250ms accommodates its100ms cadence. No source/host coordinate equivalence is claimed.

Before release: fresh Z-stage high/low probe pairs matched one-to-one on PA7/PB2, <=1us absolute timestamp difference, both low; successful status; settled physical contact for0.25source-s, force(0,5]N, compression0.005..0.25mm, speed<0.05mm/s. Probe row floors are recorded before this run's Homing Z; older pulses cannot qualify. The release freezes both live edge counts and rejects any later edge.

Release acceptance: positive physical Z displacement0.8..1.2mm, clearance>=0.5mm, force0/contactoff, speed<0.05mm/s for0.5source-s; |XYdelta|<=0.05mm; wrong-sign<-0.05mm/excess>1.25mm/force>5N fails. Continuous contact-transition export rejects recontact beyond sampled positions. These are model integration/trace-resolution observations, not sub-integration or hardware guarantees.

## Telemetry and final exports

Trace worker provides `physical-state.csv` with exact header in cold_physical.HEADER and final `physical-state-status.json`. Live status JSON is NOT required: active checks consume complete rows, immutable prefix, sequence and freshness; final status must prove stopped, exact row count, zero drops/errors, no capacity loss and empty error. Probe streams are live `nozzle-z-probe-edges.csv` and `main-z-probe-edges.csv`; required file disappearance fails. These edge writers do not expose a live heartbeat/error counter, so stationary writer health is established at final export, not asserted continuously.

The launcher's final monitor envelopes must match tested CPU-free rendering: `COLD_PROBE_nozzle_BEGIN/END`, `COLD_PROBE_main_BEGIN/END`, and `COLD_CONTACT_BEGIN/END`. Probe values: True(before stop), False(after), rows, drops, edges, False(capacity), empty LastError line. Contact values: False(stopped), rows, drops, empty LastError line. Exact integer decimal/hex spellings are parsed; malformed/missing/duplicate markers, command echoes, missing empty LastError lines, nonzero drops and mismatched counters fail.

`contact-transitions.csv` must prove actual Z contact release and no subsequent recontact. Final nozzle stream/export identity and all cold/zero-demand predicates reuse original final_passive. Final Z force/sensor bound/error predicates remain required. Historical optional bit/query trace capacity limitations remain explicitly disclosed; no complete per-bit/filter causality claim is made.

## Independent acceptance API

Report: `cold-release-observation.json`; success phase `verified_cold_release`, `virtual_release_proven=true`, `physical_completion_proven=false`, `calibration_completed=false`, exact release_gcode. Genuine `ready-prerequisite.json` is written in inherited readiness shape only after success, normal export and launcher exit0. Readiness alone never means release success.

Parent MUST call both `validate_final_report(report)` and `validate_artifacts(run_directory, report)`. The former replays strict response bytes, exact sequence/attempt/batch lifecycle, native rail evidence, pre-motion cadence, new Z pulse pairs and physical holds. The latter independently reopens actual request/wire/console/CSV/status/contact/nozzle/profile artifacts and compares report evidence. Parent source/resource/cleanup gates remain additional requirements, not replaced by these validators.

## Source dependencies

- New: observer.py, cold_protocol.py, cold_physical.py (pin final hashes in parent closure).
- Original sensor30 observer.py SHA256 `04311b970f4f1d250cb4d7ac2cc340275a616f1568a7ace9e81108d0d0723db9`.
- Original sensor30 protocol.py SHA256 `306495b2a0f714d9114b5c5cd454ef7a5535b6515e5574ec2826965a71893d73`.
- Original scripts/run_native_xyz_observation.py SHA256 `5715bd6e8ac16e02b7b7b42fdfce50f75bf3af585269ea68f84e8cdace219153`; only the two exact AST definitions validate_tmc_manifest/validate_profile execute, not its generic helper import machinery/main.
- All three protocol.HELPER_PINS: stream-end make_probe.py; native-controller/status_snapshot.py; schema-temperature/temperature_schema.py. Only reviewed pure builders/parsers are loaded; no thermal controller is invoked or qualified.
- Original Ready classification baseline console and BASELINE_SHA256, unchanged.
- Fixed new launcher, physical tracer and all parent-listed runtime/source/profile dependencies remain separately mandatory.

Offline command: `PYTHONDONTWRITEBYTECODE=1 python sensor_run_check/cold-release-c1/observer-overlay/run_offline_tests.py`. See offline-tests.log. The full runtime tests intentionally use a synthetic adapter, fake shell/console completion, fake nozzle final helper and synthetic health/model-export hooks; separate pure tests cover real strict parser, physical, probe, contact and health logic. No mock test is evidence of native execution, direction or calibration.

## Bounded report evidence

The pre-X cadence and prerelease contact evidence retain only the latest minimal qualifying contiguous0.25source-s suffix (starting at sequence>=1), normally26 or27 samples each. Full source history remains in the immutable raw CSV and continuously validated in memory. All postrelease rows remain in the report and independently replayed, so late drift/recontact checks are unchanged. A regression with4501 source rows over45s,500 postrelease rows covering the entire5s budget, long finite scalar values and real mocked lifecycle metadata serializes to525537 bytes with indent2, comfortably below the wrapper1MiB cap. No raw history is discarded.
