# Opt-in diagnostic virtual-clock fixture

This module is simulator-only measurement instrumentation. It is not production
calibration and does not establish cycle-accurate co-simulation. Do not use on
hardware. Firmware instructions, firmware guards, QEMU clock frequency and MCU
clock frequency are unchanged. One emulated peripheral channel is initialized.

## Evidence and ownership

The shipped RV1106 machine's `hw/arm/rv1106.c:188–225` computes the secure-timer
counter from `QEMU_CLOCK_VIRTUAL` at 24 MHz. The bank is mapped at 0xff590000 with
six 0x20-byte channels. Reads have no side effects; this model schedules no timer
interrupt. Channel 5 is used only after all 48 bank words read as zero.

The 128 MiB diagnostic DTB declares the ARM architectural timer, not this bank.
A separate snapshot-disk boot reported `arch_sys_counter`, no secure-timer owner
in `/proc/iomem`, and no native avata processes. BusyBox devmem and /dev/mem exist.
These observations support instrumentation on this specific image; they are not
proof of non-use by arbitrary future guest software.

## API

- `QMPStream(binary_stream)`: exclusive synchronous QMP with lifecycle event
  detection. Stream must have bounded reads (e.g. socket timeout).
- `DiagnosticTimerClock(qmp, opt_in=True, channel=5)`: requires explicit opt-in.
- `bootstrap_commands()`: requires paused VM and pristine full bank; returns
  shell commands to disable channel 5, load both halves with 0xffffffff, enable
  with control=1, then print DIAGNOSTIC_TIMER_READY only if every command succeeds.
- `arm()`: requires paused VM, verifies load/control, establishes relative epoch.
- `now(require_progress=False)`: returns elapsed virtual nanoseconds at 24 MHz.
  Paused equal samples are valid. Only set require_progress when the caller has
  actually allowed a bounded running interval; ordinary sub-tick samples can equal.
- `DiagnosticQMP.from_pipes(base, opt_in=True)`: primary tested route. Caller
  creates base.in/base.out FIFOs and launches `-qmp pipe:<base>`; guest console
  stays stdio. Bounded pipe reads default to 3 seconds. Adapter has call/now/close.
- `DiagnosticQMP(path, opt_in=True)`: socket adapter with `call`, `now`, `close`;
  its `.clock` must be bootstrapped before `now()` can be used.
- `bootstrap_fixture(qmp, clock, exchange, offline_banner, timeout=10)`: optional
  bootstrap helper. Exchange is a caller-supplied exclusive guest-console function
  accepting `(command, marker, timeout)`, returning observed text. It MUST require
  marker as a standalone output line, not shell echo, and honor its timeout.
  The helper verifies this boot's offline-shell banner and guest ps output with
  no avata_main/avata_ui process, initializes the fixture, pauses and arms it.
  No other commands, particularly native apps, may be queued concurrently.

After bootstrap, align the Renode and QEMU relative baselines before any native
application commands. Do not derive a virtual-time ratio from wall time. Existing
coordinator and run_link modules are intentionally untouched.

## Failure behavior and limitations

HMP reads are address/count checked. Each counter sample brackets high-low-high
reads with load/control verification. Incoherence, register changes, counter
reversal, explicitly required missing progress, malformed/disconnected QMP, or
RESET/SHUTDOWN/GUEST_PANICKED events invalidate the clock. Invalidation is latched;
stop/quit remain allowed. Bootstrap attempts a pause on failure. The integrating
owner must ensure a failed run cannot continue application or MCU execution.

Control rewrites reset a hidden start timestamp, even if control stays 1. A
same-value rewrite usually causes a detectable reversal, but polling cannot
prove absence of all transient reprogramming. Load/control checks do not remove
this uncertainty. This model also preserves timer fields across machine reset,
so QMP RESET event monitoring is essential. A read-only QOM property remains the
cleaner permanent telemetry solution when rebuilding is available.

## Tests

`python tests/test_diagnostic_timer_clock.py`

`python tests/smoke_diagnostic_timer_clock.py --enable-diagnostic-instrumentation`

The smoke test boots only the offline guest with snapshot=on, no MCU peers or
native apps; writes only the diagnostic timer; verifies pause/resume behavior and
reset rejection; then terminates its VM. No production calibration claim follows.

## Recorded validation

Twelve unit tests passed. Live FIFO-QMP/stdio-console smoke passed: paused
samples were 0/0 ns; a resumed interval advanced 120403916 measured virtual ns;
subsequent pause froze count; QMP RESET was rejected. A previous stdio-QMP /
FIFO-console variant also passed (120453375 ns). These are observed samples,
not a claimed wall-time scaling ratio. The test uses the bootstrap helper.

Unix-socket QMP could not be tested here: QEMU returned `Operation not permitted`
creating its socket, including an escalated execution attempt. There was no
reviewer denial message. No more socket attempts were made; FIFO is an explicit
lower-risk IPC mechanism, not an automatic fallback or security-setting change.
