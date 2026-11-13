# Native homing completion c3: offline implementation

## Scope and interfaces

Install observer.py, protocol.py and physical.py in the NEW profile at
rv1106-at32-link/experimental/native-homing-completion/. Parent supplies and
pins run_homing_fixture.sh, runner/supervisor and full source closure. No c2
source or evidence was changed. This implementation was tested offline only.

The public entry points remain run(root, run_name, cache, runtime=None),
validate_final_report(report) and validate_artifacts(directory, report=None).
The production root is the installed profile. The launcher is fixed to
experimental/native-homing-completion/run_homing_fixture.sh. Final report is
homing-completion.json and successful phase is verified_homing_completion.
Success requires exactly eight completed, ordered RPCs: ready, baseline,
home_x, status_x, home_y, status_y, home_z, status_z. There is no release,
RunGcodeScript, extra motion, heat, or StartPrint path.

Mandatory report fields: integer request_count=8, homing_completed=true,
natural_release_observed=true, physical_completion_proven=false,
calibration_completed=false, final_export_requested=true, integer
launcher_exit_code=0. All inherited cold/profile/wire/source/clock/cleanup
checks remain mandatory. These flags describe homing and automatic release in
the fixed virtual fixture only, not full calibration or hardware accuracy.
A provisional success is never persisted before final validation.

## Completion and later evidence

Native XYZ logs must be fresh and ordered. Probe evidence must be fresh since
home_z, balanced PA7/PB2, exact +1 microsecond propagation, and low at native Z
completion. Counts are frozen there, so even an extra pulse during status_z
fails. The 600 host-second / 5 shared-second settling budget starts when native
Z completion is observed, includes status_z and final capture/export, and does
not extend the 4760 work, 4768 active, 4780 supervisor, 4800 outer or 45 shared
second ceilings. Parent owns outer budgets/resources/identity enforcement.

After verified cold status_z, Physical.arm_completion(anchor) replays the raw
physical suffix after the last fresh matched pulse. The anchor binds home_z
queue physical source time, final pulse source time, native completion observed
shared time and status_z completed shared/physical source times. It never uses
old initial clearance as release evidence. Automatic lift and settling can
start before status_z completes, but readiness cannot be reported until then.

Readiness requires continuous >=0.5 source seconds of clearance>=0.5 mm,
force exactly zero, contact off, abs(Zvelocity)<0.05 mm/s, and <=0.05 mm total
range on each of X/Y across the settled interval. Physical sequence, gaps,
producer-local source ages/leads, initial fresh 0.25-second cadence and trace
status remain strict. The original c2 100ms shared growth-freshness rule is
retained. Shared clock JSON and physical CSV are separately sampled exports,
so no false1us equality is assumed between them; the shared clock is refreshed
after acquiring physical bytes. Once ready, every later sample must preserve the hold. After the first
>=0.5 mm clear sample, recontact is fatal, including sub-sample transitions
found only at final export. Final contact validation proves a fresh Z contact-on
and a final off transition after the final pulse and before first clearance.
Final probe counters, contact transitions, physical trace, cold thermal exports,
native logs and RPC captures are revalidated after normal stop/export/cleanup.

## Monitor parser

The COLD_* envelope names match the unchanged launcher exports. For each
envelope, final_health accepts exactly one of two schemas: response-only, or
the exact ordered machine/getter echo then response sequence, including the
no-response Stop and exact ending echo. Empty LastError is a required empty
response, never stripped or inferred. Mixed/missing/duplicate/reordered/wrong
machine/getter/value/counter/error or trailing content inside the envelope is
rejected. CR/ANSI normalization runs on decoded raw bytes, not text-mode
universal newline conversion. Proven L1..L200 formatter is retained locally;
the pinned shared formatter remains unchanged.

## Reproduction and limits

From this directory:

    PYTHONDONTWRITEBYTECODE=1 python -m unittest -v test_completion test_runtime
    PYTHONDONTWRITEBYTECODE=1 python replay_c2.py --source-profile /path/to/profile --run-directory /path/to/immutable/c2/run

Tests resolve installed sensor30 sources or explicit HOMING_TEST_PROFILE.
Raw-evidence tests use HOMING_C2_RUN or the immutable sibling c2 run. Only two
small status/ready binary fixtures are bundled, with hashes. The mock runtime
uses real packet/client/command builders, decoded octal uploads, shell checks,
captures, bounded log formatter, final probe/contact/physical parsers and full
artifact replay. Process ownership, profile closure and thermal/model exporters
are explicitly synthetic. No command string is executed by the mock.

The actual c2 replay demonstrates no completion at Home Rail Complete or cold
status_z completion, and first readiness at source34.72572384s, from stable
start34.225114s. Final clearance8.042412795mm and stable duration1.171456s.
It is an OFFLINE replay, not a new native pass; c2 remains strict nonpass.
c2 did not store physical samples at RPC queue/completion, so this replay
explicitly derives the latest raw source sample at/before recorded shared
times. c3 records those samples directly.

No full calibration, real-hardware accuracy, probe rearm, electrical timing
fidelity or repaired thermal provenance is claimed. Historical bit-trace
capacity/timing limitations remain explicitly qualified. No new native run
was performed. Next acceptance requires a separately authorized, pinned c3
native execution and ordinary complete export/cleanup, not reuse of c2 as a
successful c3 report.
