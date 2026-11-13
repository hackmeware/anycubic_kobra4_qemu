# Diagnostic QEMU virtual deadline instrumentation

This opt-in host-side control does not change firmware, firmware guards, guest
clock frequency, or MCU frequency. It does not simulate homing contacts or make
any production-calibration claim. Existing guest timer peripherals are untouched.
Default RV1106 behavior is unchanged: no deadline is armed automatically.

## QOM API, path /machine

- virtual-time-ns: readonly int64, actual QEMU_CLOCK_VIRTUAL nanoseconds.
- virtual-deadline-enabled: bool, launch-only opt-in; enable with
  `-M rv1106,virtual-deadline-enabled=on`. Runtime writes are rejected.
- virtual-deadline-ns: int64 requested absolute deadline. While paused/prelaunch,
  write a timestamp strictly greater than actual virtual time to arm/rearm. Zero
  cancels and clears. Negative/past timestamps and running-VM writes are rejected
  without changing the existing deadline. Requires launch opt-in.
- virtual-deadline-armed: readonly bool, whether a deadline is pending.
- virtual-deadline-fired: readonly bool, true after its callback requests pause.
- virtual-deadline-fired-ns: readonly int64, actual virtual timestamp at first
  callback entry before vCPU pause; -1 until fired, cleared on rearm/cancel/reset.
- virtual-deadline-stop-ns: readonly int64, actual frozen virtual time recorded by
  the VM-state notifier after a deadline stop; -1 until available.
- virtual-clock-epoch: readonly int64, increments on every machine reset, including
  initial cold startup. Compare epochs, do not assume a particular initial value.

Rearm or cancel clears fired/stop metadata. A manual stop before the deadline
leaves it armed, allowing later continuation to the same absolute deadline.
A reset disarms/clears and increments the epoch. In explicitly enabled mode,
subsequent resets also stop the VM rather than running without a deadline. Cold
startup is unchanged. QEMU may label the post-reset stopped state `prelaunch`.
Controllers must reject RESET/epoch change and never auto-resume a reset run.

## Semantics and limits

A QEMU_CLOCK_VIRTUAL event timer queues the native VM-stop request; this is
not an external wall-clock pacing loop. The state notifier captures actual frozen
time after pause, rather than inventing time from the requested deadline.

Non-icount QEMU timers depend on host event-loop scheduling. Host descheduling
can delay callback dispatch and cause overshoot. This mechanism is NOT an exact
instruction budget and cannot mathematically guarantee a 5ms bound. Independently
check actual observed QEMU/Renode skew against the unchanged 5ms lead guard after
every stop, rejecting any violation. Report requested deadline, actual stop time,
overshoot, epoch, and whether pause was deadline-triggered. A timer-fired flag
alone is insufficient: require stopped runstate and nonnegative stop timestamp.

The callback pairs qemu_system_vmstop_request_prepare() with
qemu_system_vmstop_request(RUN_STATE_PAUSED). Upstream main_loop_should_exit()
consumes that request after timer dispatch and invokes vm_stop. Calling vm_stop
synchronously inside a virtual timer is unsafe: pause_all_vcpus disables the
clock and waits for the executing timer list, causing self-deadlock. VM-state
notification records the actual time after ticks are disabled and vCPUs paused. Like existing board timers, this instrumentation lives
for the machine lifetime. The machine already blocks migration.

## Validation before use

Source-only changes are not a working binary. Rebuild the overlay, then run:

`python tests/virtual_deadline.py /path/to/rebuilt/qemu-system-arm`

This standalone test boots no firmware or disk. It checks default-off behavior,
readonly telemetry, launch-only opt-in, paused clock stability, input rejection,
cancel/rearm, ten measured deadline stops, frozen stop timestamp, and reset
invalidation/fail-closed behavior. It rejects sampled overshoot exceeding 5ms;
passing samples do not establish a universal scheduling guarantee. Also run
existing machine/register/MMC/display smoke tests and isolated native-kernel
replay before drawing conclusions about calibration.

## Corrected source checkpoint

The first compiled extension passed existing machine/register/MMC tests, but its
synchronous vm_stop call from the virtual timer deadlocked the deadline test.
That evidence is retained. The corrected source queues a native stop request
instead; it requires rebuilding and rerunning the deadline test before use.
The test now forcibly reaps its own VM if graceful termination times out.

## Instruction-count execution and pending-stop barrier

Non-icount full native replay failed closed after 2160 transitions: observed lead
7078778 ns exceeded the unchanged 5ms guard. Host descheduling makes a universal
bound impossible with host-elapsed virtual time; a CPU kick cannot undo elapsed
time. No timestamps were clamped and the guard remains unchanged.

Explicit `-icount shift=N,align=off,sleep=off` is a different diagnostic execution
model: virtual time derives from executed instructions at 2^N ns/instruction and
advances to pending events while idle. Peripheral frequency settings remain
unchanged, but this instruction-time assumption is not a measured hardware CPU
frequency or cycle-accurate calibration. It is not enabled by default.

An initial 10-stop shift0 test passed, but sustained shift3 revealed up to
32569840 ns overshoot. Merely queuing a native stop allows additional execution.
Adding supported cpu_pause stopped execution immediately, exposing idle warp:
first callback exactly1000000 ns, frozen stop16666667 ns (next VOP event).

The next candidate pauses the sole vCPU without disabling its clock in callback,
queues native VM stop, and keeps the same timer at actual-now + 1ns while stop is
pending. This is an actual scheduler event, not a clock rewrite or reported-time
substitution. QEMU timer dispatch snapshots its current time before invoking
callbacks, so strictly future rearming cannot create a same-dispatch loop. The
main-loop idlewarp sees this nearest event instead of the next distant device
event. The VM-state notifier removes it after stop and records actual frozen time.
This ordering must still be verified with sustained tests before native replay.

Tests support explicit --icount-shift 0..10, --iterations 1..10000, and
--quantum-ns 1..10000000. They now stop at the first observed 5ms violation and
include requested/callback/frozen timestamps in failure diagnostics. A bounded
per-deadline wait also fails loudly; cleanup forcibly reaps a stuck owned VM.
