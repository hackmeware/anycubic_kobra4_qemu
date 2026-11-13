# Bootstrap boundary comparison (experimental; native equivalence unproven)

This directory is an explicit diagnostic experiment, not a production launcher.
Runtime results are now saved under evidence/: synthetic-r1 passes its full1s timer comparison; native-baseline-a, native-candidate and native-baseline-b complete cleanly, but motor SRAM differs even between identical baselines. Twelve other captures match. Full native equivalence is NOT established. Offline unit tests do not launch Renode or vendor firmware. Runtime commands below require the parent's
source checkpoint and explicit authorization. Checkpoint every native leg's
sources before launch, then its result before the next leg. Never batch native legs.

## Exact scope

- Synthetic: one clock-only Renode machine; 100us periodic timer witness;
  legacy 1s RunFor versus 1000 existing RenodeStepper 1ms calls. Baseline/candidate/
  baseline must match exact actual event timestamps, count (10,000), and SHA-256.
  No vendor firmware or synthetic CPU program is loaded.
- Native prefix: **20ms only**, three actual vendor MCU images and identical setup
  from `runs/startup-stop-scalar-30s-r3`. Legacy runs one 0.02s RunFor; candidate
  publishes paused acknowledgment zero before advancing through 20 1ms calls.
  This does not change production's 1s bootstrap and **cannot establish full
  native 1s equivalence**. No QEMU, guest OS, networking, homing, heater, or print
  request is issued. Firmware's own boot actions are not suppressed or modified.
- Both retain 1us global quantum and unchanged firmware bytes. Only the synthetic
  test adds BoundaryProbe. Native uses exactly the already-enabled passive observers.
- Native setup is checked against normalized ready-check monitor commands, all
  existing profile fields, firmware hashes, and model source hashes. Absolute paths
  are the only setup normalization. Generated hashes themselves contain local paths.
- Native profile: thermal=none, Z=none, heater binding absent, autobaud TMC,
  recovered nozzle NTC, centered contact assumptions, mcu-control-only wiring,
  assumed XY DIAG cable, passive motor/nozzle/GPIO/TMC observers.

## Commands (run from repository root)

Each output must be fresh. Paths must contain no spaces, quotes, or backslashes.
Use the existing runtime dependency environment if required by this installation.

Synthetic, after checkpoint authorization:

    python3 rv1106-at32-link/experimental/bootstrap-boundaries/compare.py --kind synthetic --wall-seconds 120 --output rv1106-at32-link/experimental/bootstrap-boundaries/evidence/synthetic-r1

Native baseline A, after its own checkpoint authorization:

    python3 rv1106-at32-link/experimental/bootstrap-boundaries/compare.py --kind native-prefix --mode legacy --wall-seconds 45 --output rv1106-at32-link/experimental/bootstrap-boundaries/evidence/native-baseline-a

Checkpoint result, request authorization, then candidate:

    python3 rv1106-at32-link/experimental/bootstrap-boundaries/compare.py --kind native-prefix --mode segmented --wall-seconds 45 --output rv1106-at32-link/experimental/bootstrap-boundaries/evidence/native-candidate

Checkpoint result, request authorization, then baseline B:

    python3 rv1106-at32-link/experimental/bootstrap-boundaries/compare.py --kind native-prefix --mode legacy --wall-seconds 45 --output rv1106-at32-link/experimental/bootstrap-boundaries/evidence/native-baseline-b

Read-only aggregation (requires all three successful legs):

    python3 rv1106-at32-link/experimental/bootstrap-boundaries/aggregate.py rv1106-at32-link/experimental/bootstrap-boundaries/evidence/native-baseline-a rv1106-at32-link/experimental/bootstrap-boundaries/evidence/native-candidate rv1106-at32-link/experimental/bootstrap-boundaries/evidence/native-baseline-b

## Safety, timing, captures, and limitations

The deadline covers each complete native leg, or all three synthetic legs, with
2s reserved for process-group cleanup. The source generator has the same
remaining-budget timeout. A separate watchdog kills the Renode process group if handshake or normal quit
blocks. Monitor writes use nonblocking os.write/select with the remaining deadline.
Uncertain or stopped processes receive SIGKILL, never SIGCONT; no firmware is
resumed just to clean up. Every forced signal, reason, process-group ID, time and
send outcome is recorded. Cleanup targets surviving descendants even if the leader
has already exited. Zero exit, whole-group absence, no forced termination, exact
paused acknowledgments, and all expected captures are necessary for success.
The watchdog is cancelled and joined before a leg returns; failure to join is fatal
and cannot launch a subsequent leg. Early `result.json` records failure until proven otherwise. If native launch
occurs without an acknowledged advancing boundary, `vendor_firmware_ran` is null
(unknown), never a false claim that firmware did not run. `acknowledged_time_ns`
records the latest proven boundary even after later failure. No protocol reset:
legacy uses initial id0 at20ms; candidate starts id0 at0ms and ends id20 at20ms,
using the same absolute acknowledgment path throughout each process.

Native byte comparisons cover all three 96KiB SRAM ranges, four UART streams,
passive motor snapshots, nozzle thermal live/exported CSV, TMC timing CSV, and
main/motor GPIO edge CSV. Nozzle observer drop/error counters are checked.
`renode.log` includes PC/SP and other observer status values for manual review;
**full CPU register/peripheral hidden state equality is not established**. The
aggregate truthfully reports only equality of observed captures. The existing
motor observer is decimated; matching files cannot exclude unobserved differences.
PC/SP read support and synthetic timer-only clock advancement still need runtime
validation. Empty UART/edge captures at20ms are possible and weaken the conclusion.

Normal monitor quit must exit zero. Missing files, nonzero exits, timeout, or forced
termination fail closed even if some useful partial captures exist. A source
compile or monitor export error may leave a partial run; inspect the log before
interpreting equality. Do not extend runtime budgets or start the next native leg
without checkpoint review. Full1s native comparison, full CPU-register capture,
longer boot effects, and cross-emulator alignment remain outside this experiment.

Offline validation:

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s rv1106-at32-link/experimental/bootstrap-boundaries -p 'test_*.py' -v

`evidence/offline-tests.txt` records ten passing offline tests, including real dummy processes
for blocked pipe writes, stopped-state KILL, live descendants after leader exit,
watchdog expiry/join and clean whole-group absence. These are not
runtime-equivalence evidence.

## Required outer runtime guard (supersedes direct commands above)

Run the comparator only through `outer_guard.py`. It is an independent Linux
subreaper process and survives comparator failure, adopts orphaned grandchildren,
tracks `/proc` PID/starttime/PGID/session identities, and kills tracked descendants
through pidfds without PID-reuse races. A comparator's zero exit with surviving
children also fails closed. Clean success requires the entire tracked process
population and all tracked groups to be absent. SIGTERM/SIGINT to the outer guard
request bounded cleanup; no SIGCONT is sent. Killing the outer guard itself with
SIGKILL, host termination, or kernel failure cannot be handled by this userspace
guard and is outside that guarantee.

The guard samples aggregate descendant RSS (including different sessions) and
MemAvailable every approximately20ms. RSS over4GiB or MemAvailable below2GiB fails
closed and triggers cleanup. These are sampled safeguards, not cgroup hard limits.
The outer total budget reserves2s for cleanup. Native comparator gets42s inside
an outer45s budget; synthetic comparator gets117s inside an outer120s budget.
No source or result should be overwritten; record path and comparison output must
both be fresh. Example native baseline after source checkpoint/authorization:

    python3 rv1106-at32-link/experimental/bootstrap-boundaries/outer_guard.py --record rv1106-at32-link/experimental/bootstrap-boundaries/evidence/native-baseline-a.guard.json --wall-seconds 45 -- python3 rv1106-at32-link/experimental/bootstrap-boundaries/compare.py --kind native-prefix --mode legacy --wall-seconds 42 --output rv1106-at32-link/experimental/bootstrap-boundaries/evidence/native-baseline-a

For candidate use `--mode segmented` and fresh candidate record/output paths; for
baselineB use fresh baselineB paths. Checkpoint each leg before requesting the next.
Synthetic, after checkpoint/authorization:

    python3 rv1106-at32-link/experimental/bootstrap-boundaries/outer_guard.py --record rv1106-at32-link/experimental/bootstrap-boundaries/evidence/synthetic-r1.guard.json --wall-seconds 120 -- python3 rv1106-at32-link/experimental/bootstrap-boundaries/compare.py --kind synthetic --wall-seconds 117 --output rv1106-at32-link/experimental/bootstrap-boundaries/evidence/synthetic-r1

Dummy-process tests cover comparator death with a separate-session child,
zero-exit orphan detection, overall timeout cleanup, and normal clean exit. All24
offline tests pass (including six aggregate validation tests added by the parent); no runtime emulator evidence has been produced.


## Packaged reference and final guard regressions

`reference/` contains exact copies of the five ready-check files: motor/nozzle
setup commands, shared-link script, shared-profile JSON, and model manifest.
`metadata.json` records their SHA-256 values, original repository/output/executor
paths, and unchanged firmware hashes. Every native preparation validates the
packaged file hashes before use. Only these exact original path prefixes are
relocated to the current repository and fresh output. Firmware/model hashes and
all profile checks remain unchanged. No original `runs/` directory is required.
Offline generation now explicitly refuses any attempted unbundled `runs/` read.

The outer reaper preserves comparator exit status if `waitpid(-1)` wins a race
with Popen polling. An exited dummy returning37 tests this exact interleaving.
Per-identity pidfd/signaling errors are recorded without aborting cleanup of other
processes or final evidence. Cleanup always attempts at least one observe/kill
pass, even after a wall-budget overrun. Fault tests cover a real transient pidfd
failure and a simulated already-expired cleanup deadline. Any incomplete cleanup
or forced signal remains a failed result, never a clean completion.

## Recorded result limitations

Nozzle maps20KiB SRAM; the uniform96KiB dump includes77,824 bytes of verified zero padding from unmapped space. Main and motor map96KiB. Firmware-model warnings include unmodeled IOMUX/timer bits, assumed flash size, and intentionally rejected motor flash programming/erase. These limit physical fidelity. See evidence/native-readonly-analysis for PC/SP, observer status, byte offsets and baseline reproducibility. Legacy remains the default; no longer native run is authorized by these results.

## Optional post-ack paused motor diagnostic

See [PAUSED-MOTOR-PROBE.md](PAUSED-MOTOR-PROBE.md) for the optional
`--paused-motor-probe` Legacy20ms-only experiment, exact guarded fresh command,
source/API inventory, strict read-only verifier, and offline evidence. It is
installed only after the original20ms acknowledgment, preserves all13 captures,
and adds15 pause/time fences plus a pre-install anchor and two fenced full96KiB
motor dumps. It cannot be
used as an equivalence baseline. The documented runtime command has not been run
by the implementation work; source checkpoint/resource preflight and the parent's
single-run authorization still govern launch.
