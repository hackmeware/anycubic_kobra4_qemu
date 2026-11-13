# Fixed-budget Legacy Ready-only run

This is a separate preset copied from the reviewed `legacy-progress/runner.py`
(SHA256 `569006cc81fc34254bb3947aa39763af3bc593f2c30f234eee140fa3eb043ec7`).
The old experiment, production supervisor, native observer and original outer
guard are unchanged. The runner diff changes only the preset limits, source
directory reference and guard provenance list. Offline evidence includes that diff.

## Scope and fixed limits

* Outer host budget: **900 seconds**. The new `outer_guard.py` accepts only 900,
  verifies the original guard's reviewed SHA256 and calls its unchanged
  `supervise` implementation. Linux subreaper, pidfd identity-safe cleanup,
  descendant/orphan tracking and memory enforcement remain intact. The original
  guard's CLI still rejects limits above 180 seconds.
* Inner host budget: **880 seconds**, including startup and cleanup. Request stop
  at **868 seconds**, allow **8 seconds** graceful cleanup, then reserve **2
  seconds** each for TERM and KILL. Neither script accepts arbitrary inner limits.
* Observed virtual ceiling: **15,000,000,000 ns**. It requests stop after a sampled
  export reaches this value. It is not a strict stepping cap and can overshoot.
* Resource guards: more than **4 GiB summed RSS**, or less than **2 GiB available
  host memory**. Preflight also requires 512 MiB free disk at both output locations.
  RSS is sampled and can double-count shared mappings or miss short-lived peaks.
* Host progress samples target a **one-second interval**. Missing or malformed
  virtual-time data remains unknown. Observed sample gaps above two seconds,
  sampler errors, forced signals and unconfirmed cleanup prevent inner success.

The standard single one-second Legacy `RunFor`, scalar clock client, baseline
QEMU, `icount=0`, 1 µs quantum and autobaud TMC model are unchanged. Thermal and Z
profiles are disabled, and the native nozzle heater is off. The unchanged
observer adds its usual passive traces and may send exactly one read-only
`PrinterState` request, only after a genuine native-ready log. No heater, movement,
homing or print requests are added. No readiness is synthesized.

The unchanged observer can spend up to **30 host seconds** generating its probe;
its RPC timeout is **5 guest seconds**. Neither necessarily fits the eight-second
grace if readiness appears close to the wall or virtual cutoff. Such a run can be
terminated during generation or response collection and must remain unsuccessful.
Do not extend cleanup, rerun the RPC, alter the observer or stretch the outer
budget to turn this into success. An offline dummy test covers forced termination
of a late generator.

## Exact clean launch

The caller must first verify the environment, resources and original inputs,
freeze/hash this source, and durably save the pre-launch state. Native output goes
to `PROFILE/runs/NAME`; host evidence goes to the separate caller-selected evidence
directory. The directory must exist, but every named output and run path must be
fresh, including temporary atomic-summary paths.

```sh
PROFILE=/workspace/scratch/ca95ca5f55d9/native-clock-integration
EVIDENCE=/workspace/scratch/ca95ca5f55d9/recovery-evidence/legacy-ready-r1
NAME=legacy-ready-scalar-900s-r1
PYTHON_DIR=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin
mkdir -p "$EVIDENCE"

# Planning only: no child launch and no files written by the runner.
env -i PATH="$PYTHON_DIR:/usr/bin:/bin" HOME=/home/agent LANG=C.UTF-8 \
  "$PYTHON_DIR/python3" -I -B \
  "$PROFILE/rv1106-at32-link/experimental/legacy-ready/runner.py" \
  --profile "$PROFILE" --evidence-dir "$EVIDENCE" --name "$NAME" --plan

# Execute only after the durable pre-launch checkpoint and source review.
env -i PATH="$PYTHON_DIR:/usr/bin:/bin" HOME=/home/agent LANG=C.UTF-8 \
  "$PYTHON_DIR/python3" -I -B \
  "$PROFILE/rv1106-at32-link/experimental/legacy-ready/outer_guard.py" \
  --record "$EVIDENCE/$NAME-guard.json" --wall-seconds 900 -- \
  "$PYTHON_DIR/python3" -I -B \
  "$PROFILE/rv1106-at32-link/experimental/legacy-ready/runner.py" \
  --profile "$PROFILE" --evidence-dir "$EVIDENCE" --name "$NAME"
```

The clean launch preserves the existing Python 3.12 runtime and strips inherited
Python, loader and shell injection settings before interpreter startup. The runner
uses the same clean child allowlist and restores its caller's environment. Its
fixed observer command is:

```text
python3 -B PROFILE/rv1106-at32-link/scripts/run_native_ready_observation.py NAME --seconds 868
```

## Durable progress and acceptance

The evidence format is identical to the reviewed Legacy-progress wrapper:

* `NAME-configuration.json`: exact command, paths, fixed limits, controlling-source
  hashes for both outer-guard entrypoint and original implementation.
* `NAME-progress.jsonl`: exclusively created, append-only, flushed and fsynced
  host samples, bounded log tails, process/RSS and virtual-time evidence.
* `NAME-latest.json`: small atomic latest summary, with explicit inner-only
  success scope and outer-guard verification still pending.
* `NAME-supervision.json` and `NAME-post-audit.json`: native readiness validation,
  cleanup, sample health and independently labeled progress milestones.
* `NAME-guard.json` and `.log`: outer descendant/group cleanup and captured output.

The parent owns durable captures approximately every two minutes using
`capture_legacy_progress.py`. Copy the latest summary and timestamped byte prefixes
of logs/JSONL without modifying the running files. All such captures are **evidence
only, never resumable VM snapshots**. This preset does not add a resume mechanism.
Individual writes are durable, not one atomic transaction across all run files.

Partial exported time can appear during the active bootstrap. Full-bootstrap
completion is reported only from a valid paused step acknowledgement at or beyond
one virtual second. Subsequent Renode acknowledgements, an observed baseline QEMU
process and nonempty console are separate milestones, not readiness substitutes.

Missing, failed or incomplete readiness cannot succeed. Runner success means
strict readiness and inner cleanup only. Independently bind the outer report's
command to this exact runner/profile/run/evidence path and verify descendant and
whole-process-group absence. A nonzero inner exit makes the outer guard report
failure even when its cleanup succeeded; inspect explicit cleanup fields.
Nothing here establishes physical printer completion or authorizes later tests.

Deadlines bound polling and cleanup waits, not OS scheduling or stalled kernel/
filesystem operations. Machine loss or SIGKILL can leave an `active` summary.

## Offline tests

No tests launch firmware, Renode or QEMU. Dummy processes are disposable Python
programs, and their artificial reports are only test fixtures.

```sh
python3 -B -m unittest discover \
  -s rv1106-at32-link/experimental/legacy-ready -p 'test_*.py' -v
python3 -B -O -m unittest discover \
  -s rv1106-at32-link/experimental/legacy-ready -p 'test_*.py' -v
```

Coverage includes exact limits/configuration, arbitrary-limit rejection,
preservation hashes, no-ready/failed-ready rejection, late-generation forced
cleanup, original memory limits, detached descendant tracking/reaping, log/time
parsing, resource stop requests, signal/environment restoration and sampler
finalization. The original experiment and production files remain untouched.
