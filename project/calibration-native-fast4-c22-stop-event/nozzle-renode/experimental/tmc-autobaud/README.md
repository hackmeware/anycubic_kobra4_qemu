# Isolated autobaud candidate: NOT integration-ready

Only new experimental files were created. Production TMC/GPIO/firmware, native clock settings, guards and active runs were not changed.

The candidate measures the four-bit sync interval from start falling edge through data-bit2-to3 falling edge. RX remaining sample times and TX bit boundaries use that measured interval with rational nanosecond rounding. It does not fit a baud rate to expected reply bytes. SENDDELAY uses the paired encoding 8*(value|1). The old stop-midpoint turnaround anchor and release behavior are intentionally retained: no authority was obtained for changing the sub-bit anchor. Existing CRC, address, stop, disconnect and register checks remain.

Direct ReceiveByte injection remains available for register unit tests; because no GPIO sync is present in that path, it retains the constructor's default timebase. Production-edge tests do not use that path for requests. The tests configure NODECONF with a valid direct write before sending actual GPIO requests.

## Evidence

- 72 ideal waveform cases pass: baud 20k/40k/50k/80k; phases0/3/9us; SENDDELAY0/1/2/3/14/15.
- 60 negative cases pass: corrupted CRC, wrong address, invalid stop, disconnected device and bad sync byte.
- Independent actual-edge analysis verifies reply framing, CRC and the delay table.
- Ten synthetic CPU/DWT-driven cases do NOT all pass. Nine accepted requests; phase7 produced zero reads and one rejected frame. The fixed-baud baseline accepted all ten. Integration is blocked.

For failing phase7, the recorded first/fourth sync edges are135125ns and237875ns: measured four-bit span102750ns, implied bit period25687.5ns. The second byte starts at390000ns and the next at632000ns. The learned stop sample would occur at634031.25ns, after the next start. Available clock timestamps are unsynchronized with CPU instruction execution; the observer and candidate never call SyncTime. Changing device event deadlines also changes CPU synchronization opportunities, so timestamps alone cannot establish the physical waveform that silicon would see. Do not clamp the learned rate or relax stop/CRC checks to hide this failure.

This isolates a meaningful interaction between adaptive timing and the existing CPU/GPIO timing model. It does not establish that a hardware-accurate autobaud implementation alone fixes native failures. Native passive-edge evidence and a justified synchronization model are required first.

## Reproduction

Run run_tests.py under an external90s process-group timeout, then analyze_edges.py. Run run_cpu_tests.py under an external75s timeout and analyze_cpu_edges.py. The final CPU analysis intentionally exits nonzero and writes a structured failed report. All tests are synthetic, with no native firmware writes, physical hardware or calibration claim.

Evidence: evidence/tmc-autobaud. No optional production launcher integration is provided while the CPU regression fails. Existing errors/timeouts/glitch recovery and high-impedance release fidelity remain broader model limitations.
