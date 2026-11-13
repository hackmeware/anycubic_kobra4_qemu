# Snapshot client (isolated experiment)

`SnapshotClockClient` subclasses the immutable STOP-event client and reuses its
bounded stream, exclusive ownership, request ID validation, lifecycle failure,
and RESUME-then-STOP sequencing. It makes no VM launches or coordinator changes.
Use the same caller-owned binary streams, timeout, and shutdown/reaping policy.

Imports require these directories on `PYTHONPATH`:

- `scripts`
- `experimental/stop-event-clock`
- `experimental/clock-snapshot/client`

The only clock observation is read-only QOM `/machine:virtual-clock-state`.
Unsupported, missing, malformed, stale epoch/reversed time, and failed responses
invalidate the connection with no fallback. Schema 1 permits additional fields
but requires every documented field, exact bool/int types, the expected source,
enabled and initialized true, and an unchanged positive epoch. Deadline is
nonnegative; callback and stop timestamps use -1 only as the unset sentinel.
Repeated timestamps while paused are valid, so identical snapshots alone are not
proof of staleness. Arming and completion checks bind state to the exact requested
deadline, rejecting stale snapshots at those transitions.

Each run makes three coherent snapshot reads (before arm, after arm, after STOP),
one existing deadline setter, and one cont. Armed state must be paused with exact
deadline, unchanged virtual time, fired false, and both timestamps unset. Final
state must be paused, fired, unarmed, and match the requested deadline, with
`deadline <= fired_ns <= stop_ns == virtual_time_ns`. Stop and callback timestamps
are read actual values, never reconstructed. Any run failure attempts bounded
best-effort stop; the owner must terminate/reap if cleanup fails. `get(name)` is
available for explicit diagnostics but never used internally as a fallback.

Retain the existing external coordinator unchanged: 1 ms slice, 5 ms maximum
lead, 1 ms maximum lag, exact final catch-up. No speed benefit is claimed from
offline tests.

From `experimental`, run:

    PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s clock-snapshot/client -v

The suite includes snapshot schema/phase/cleanup faults and reuses the original
STOP race, timeout, bounded pipe write, lifecycle, and exclusive ownership tests
against the new subclass. No original deliverable is modified.

## Exclusive-coordinator limitation

Epoch 0 is intentionally rejected at construction. An already-armed initial
state is rejected before `run_until` can arm or resume, including a deadline
left armed after a manual stop. This client targets exclusive coordinator
ownership, not a general manual stop/rearm workflow.
