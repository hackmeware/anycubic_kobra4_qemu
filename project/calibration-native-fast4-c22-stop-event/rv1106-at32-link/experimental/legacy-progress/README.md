# Bounded Legacy progress observation

This isolated host wrapper uses the existing readiness observer and production
supervisor without changing either file. It preserves the standard full one-second
Legacy `RunFor`, scalar clock client, `icount=0`, 1 µs global quantum, autobaud TMC
model and baseline QEMU runtime. Thermal and Z profiles are disabled and the native
nozzle heater is off. The existing observer adds its usual passive traces and may
send exactly one read-only `PrinterState` request, only after a native ready log.
The wrapper adds no firmware instructions, monitor commands, virtual steps or
synthetic readiness.

## Fixed bounds

* Inner native budget: 170 host seconds, including startup and cleanup. Stop is
  requested at 158 seconds, followed by 8 seconds of graceful cleanup, 2 seconds
  for TERM and 2 seconds for KILL. Earlier exits use only the needed reserve.
* Outer budget: 180 host seconds, including the runner's preflight and evidence
  finalization. The existing outer guard owns subreaper, pidfd, detached descendant
  and orphan tracking. The runner does not replace it.
* Observed virtual threshold: 5,000,000,000 ns. This requests cleanup after the
  exported time reaches the threshold. It is **not a strict stepping cap** and can
  overshoot. A missing or malformed export is unknown, never inferred as zero.
* Resource stop thresholds: more than 4 GiB summed process-group RSS or less than
  2 GiB host `MemAvailable`. The outer guard independently monitors descendants.
  RSS can double-count shared mappings and sampled observations can miss peaks.
* Preflight requires at least 2 GiB available memory and 512 MiB free disk at both
  output locations, readable runtime/firmware inputs, fresh output paths and no
  unexpected loader, shell, Python, contact-trace or Z-profile overrides.

The host sampler targets a one-second period throughout inner startup, execution
and cleanup. It does not query an active Renode `RunFor`. Observed intervals over
two seconds, telemetry persistence failures and unfinished samplers fail closed.
These are scheduling and polling bounds, not guarantees against an OS stall,
blocked filesystem operation, machine loss or SIGKILL.

## Preparation and launch

Do not launch this without the outer guard. First persist the runner, tests,
configuration plan and controlling-source hashes in durable storage. The caller
owns durable packaging and any timestamped midpoint copy. Native run data is
written under `PROFILE/runs/NAME`; host evidence belongs in the caller-selected
directory outside this source experiment. Every output name must be fresh.

Example exact configuration and launch for this restored workspace:

```sh
PROFILE=/workspace/scratch/ca95ca5f55d9/native-clock-integration
EVIDENCE=/workspace/scratch/ca95ca5f55d9/recovery-evidence/legacy-progress-r1
NAME=legacy-progress-scalar-180s-r1
PYTHON_DIR=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin
mkdir -p "$EVIDENCE"

# Planning only. This writes no files and starts no child.
env -i PATH="$PYTHON_DIR:/usr/bin:/bin" HOME=/home/agent LANG=C.UTF-8 \
  "$PYTHON_DIR/python3" -I -B \
  "$PROFILE/rv1106-at32-link/experimental/legacy-progress/runner.py" \
  --profile "$PROFILE" --evidence-dir "$EVIDENCE" --name "$NAME" --plan

# Launch only after the caller has durably saved the preparation checkpoint.
env -i PATH="$PYTHON_DIR:/usr/bin:/bin" HOME=/home/agent LANG=C.UTF-8 \
  "$PYTHON_DIR/python3" -I -B \
  "$PROFILE/rv1106-at32-link/experimental/bootstrap-boundaries/outer_guard.py" \
  --record "$EVIDENCE/$NAME-guard.json" --wall-seconds 180 -- \
  "$PYTHON_DIR/python3" -I -B \
  "$PROFILE/rv1106-at32-link/experimental/legacy-progress/runner.py" \
  --profile "$PROFILE" --evidence-dir "$EVIDENCE" --name "$NAME"
```

The clean outer launch matters: removing inherited Python or dynamic-loader
settings inside an already-running Python process cannot undo startup effects.
The explicit Python directory preserves this workspace's existing Python 3.12.14
interpreter instead of switching the observer to the system Python 3.13.
The runner also supplies only fixed host/environment values to its observer and
restores the caller's environment in `finally`. The observer command is exactly:

```text
python3 -B PROFILE/rv1106-at32-link/scripts/run_native_ready_observation.py NAME --seconds 158
```

The existing fixture sources `build-deps/env.sh`, which sets its usual local
dependency paths. It does not inherit arbitrary ambient overrides through this
wrapper. The native one-second bootstrap is unchanged.

## Evidence and interpretation

* `NAME-configuration.json`: fixed command, run path, resource/budget limits and
  hashes of the controlling scripts.
* `NAME-progress.jsonl`: exclusively created, append-only, flushed and fsynced host
  samples. Each contains log sizes and bounded 2 KiB tails, available virtual-time
  exports, process-group identities/RSS, host timing and observed milestones.
* `NAME-latest.json`: small atomic current summary. It remains unsuccessful until
  final inner readiness and cleanup validation. A crash can leave status `active`;
  that does not mean the run is still alive. Consult the outer guard.
* `NAME-supervision.json`: unchanged production supervisor's final report.
* `NAME-post-audit.json`: combined inner result, sampling health, process-group
  absence check, maximum sampled virtual time and milestones.
* `NAME-guard.json` and `.log`: independent outer cleanup result and captured output.

Every progress checkpoint is **evidence only, not a resumable VM snapshot**. No
resume/load interface exists. Midpoint copies should retain a byte prefix of the
append-only JSONL and label the copy time; do not describe them as full snapshots
of concurrently changing output files. File and JSON writes are individually
durable, not an atomic transaction across the entire evidence set.

Partial exported virtual time may exist while the original Legacy `RunFor` is
still active. It does not establish bootstrap completion. The full-bootstrap
milestone requires an existing structurally valid, paused `renode-step.json`
acknowledgement at or beyond 1,000,000,000 ns. Later positive step IDs and increased
time are reported as post-bootstrap Renode acknowledgements. The first sampled
acknowledgement may already be later than step zero. A QEMU milestone means its
baseline process was seen, not that all clock relationships were validated.

The short run primarily measures bootstrap and early coupled-clock progress;
native readiness is not expected to fit this window. Useful milestones are kept
even when readiness is false. Missing, failed or incomplete readiness reports,
forced signals, unconfirmed cleanup, sampling errors or resource stops can never
produce inner success. Exit code 2 means no strict inner success. An orderly,
useful timed observation may therefore also make the outer guard report failure
because its child exited nonzero. Check its explicit absence/cleanup fields.

Runner success covers strict readiness plus **inner** cleanup only. Its report
explicitly leaves outer verification pending. For any accepted overall result,
bind the guard command to this runner, profile, run name and evidence directory,
then inspect both reports. The outer guard must independently confirm descendant
and whole-group absence. No report establishes physical printer completion.

## Offline verification

No test launches QEMU, Renode or firmware. The executable tests use only small,
disposable Python children with artificial readiness JSON. Those fixtures are
test data, never native readiness evidence.

```sh
python3 -B -m unittest discover \
  -s rv1106-at32-link/experimental/legacy-progress -p test_runner.py -v
python3 -B -O -m unittest discover \
  -s rv1106-at32-link/experimental/legacy-progress -p test_runner.py -v
```

Tests cover the exact command/environment/budgets, no-launch planning, freshness,
resource preflight, missing/malformed clocks, truncated and replaced logs,
nonblocking FIFO/symlink rejection, append-only progress, resource stop requests,
bootstrap milestone attribution, no-ready/failed-ready rejection, and sampler,
signal-handler and environment finalization. Production sources, firmware and
earlier experiment/comparator files remain untouched.
