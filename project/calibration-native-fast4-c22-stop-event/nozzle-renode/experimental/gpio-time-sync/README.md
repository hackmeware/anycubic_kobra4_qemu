# Isolated GPIO synchronization / quantum experiment

NOT integrated into production or native runs. Original failed autobaud candidate is separately preserved as evidence/tmc-autobaud/source-checkpoint.tar.gz (cfad4ee43a2ea7812e663b380ddc0f6cb3bc09ed34b404fed7960d336a164e5a).

## Scope

AT32F403A_IO_Synchronized.cs adds the existing DWT-style current-CPU SyncTime operation immediately before GPIO MMIO reads/writes. It does not change frequency, time counters, UART bytes, baud tolerances or guard outcomes. ReadSnapshot exposes only side-effect-free configuration/input/output-latch reads for observers. The unsynchronized control has an empty synchronization operation, retaining original GPIO behavior with the same snapshot API.

The copied autobaud implementation is unchanged from the failed candidate. A second observer targets the original fixed-baud device for controlled comparison. Both observers use passive snapshots and assert unchanged virtual clock and MMIO synchronization count within an atomic clock-source read section. An initial non-atomic check failed when clock advanced260000→260375ns while synchronization count stayed8→8; the original failure is preserved. The clock-source lock provides coherent observation and prevents concurrent clock advancement during the check; it does not advance time or inject delays.

Production passive thermal and GPIO trace observers still call ordinary ReadDoubleWord, so any future production synchronization change requires auditing/migrating those reads. Do not silently make an observer synchronize CPU time.

## Source basis

The local AT32DWT already uses TryGetCurrentCPU followed by SyncTime for counter reads. Upstream STM32_Timer uses that pattern for its counter; Machine.ScheduleAction synchronizes the requesting CPU before scheduling timed events. BaseClockSource exposes ExecuteInLock, and LimitTimer.Value reads its clock entry. These support the mechanism, not a claim that this experiment solves native timing.

https://github.com/renode/renode-infrastructure/blob/master/src/Emulator/Peripherals/Peripherals/Timers/STM32_Timer.cs
https://github.com/renode/renode-infrastructure/blob/master/src/Emulator/Main/Core/Machine.cs
https://github.com/renode/renode-infrastructure/blob/master/src/Emulator/Main/Time/BaseClockSource.cs
https://renode.readthedocs.io/en/latest/advanced/time_framework.html

## Results

Actual CPU-driven request and reply edges, independent framing/CRC analysis, ten phase offsets per configuration:

- 10us global quantum: fixed baud/no sync10/10; autobaud/no sync9/10; autobaud/MMIO sync8/10.
- 1us global quantum: all three configurations10/10.
- Candidate ideal waveform suite at BOTH1us and10us:72 positives plus60 CRC/address/stop/disconnect/bad-sync negatives passed. Raw edges independently verify SENDDELAY0/1/2/3/14/15.
- A single-machine-at-a-time synchronized test passed10/10. Accumulated-machine repetitions failed different later phases. Earlier phase runners used mach clear (selection only), so completed WFI machines remained active. This is retained as multi-machine scheduling stress, not mislabeled single-CPU isolation.

All CPU fixtures are synthetic Cortex-M programs with8MHz DWT and8MIPS timing, not native firmware or physical frequency evidence. They validate the request-emission side, not original firmware receiver ISR behavior. Global quantum reduction is an explicit timing-resolution experiment, not a production change, clock adjustment, relaxed tolerance or calibrated fix.

The matrix supports a scheduling-granularity interaction. GPIO synchronization alone is not a robust solution. Existing native PA3 edge captures must be analyzed before selecting a change. No tuning of learned baud, CRC data, IFCNT or delays is justified.

## Failure evidence

matrix/summary.json contains per-phase actual edge artifacts, final model learned sync span, observed first sync edges and per-byte start intervals. Final learned span may reflect reacquisition after a failed request, and is explicitly distinguished from initial sync span. Byte starts are matched to the known synthetic request grid within12.5us; this matching is analysis only, not a receiver tolerance. Raw traces remain authoritative.

For example, autobaud/MMIO-sync at10us phase6 observed a91500ns four-bit sync span and byte-start intervals250000/241625/258375ns, then rejected the frame. At1us the corresponding run succeeded without changing protocol checks.

A console PASS token was split by asynchronous logger output in one ideal test; the runner now writes structured assertion counts to a file, avoiding an unreliable text count. CPU matrix parsing removes complete timestamped logger records, then demands exactly six reported values per phase; original logs are retained.

## Reproduction

run_cpu_tests.py accepts RESULT_DIRECTORY, TMC_MODEL=fixed|autobaud, SYNC_GPIO=0|1, GLOBAL_QUANTUM=0.00001|0.000001 and REMOVE_MACHINES=1 for single-machine-at-a-time. Use an external75s process-group timeout. run_tests.py uses RESULT_DIRECTORY/GLOBAL_QUANTUM and an external90s timeout. analyze_edges.py and analyze_matrix.py inspect existing artifacts only. Each Renode subprocess also has an internal timeout.
