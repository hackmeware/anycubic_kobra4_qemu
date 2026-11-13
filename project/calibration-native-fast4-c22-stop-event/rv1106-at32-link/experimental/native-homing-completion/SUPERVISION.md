# Native homing completion supervision overlay

Install only `rv1106-at32-link/experimental/native-homing-completion/{runner.py,outer_guard.py,test_runner.py}` from this overlay into the separate `calibration-homing-completion-c3` profile. The immutable c2 source and its retained failed/nonpass run remain unchanged. `exact-c2.diff` compares the delivered files with c2. No native firmware, emulator, client, RPC, heating, or print run was launched for this work.

## Fixed contract

- Observer CLI remains exactly `observer.py --run-name NAME --seconds 4768`, with the original isolated, disabled-bytecode, fresh-cache Python launch. No arbitrary command, environment, profile, or budget override was added.
- Outer guard: 4800 host seconds. Original bounded inner supervisor: 4780 total, 4768 active, 8 graceful, 2 TERM, 2 KILL. Observer work cutoff: 4760 host seconds. Shared-time stop remains 45,000,000,000 ns, sampled by the original supervisor; it is not a strict pre-step cap. No clock, bootstrap, quantum, or firmware timing changes.
- Resource gates remain 4 GiB summed process-group RSS, 2 GiB available RAM, and 512 MiB free disk. Original identity, freshness, cache, sampler, cleanup, subreaper, pidfd, and descendant gates are preserved.
- Environment remains cold synthetic-functional Z, `THERMAL_PROFILE=none`, native heater off, and original RAM motor tracing off. The reviewed additive launcher/physical observer owns its physical-only trace configuration. This wrapper does not modify base guards, models, or thermal gates.
- `homing-completion.json` must first pass both `validate_final_report(report)` and `validate_artifacts(path.parent, report)` from freshly hash-verified observer source. Missing, malformed, changed, missing-validator, or raising-validator evidence fails closed.
- The independent wrapper additionally requires phase `verified_homing_completion`; strict integer request_count 8 and launcher_exit_code 0; `homing_completed`, `natural_release_observed`, and `final_export_requested` exactly true; and `physical_completion_proven` and `calibration_completed` exactly false. There is no release_gcode field or literal-release requirement. Old ten-request release reports cannot pass.
- The eight RPC stages belong to the observer/protocol: ready, baseline, home_x, status_x, home_y, status_y, home_z, status_z. There is no RunGcodeScript, extra 1 mm motion, final_status, heat, or StartPrint stage. Native post-Z lift and stable physical clearance must be proven by the new observer before normal export.
- `ready-prerequisite.json` still uses the genuine original one-PrinterState Ready supervisor shape. This is one prerequisite within eight requests, not a replacement for full homing validation.
- Audit fields are `homing_completion_report_valid`, `homing_completion_report_error`, `homing_completed`, and `natural_release_observed`. Overall success still additionally requires the original supervisor's valid Ready report, exit 0, no forced signals, absent group, finished valid sampling, and no resource stop. Outer cleanup must be independently checked. Physical hardware completion and calibration remain unproven.

## Source pins and integration

All NEW pins intentionally remain `None`: runner observer/protocol/manifest, launcher/physical controls, and outer runner/observer/protocol/manifest. The overlay therefore cannot launch. Installing or passing offline tests does not authorize a native run.

The unchanged original six controls retain their c2 hashes: bounded_native_supervisor.py, run_native_ready_observation.py, run_native_event_fixture.sh, run_link.py, bootstrap-boundaries/outer_guard.py, and clock-snapshot/runtime/run-baseline. READY_REFERENCE remains the original sensor30-observation/evidence/ready-baseline.console.txt. New mandatory controls are run_homing_fixture.sh and physical.py; observer.py and protocol.py are separately pinned.

For any later reviewed freeze, the manifest scope must be `native-homing-completion-execution-source-closure`. Preserve the existing whole-source-closure schema, symlink/absent-target handling, and exclusions of this experiment's manifest/runner/outer pin owners. The older experiment remains historical source in the closure, not retroactively successful. The parent owns final profile integration, independent source review, manifest construction, and any later pin freeze. No pin is guessed here.

## Offline verification

Run `/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3 -I -B sensor_run_check/homing-completion-c3/supervision-overlay/run_offline_tests.py` from the workspace. `offline-tests.log` records 66 passing tests: the 63 minimally adapted inherited checks plus explicit old-ten rejection and two actual inert-source validator identity/failure checks.

The overlay harness uses immutable c2 only to read/hash/load original supervision sources for disposable inert Python-child cleanup tests. It never launches native executables. It reads the new sibling `overlay/observer.py` main function as AST and compiles only that CLI function with a mocked run entry point. The exact planned arguments parse; the old positional form and changed budget fail before execution. In installed tests, OBSERVER_SOURCE resolves to the new profile's actual observer. Re-run this suite on the final installed observer before any future reviewed freeze.

`guard-preservation.json` records original and delivered source identities, preserved function bodies, budgets/resources, and deliberately pending pins. This is static/offline evidence only, not native homing success.
