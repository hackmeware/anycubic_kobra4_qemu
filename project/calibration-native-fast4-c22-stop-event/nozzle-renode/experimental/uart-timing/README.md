# Passive TMC UART timing evidence

Isolated diagnostic files only. The production TMC, GPIO, firmware, baud, reply contents, CRC checks and guards are unchanged. No current native run is modified.

The observer connects as an additional sink to PA3, retains up to 200,000 resolved line transitions and markers, and exports them only when explicitly requested. It reads GPIO mode/latch and existing TMC counters/last messages. It never writes GPIO, calls SyncTime, drives a signal, reads firmware RAM or creates periodic events. Its eventless counter timestamps the available machine clock; the additional machine elapsed timestamp is also recorded. These are not guaranteed CPU-instruction timestamps when CPU time has not yet been synchronized. GPIO mode distinguishes request-driving versus input/reply phases, not electrical driver contention. Dropped counts must be inspected before interpreting a trace as complete.

Optional future native setup, after virtual-tmc2209.resc:
include @experimental/uart-timing/passive-observer.resc

At final paused diagnostics:
sysbus.tmcTimingObserver Mark "final"
sysbus.tmcTimingObserver WriteCsv "/absolute/path/tmc-edges.csv"
sysbus.tmcTimingObserver Dropped

## Tests performed

- Existing production model used without alteration.
- Ten ideal 40kbaud request start phases, 0–9us across the 10us quantum: every request and eight-byte reply passed independent GPIO waveform decoding and CRC.
- Forty negative cases across those phases: request CRC corruption, wrong slave address, invalid stop bit and disconnected device. All were rejected/no reply as expected.
- Ten synthetic Cortex-M fixtures, not original firmware, emit GPIO requests paced by an 8MHz DWT at 8 MIPS. CPU completion RAM markers prove execution. All ten requests were accepted with no device rejection. Offline decoding of actual reply GPIO edges produced 05 ff 02 00 00 00 00 4c with correct start/stop bits and CRC in every case.
- Synthetic CPU fixtures deliberately test the CPU-to-device request side, not the original firmware receiver, ISR-latency compensation, native response unpacking or realistic interrupt load. The 8 MIPS fixture is not a physical frequency claim or a change to native MCU settings.

Recorded CPU request-edge grid deviations reached 9.125us. Unsynchronized timestamp semantics mean these cannot alone be interpreted as CPU instruction jitter. Replies began around 187.5us after the nominal request end (range 179.625–191.250us across phase cases), consistent with the model starting its eight-bit delay at the final stop-bit midpoint. This is an observed boundary condition, not proof of a specification violation or a reason to tune turnaround.

These tests do NOT reproduce the native CRC failure or establish whether autobaud, GPIO synchronization, native ISR timing, or another cause is responsible. The next useful evidence is a separately authorized native run with this passive observer and unbuffered/final incoming serial captures, comparing actual outgoing reply edges with firmware-reported bytes. No reply repair or guard suppression is justified.

## Reproduction and artifacts

Run run_phase_tests.py, run_cpu_tests.py, then analyze_cpu_edges.py with an external 75s process-group timeout. Each Renode subprocess also has a 60s timeout. Evidence is under evidence/nozzle-uart-timing; CPU fixture hashes are recorded in cpu-phase-report.json. The initial synthetic CPU attempt failed only because a platform property used incorrect syntax; cpu-phase.log records the corrected successful run.
