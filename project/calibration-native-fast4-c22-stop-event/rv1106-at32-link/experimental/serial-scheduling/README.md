# Prepared bounded serial scheduling experiment

DO NOT RUN while native-ready-autobaud is active. Parent must release test slot.

run_abba.sh NEW_DIRECTORY executes parallel/serial/serial/parallel with external60s timeout each. No production files changed. Identical three Cortex-M increment loops at explicit100MIPS, GPIO connector and UART hub probe,100us timer,1us quantum, exact100 coupled1ms steps, exact24 QEMU shift0. UART test is hub event ordering, not physical bit waveform. No native firmware. CPU counter must advance; every timer event and UART order recorded. Exact traces compared across modes, but a difference blocks equivalence, not automatically a bug. Underlying CPU scheduling can alter within-quantum delivery.

Same baseline synchronous QMP checks and Renode sender wrapper retained in both modes. Timed coordinator copied from earlier candidate only to record phase timings and terminate exactly at100steps; no batching selected. Actual clock bounds5ms lead/1ms lag unchanged. Output includes callbacks/stops, phase costs, GPIO/UART/timer timestamps and CPU counter files. Every process has cleanup and outside timeout.

Prepared Python syntax validation only so far. Renode model/API compilation and smoke must occur after slot release; no passing execution claim. A startup/build error stops ABBA, rather than skipping a failed case. Candidate source frozen before launch.
