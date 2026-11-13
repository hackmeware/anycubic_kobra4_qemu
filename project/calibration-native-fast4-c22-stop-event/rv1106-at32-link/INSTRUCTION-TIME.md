# Explicit instruction-count diagnostic

The default execution model remains unchanged. `--clock-coupled --clock-source
qom-deadline --qemu-icount-shift 0` selects QEMU instruction-count virtual time,
with 1 ns per guest instruction and idle warp. Other accepted shifts 0..10 mean
2**shift ns/instruction. This is a simulation assumption, not a measured CPU
frequency or cycle-accurate model. QEMU virtual time remains QEMU's actual clock;
no time report, position, homing flag, detector or safety state is fabricated.

Why explicit: non-icount virtual time counts host-running elapsed time. A host
OS deschedule can overrun the 5 ms bound before a deadline callback runs. The full
native-event-contact run demonstrated 7,078,778 ns overshoot after 2,160 transitions
and correctly stopped. Short smoke passes did not prove a sustained bound.

Instruction-count mode is opt-in, requires native QOM deadlines, and writes its
exact launch/time-model metadata to qemu-execution.json. The original 5 ms lead
bound and original firmware guards remain enforced. Tests of this mode must be
reported separately from non-icount mode. Configuration tests pass; sustained
runtime and full calibration remain pending.
