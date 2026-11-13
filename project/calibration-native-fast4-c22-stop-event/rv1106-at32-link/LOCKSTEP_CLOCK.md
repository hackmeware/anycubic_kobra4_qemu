# Explicit bidirectional diagnostic clock stepping

This mode solves free-running Renode drift while QEMU executes a CPU-heavy slice.
It does not change oscillator/peripheral frequencies, firmware, or firmware guards.
It requires the explicit icount/QOM-deadline execution mode already documented
separately. Icount is an instruction-time assumption, not physical cycle accuracy.

## Launcher contract

Use a fresh run directory. Refuse an existing renode-step.json rather than trust
an old acknowledgement. Shared Renode startup runs its original initial RunFor1,
then calls `sysbus.timeTelemetry PublishStep ".../renode-step.json" 0` and stays
paused; there must be no final `start`. QEMU starts paused with deadline opt-in.
Reject live peer-monitor command input in lockstep. All Renode writes must use one
serialized sender; final diagnostics happen only after coordinator close.

## API

`RenodeStepper(process, ack_path, send_callback, timeout=10)` waits for ack0.
Sender accepts bytes. `step(duration_ns=1000000)` sends one global RunFor followed
by PublishStep(next id), then verifies the returned actual time advanced by exactly
the requested duration. Steps must be whole microseconds. Properties include
initial_time_ns, time_ns, epoch, step_id, timeout, and failed. `pause(force=False)`
sends pause; force=True sends SIGSTOP to the owned Renode process.

`LockstepCoordinator(qmp_client, stepper, output, max_lead_ns=5000000,
slice_ns=1000000)` establishes baselines at the current paused clocks and starts a
background loop. It exposes error and close(). Each cycle runs Renode exactly one
slice, waits for its actual-time ack proving RunFor returned and machine paused,
then runs QEMU to the corresponding absolute deadline and verifies actual stop.
Only then may another Renode slice start. There is no background free-running
Renode time to accumulate while QEMU is busy.

The unchanged positive lead bound is 5ms. Intermediate negative skew is separately
bounded by one slice (default1ms), and QEMU must catch up at every completed cycle.
Capping QEMU slices alone would not impose that negative-skew bound.

PublishStep is passive measurement: actual machine elapsed time, epoch, paused
state and step id, atomically written only after the monitor RunFor returns.
It requires paused machine, enabled telemetry and sequential ids. It writes no
firmware registers, CPU state, clocks or elapsed-time corrections.

## Failure and cleanup

Epoch/id mismatch, malformed/stale acknowledgement, wrong actual step duration,
unexpected running state, changed paused QEMU time, clock regression, or skew
violation stops the coordinator. Ack waits and QMP reads are bounded. Step failure
SIGSTOPs the owned Renode process, so it cannot silently keep running; do not
automatically resume it for final diagnostics. The launcher owns ultimate process
termination/reaping and must report unavailable final dumps honestly. Normal
close finishes an outstanding slice, pauses both sides, writes its report and
closes QMP only after the worker finishes. A bounded shutdown failure is explicit.

PTY transport is still untimestamped and may deliver bytes at slice boundaries.
Clock lockstep therefore does not establish cycle-accurate UART timing, physical
motion, successful homing, or native calibration correctness.

## Verified scope

Seven unit tests passed, covering exact steps, epoch/id/time/paused mismatches,
staleness, malformed ack, bidirectional ordering and unchanged5ms overshoot refusal.
Actual Renode clock-only smoke acknowledged1/2/3/4ms exactly with paused=true.
Joint smoke used actual Renode plus preserved QEMU binary2a9d2a79... and the explicit
synthetic ARM B . fixture with icount shift0,alignoff,sleepoff. It completed101 full
1ms cycles, max QEMU lead1ns, max intermediate lag1,000,000ns; no errors. A90second
external supervisor cap was not hit (4.877406seconds total including startup).
All owned processes were cleaned up. No native firmware was used by these smoke
tests. Full native application/calibration behavior remains a separate test.

Run tests:

python -B tests/test_lockstep_coordinator.py
python -B tests/smoke_renode_stepper.py

The joint smoke expects the preserved runtime and synthetic fixture paths used by
this recovered snapshot. Retained evidence is under evidence/bidirectional-lockstep.
