# Optional paused motor diagnostic, offline validated only

This is one optional **Legacy 20 ms diagnostic**, not a new equivalence test and
not authorization to launch. Review/checkpoint the sources and preflight resources before the one guarded run. No Renode, QEMU, or firmware was
launched during implementation or offline validation. Dynamic C# include/monitor
compatibility remains untested in Renode.

## Exact implementation and APIs

- `compare.py --paused-motor-probe` is accepted only with `--kind native-prefix
  --mode legacy`. The original setup, 1 us global quantum, firmware images,
  single 20 ms RunFor, and initial `PublishStep` remain unchanged.
- Only after `RenodeStepper` has validated the original acknowledgment at
  20,000,000 ns and it has been recorded does the comparator send the helper
  include and per-board platform-instantiation commands. The helper is absent
  from `experiment.resc`. An invalid/missing initial acknowledgment cannot send
  any probe commands.
- `PausedMotorProbe.cs` implements `IPeripheral` in
  `Antmicro.Renode.Peripherals.BootstrapExperiment`. Its constructor only stores
  `IMachine`; `Reset` is empty. Its only machine reads are, in this order:
  `machine.IsPaused`,
  `machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds` twice,
  and `machine.IsPaused` again. These exact APIs already appear in
  `printer-shared-mcu/peripherals/VirtualTimeTelemetry.cs`.
- The helper uses ordinary `System`, `System.IO`, `System.Globalization` APIs,
  manual JSON, `Guid.NewGuid`, and same-directory `File.WriteAllText` followed by
  `File.Move`. Every final fence path must be fresh; exports do not overwrite.
  This follows the existing telemetry's file-publication pattern without a timer
  or serializer dependency. Each board enforces sequential phase IDs and a
  consistent board label. A skipped/repeated phase fails.
- No timer, hook, SyncTime, MMIO read, firmware write, clock/MIPS/serial setter,
  runtime model edit, or instruction-count/full-register API is added. Installing
  the observer changes the peripheral object graph only after firmware reaches
  the original endpoint. Dynamic compilation adds wall-clock overhead.

## Capture sequence

The one post-ack monitor command batch is:

1. Select motor; dump mapped SRAM `0x20000000`, length `0x18000` (96 KiB),
   to `motor-probe-anchor.bin`; read the already-used `cpu PC` and `cpu SP`.
   This is after the original acknowledgment and **before helper include or
   installation**. It adds no RunFor or new API.
2. Include `PausedMotorProbe.cs` once; instantiate a passive helper on main,
   nozzle, and motor.
3. Export each board's `before-a` fence.
4. Select motor; dump mapped SRAM `0x20000000`, length `0x18000` (96 KiB), to
   `motor-probe-a.bin`; repeat the already-used `cpu PC` and `cpu SP` commands.
5. Export each board's `between-a-b` fence.
6. Select motor; dump the same full range to `motor-probe-b.bin`; repeat PC/SP.
7. Export each board's `after-b`, then `before-existing` fences.
8. Perform the entire pre-existing capture/observer-stop command sequence,
   unchanged, retaining all original 13 capture files and their original hash map.
9. Export each board's `after-existing` fence, then the original `quit`.

Each of the 15 files `probe-<phase>-<board>.json` records schema/source, board,
phase/index, both paused flags, and both actual local-time readings. Publication
is atomic **as a file**, not a simultaneous whole-emulation snapshot: board
reads and file exports occur sequentially. The repeated fence samples bracket
both extra motor dumps and the original bulk captures. No claim of continuous
observation or full hidden-state capture is made.

## Acceptance and interpretation

`paused_motor_probe.py` validates every exact fence schema/identity and integer
field, rejects missing/malformed/duplicate-key evidence, requires both paused
flags true, requires before/after local time equality within every fence, and
requires each individual board's local time to stay unchanged across all five
phases. The main local time must remain the original acknowledged 20,000,000 ns.
Motor anchor, A, B, and the original `motor-sram.bin` must each contain exactly
96 KiB and be byte-for-byte equal. All original 13 captures remain required and hash-checked.

The report separates:

- `diagnostic_evidence_complete`: all required probe observations were structurally
  collected. Complete observations can still fail stability or main-endpoint tests.
- `within_pause_stable`: all pause/time fences and the three motor dumps agree.
- `original_main_ack_preserved`: the main fence is still exactly 20 ms.
- `motor_sram_preserved_across_helper_installation`: the pre-install anchor
  matches the later dumps. This detects SRAM changes across helper installation,
  separately from the later within-pause stability test.
- `local_times_ns` and `board_matches_20ms_ack`: each board's actual local endpoint.
- `equal_board_endpoints`: whether those three observed local times agree.
  A stable secondary-board offset is preserved and reported, not assumed away or
  incorrectly rejected as missing evidence.
- `equivalence_established` and `full_native_one_second_proven`: always false.

The comparator can establish observations and its own clean lifecycle, but cannot
know the outer guard's final state while it is still running. Its probe status is
therefore explicitly pending guard verification. Final diagnostic acceptance
requires a separate **read-only** verifier invocation after the wrapper finishes.
That verifier requires inner zero exit, no forced termination/signals, joined
watchdog, absent inner process group, outer zero comparator exit, no failure or
signals, absent descendants and whole tracked groups, and an outer budget no more
than 45 seconds. It binds the outer command to this exact arm and flag, enforces a
comparator budget no more than 42 seconds with at least 3 seconds outer reserve,
and rereads/hashes all evidence. Guard failure remains failure, even if useful
partial observations exist.

A probe success must not become equivalence: `aggregate.py` explicitly rejects
probe-marked arms rather than treating one as a baseline. Defaults for ordinary
arms and their original 13 captures are otherwise unchanged.

## Exact fresh commands, after checkpoint/preflight

Run from `/workspace/scratch/ca95ca5f55d9/native-clock-integration`. The following
fresh output and guard paths are reserved in this document only; this document
and implementation did not create or run them. Do not overwrite a prior attempt.
The command is accepted by the final verifier exactly as shown. `python3 -B` is
explicitly supported for the comparator; plain `python3` is also accepted.
Other Python flags or reordered comparator options are not accepted by this
strict evidence-binding check. The outer interpreter's `-B` is independent.

```sh
EXP=/workspace/scratch/ca95ca5f55d9/native-clock-integration/rv1106-at32-link/experimental/bootstrap-boundaries
OUT="$EXP/evidence/native-paused-motor-r1"
GUARD="$EXP/evidence/native-paused-motor-r1.guard.json"
test ! -e "$OUT" && test ! -e "$GUARD" || exit 1
PYTHONDONTWRITEBYTECODE=1 python3 -B "$EXP/outer_guard.py" \
  --record "$GUARD" --wall-seconds 45 -- \
  python3 -B "$EXP/compare.py" \
  --kind native-prefix --mode legacy --wall-seconds 42 \
  --paused-motor-probe --output "$OUT"
```

After wrapper completion, this command is read-only and launches no runtime:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B "$EXP/paused_motor_probe.py" \
  --output "$OUT" --outer-record "$GUARD"
```

Use the installation's already-verified runtime dependency environment as needed;
do not change the command shape or increase the budget. Any compile/export error,
nonzero exit, deadline, missing evidence, forced cleanup, or surviving group is a
failed/inconclusive run. Do not retry automatically. Preserve and checkpoint the
result for review.

## Explicitly unavailable and caveats

There is deliberately **no per-board local-time fence before helper installation**.
The anchor detects motor SRAM changes across installation, but does not prove
unchanged CPU registers, instructions, timers, or hidden peripheral state. Only
the existing main acknowledgment establishes the pre-install main time/pause.

CRM frequency outputs, full CPU register files, instruction counts, and timer/
peripheral hidden state are unavailable in this minimal probe. PC/SP are the
existing monitor outputs repeated for manual review, not parsed or included in
automated equality. No timer/device-state fields are invented. No cross-run or
legacy-versus-segmented equivalence, full native 1 second behavior, physical
hardware fidelity, or root cause of prior baseline differences is established.
A successful within-pause test narrows only this run's capture-time stability.
Nozzle's original uniform 96 KiB dump still contains its existing unmapped padding;
this probe's anchor and two fenced extra dumps concern motor's fully mapped
96 KiB only.

## Offline evidence

`evidence/paused-motor-probe-offline/all-tests.txt` records the passing full suite,
including mocked monitor/ack ordering, exact plans, helper-source constraints,
strict malformed/missing/running/time-changing fences, mismatched/truncated
motor dumps and pre-install anchor mismatch, secondary offsets, main endpoint preservation, both guards,
original 13 capture hashes, aggregate isolation, and the supported `-B` form.
No emulator or firmware is invoked. Existing guard tests use bounded Python dummy
processes and fault injection, not Renode/QEMU.

A byte-preserved pre-change comparator is
`evidence/paused-motor-probe-offline/original-compare.py`, SHA-256
`0018f0b3598b67eaab124ccebcd982dcba640b647ae073d3b4079ab39d011b00`.
The mocked default-path regression compares its original command batch and result
record with the modified comparator and requires exact equality. The experiment's
original outer guard and runtime sources were not edited.
