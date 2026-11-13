# Isolated batched-clock performance candidate

No shared launcher, coordinator, MCU, firmware, QEMU binary, or active-run file is modified.

- `batched_event_clock.py`: paused read-only checks are pipelined in one write with unique request IDs. Replies are mapped by ID, even out of order. Duplicate/unexpected replies, reset/shutdown/panic, command errors, malformed replies and unresolved requests invalidate the connection. A single-owner lock rejects interleaved commands. A failed connection allows only existing stop/quit cleanup commands.
- Every original epoch, paused status, actual counter, armed/fired flag, callback timestamp and final frozen timestamp check remains. No response is inferred or fabricated. Polling remains; STOP-event waiting is deliberately not implemented.
- `batched_lockstep.py`: isolated coordinator copy pipelines the boundary check and records phase timings. Exact 1ms slices, 5ms maximum lead, 1ms intermediate lag and zero negative final skew remain unchanged.
- `step_sender.py`: serialized sender uses the shared peer-write lock but adds no redundant machine selections. The existing RenodeStepper still explicitly selects main before RunFor and PublishStep. Live peer monitor input must remain prohibited.
- `timed_baseline_clock.py`: original client with timing instrumentation only.
- `benchmark.py`: clock-only Renode, synthetic ARM B . fixture, preserved exact24 QEMU, explicit icount shift=0,align=off,sleep=off. Baseline reproduces launcher monitor wrapping; candidate uses the dedicated sender. No vendor firmware, disk or native calibration is used.

Fourteen unit tests cover success, response ordering, duplicate responses, partial/pending timeout, concurrent ownership, lifecycle invalidation, epoch change, bad stop/callback, unchanged lead/lag rejection and sender command preservation.

Run the benchmark with PYTHONPATH=rv1106-at32-link/scripts and an external process-group timeout. Each mode advances at least 100 exact 1ms steps. Results are under evidence/batched-clock.

First pair: baseline 64.54 steps/s, candidate 69.42. Reverse-order pair: candidate 60.82, baseline 69.08. All four runs measured maximum lead 1ns and lag 1ms. The candidate improvement is NOT reproducible: do not claim acceleration or integrate on performance grounds. Further phase timing is required on native workloads before attributing their ~55ms/step latency to orchestration.

Binary SHA256: e700c120fe5edc5a40edc514f9e432696a1156593d80b56759d7eca01d753b7c.
Synthetic B . fixture SHA256: db8c2881cbdfd6291ff7bdd5a0a304a850d07de94cb60566880df7389a38f1d2.

Final instrumented pair: baseline 60.50 steps/s, candidate 67.80. Mean phases (baseline -> candidate): boundary 0.906 -> 0.729ms; Renode 3.794 -> 3.129ms; QMP arming 1.925 -> 1.492ms; execution/stop wait 7.676 -> 7.611ms; final checks 2.212 -> 1.772ms. The execution/stop phase dominates this synthetic fixture and is essentially unchanged. These short serial runs are noisy, not a robust end-to-end native acceleration measurement. All six runs passed 101 steps with actual maximum lead 1ns and intermediate lag 1ms.
