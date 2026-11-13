# Ambient observation supervision checkpoint

Status: offline implementation checkpoint only. No Renode, QEMU, firmware, target
client, native ambient observer or thermal controller was launched by the
supervision work. The new pin-owning wrappers intentionally reject a launch while
any required source/manifest pin is unset. No native result is claimed here.

## Fixed execution contract

- New outer entrypoint: `ambient-observation/outer_guard.py`. It accepts only
  `--profile`, `--evidence-dir`, `--name`, and read-only `--plan`. The profile must
  be the exact resolved profile containing these sources. Symlinked profile or
  evidence destinations are rejected. The outer record is derived as
  `<evidence-dir>/<name>-outer.json`, never an arbitrary command or record path.
- It launches only the exact new `runner.py`, using the fixed host Python 3.12
  executable with `-I -B -X pycache_prefix=<derived-path>`. The runner launches only the exact new `observer.py`
  with positional NAME and `--seconds 868`, again under that interpreter and
  the same cache prefix.
- Budgets remain 900 host seconds outer and 880 inner: 868 active, 8 graceful
  stop, 2 TERM, 2 KILL. The unchanged base guard reserves its final two seconds
  for descendant cleanup. These deadlines bound waits, not kernel scheduling,
  filesystem stalls, or a process externally killed before cleanup can run.
- The existing 15,000,000,000 ns virtual threshold remains a sampled stop
  threshold. It is **not** a strict pre-step virtual-time cap. There is no
  changed stepping, clock, frequency, model or overall virtual-time semantics.
- Observer-specific limits are 180 host seconds after Ready and no capture entry
  after 680 host seconds; their implementation belongs to `observer.py`.
- Launch environment is rebuilt: Legacy bootstrap, scalar clock, autobaud,
  1 microsecond quantum, icount 0, thermal profile none, Z profile none, heater
  disabled and the retained baseline QEMU launcher. Inherited shell/Python/loader
  overrides, conflicting preset values and launcher override variables fail
  before target launch. Unrelated inherited variables are not forwarded.
- The cache prefix is derived as `<evidence-dir>/<name>-python-cache`, outside
  the future run directory. It must be absent, canonical, and have the existing
  evidence directory as its parent. It is never created by the wrappers. The
  runner requires the exact runtime prefix plus isolated/no-bytecode-write
  interpreter flags. A conflicting inherited prefix is rejected. The same
  prefix and `PYTHONDONTWRITEBYTECODE=1` are passed through the clean environment
  for fixture Python processes that are not themselves isolated.
- All wrapper dynamic imports compile and execute the exact bytes whose hash was
  checked. They do not use SourceFileLoader or read cached bytecode. Existing
  production caches are neither modified nor deleted.

## Unchanged ownership and evidence gates

The unchanged, SHA256-pinned `bootstrap-boundaries/outer_guard.py` owns a dedicated
subreaper process, PID/start-time identity tracking, pidfd signals, detached-child
tracking, and adopted-child reaping. The unchanged, pinned
`bounded_native_supervisor.py` owns stop-file grace and TERM/KILL of the child's
process group. No functions or validation hooks in either module are replaced.

The inner supervisor reads `ready-prerequisite.json`, scoped to the single real
PrinterState request. Its old strict Ready gate remains unchanged. The runner
independently reads `ambient-observation.json`, hash-verifies and invokes the new
observer's pure `validate_final_report`, and adds a completed two-request gate.
Ready-only evidence cannot produce overall success. Neither synthetic tests nor
native virtual observations prove physical completion or calibration.

The runner records host progress at a target interval of one second, bounded log
tails, process-group RSS, available host memory, and observed virtual-time and
step-ack exports. Missing exports remain unknown, not zero. The runner requests
stop on telemetry errors, summed group RSS over 4 GiB or MemAvailable below
2 GiB. A sampling gap over two seconds prevents a pass. The outer guard samples
all tracked descendants, including detached children, at its unchanged cadence.
RSS is sampled, can double-count shared mappings, and can miss peaks.

The inner post-audit does not certify the outer audit. Overall acceptance also
requires the outer record to pass, no forced cleanup signals, and confirmed
absence of all descendants and tracked groups.

## Source closure and frozen-before-native gate

`execution-manifest.json` uses the following contract:

- `schema_version`: integer 1.
- `scope`: `ambient-execution-source-closure`.
- `files`: a mapping of canonical profile-relative regular-file paths to lowercase
  SHA256 values. The direct controlling sources, observer and protocol are
  mandatory. Each file is read in bounded chunks, with no execution or writes.
- Optional `symlinks`: relative link path to exact literal relative target.
  Every target must resolve inside the profile to a regular file already in
  `files`, or to one explicitly listed in `absent_targets`. Changed text,
  absolute/outside/unlisted targets, symlinked regular entries and symlinked
  parents fail.
- Optional `absent_targets`: unique canonical profile-relative target paths that
  must remain absent, neither existing nor symlinked. These preserve the four
  existing deliberately dangling build-deps links without repairing/removing
  them. Each absent target must be referenced by an exact preserved link and
  must not overlap files or links. Orphan entries, outside/noncanonical paths,
  symlinked parents, and targets that become present all fail.

The runner pins the manifest's exact SHA256. The outer pins runner, observer,
protocol and manifest. The runner pins observer, protocol and retained direct
controls. The retained Ready console copied into the new evidence directory is
a mandatory manifest entry. Runner, outer and the manifest itself must not appear inside the
manifest, preventing circular hash dependencies. The parent assembles the broad
transitive closure and performs independent review. Hashes verify identity, not
physical fidelity, calibration or the success of an unrun experiment.

Full closure verification happens in the inner runner, under the outer
900-second budget and before observer launch. The outer does only small source
pin checks and configuration checks before starting the bounded runner. A plan
is read-only and explicitly does not certify launch readiness.

Before any separately authorized native execution:

1. Finish and independently review observer/protocol and the complete closure.
2. Populate the exact observer, protocol and manifest hashes in the new runner.
3. Populate exact runner, observer, protocol and manifest hashes in new outer.
4. Freeze outer and all new deliverables in a checkpoint hash record outside
   this circular pin chain; rerun offline tests against the final bytes.
5. Recheck the retained gates, runtime, candidate overlay and input pins required
   by the parent. Record actual pass/failure, never infer them from this suite.
6. Use fresh run/evidence names and the fixed outer entrypoint only.

No old gate, production file, source pin, model, frequency, or calibration value
was changed by this supervision work. No heater, motion, print or zero command,
process-memory/loader analysis, stopped capture route, or thermal controller is
added by either wrapper.

## Offline evidence

`evidence/supervision-offline-tests.txt` and
`evidence/supervision-offline-tests-optimized.txt` record 58 passing tests each
(normal and `-O`). They cover configuration/path/environment rejection, pending
and mismatched hashes, manifest traversal/symlink checks, existing source pins,
missing/malformed evidence, resource stops, strict Ready-only rejection, and
owned cleanup. Six cache-isolation tests additionally reject existing or
changed prefixes and prove that a same-size/same-mtime stale dummy bytecode cache
cannot replace verified source bytes. That disposable cache exists only in a
temporary offline test directory; no retained cache is touched. Four additional
manifest tests cover deliberately retained dangling links and reject newly
present, overlapping, noncanonical, symlinked or orphan absent targets.

Process tests use **only disposable inert Python children**. The supervisor test
budgets are shortened only inside mocks. Outer cleanup tests import the exact
unchanged base guard in their own subprocess and use a 3-second test budget;
these tests do not add an arbitrary-command option to the new outer CLI. The
inert children only exit, sleep, ignore TERM, or spawn a detached sleeping Python
child. Dedicated tests confirm that detached children are killed/reaped and that
failure/forced-cleanup never counts as success. A mocked ambient validator used
in one inner-success plumbing test is explicitly synthetic, not ambient data.

Offline suite command (no native launch):

```sh
python3 -I -B rv1106-at32-link/experimental/ambient-observation/test_runner.py -v
python3 -I -O -B rv1106-at32-link/experimental/ambient-observation/test_runner.py -v
```
