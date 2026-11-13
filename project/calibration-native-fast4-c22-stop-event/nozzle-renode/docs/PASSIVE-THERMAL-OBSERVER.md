# Passive PB8/PB9 and thermal observation

For a **next** run, include `scripts/passive-nozzle-thermal-observer.resc` after
the nozzle platform and its existing thermal fixture are loaded. The optional
peripheral name is `passiveNozzleThermalObserver`. No launcher default, current
run, firmware, thermal model, ADC setting or heater/fan binding is changed.

This observer attaches only GPIO receiver sinks to PB8 and PB9. Each actual level
transition is recorded; snapshots are explicitly distinguished from edges.
Every 100 ms it also records GPIO levels, configuration nibbles and output latches,
physical model temperature, the published ADC code, selected curve, injected
sensor-fault state, curve-range diagnostic, model overtemperature/latch flags,
last modeled heater/fan duty and thermal update count. No property is written.

The `model_*` flags belong to the simulated thermal plant. They are **not** the
original firmware/host guard state. The ADC column is the plant's published ADC
input, not an assertion about a firmware sampling result or Celsius report.
Preserve native console/protocol evidence separately for accepted commands,
interpreted temperature, target updates, shutdowns and actual file completion.

Times are nozzle Renode microseconds elapsed since observer creation. Do not
subtract them from Linux/host timestamps or call the clocks synchronized. GPIO
callbacks from one multi-bit port write are delivered in pin order and may share
a timestamp; each row reflects that callback's point in the GPIO update.

## Next native target35 trace

Keep all actuator inputs disconnected. Load the observer before native startup,
alongside the already selected recovered sensor. Use the verified normal `ExtruderPreheating` RPC with target 35°C, then target
0°C, when the coordinating worker permits it. See
`evidence/extruder-preheating-schema/README.md`. The native passive control path
is now recorded in `evidence/native-nozzle-control-trace/README.md`. This
document does not execute a request.
Markers are observations, not proof that a native command was accepted.

In the nozzle machine's monitor context:

    sysbus.passiveNozzleThermalObserver Mark "BEFORE_NATIVE_NOZZLE35"
    sysbus.passiveNozzleThermalObserver WriteCsv @/chosen/path/nozzle35.csv

After actual native completion/error, mark and export again. Use a fresh path or
intentionally update the same trace. `WriteCsv` also writes `.status.json` beside
the CSV. Check `dropped_rows==0` before claiming complete edge coverage. The
default buffer has 100000 rows; overflow is explicit and never overwrites older
evidence. `Clear` resets only observation storage/counters, never device state or
the observation clock. The observer's `Reset` only adds a reset marker.

The next trace can establish whether native target35 produces PB8 demand and
PB9 fan activity. Because both signals remain unconnected to the thermal plant,
it cannot establish closed-loop heating or successful temperature control.
Do not infer heater failure from the intentionally unchanged model temperature.
Do not infer command execution from RPC acceptance alone. Preserve native guards
and report any rejection/shutdown rather than bypassing it.

## Small actual C# test

Run `tests/run-passive-nozzle-thermal-observer.sh`. It loads the actual optional
setup and profile in a CPU-free Renode machine, using an isolated HOME. It changes
only synthetic GPIO output registers: no heater/fan connection, temperature
injection, sensor-fault injection or direct thermal drive is used.

Checks cover actual edge timestamps, unchanged-output suppression, simultaneous
observer sinks, GPIO config/latch values, periodic snapshots, physical/ADC/guard
invariance, marker escaping, observer-only reset/clear, bounded capacity and CSV
status metadata. Logs and example CSVs are in
`tests/results/passive-nozzle-thermal-observer/`. These synthetic GPIO traces must
not be represented as native PB8 activation evidence.

## Optional live streaming

Streaming is disabled by default. After loading the observer, while paused:

```text
sysbus.passiveNozzleThermalObserver Start @/chosen/fresh/path/nozzle-live.csv
sysbus.passiveNozzleThermalObserver WriteStreamStatus @/chosen/path/nozzle-live.status.json
```

The parent directory must exist and the CSV must not exist. `Start` uses
`FileMode.CreateNew` and permits concurrent readers. It flushes the header, then
an actual current-state `snapshot:stream_started` row. It does not replay old
buffered rows. Each subsequent real edge, periodic sample or explicit marker is
flushed immediately, so physical temperature, ADC and native PWM can be read
while the run is ongoing. It never calls SyncTime, writes device state or
changes the thermal timer.

`Streaming`, `StreamRowsWritten`, `StreamDroppedRows`, `StreamCapacityReached`,
`StreamErrorCount`, `LastStreamError` and `StreamWriteOutcomeUncertain` are
readable monitor properties. `WriteStreamStatus` writes their current values
alongside the ordinary observer counters. The sidecar is an explicit snapshot,
not an automatically refreshed file. Use a distinct CSV/status path.

At completion:

```text
sysbus.passiveNozzleThermalObserver Stop
sysbus.passiveNozzleThermalObserver WriteStreamStatus @/chosen/path/nozzle-live.status.json
sysbus.passiveNozzleThermalObserver WriteCsv @/chosen/path/nozzle-final-buffer.csv
```

`WriteCsv` must not target the streaming CSV, even after Stop. It exports the
bounded in-memory buffer separately and includes streaming status in its
`.status.json`. Start/Stop/streaming do not clear that buffer. Buffer `Clear`
does not reset streaming counters or bypass the streaming capacity. Observer
Reset adds its existing marker and keeps a running stream; it does not reset
physical state. Dispose closes only the file.

Streaming and memory each obey `maximumRows` independently (default 100000).
At the streaming limit the file closes, `StreamCapacityReached` becomes true,
and subsequent uncaptured events increment `StreamDroppedRows` until explicit
Stop. No older streamed row is overwritten. Stop intentionally excludes later
events, so they are not counted as drops. Call Stop before starting a new fresh
file; a successful Start begins new per-stream counters, while the observation
clock and memory remain unchanged.

Explicit Start failures throw and record I/O errors. Errors during streaming
callbacks are logged, recorded and close the writer without throwing into
firmware execution or changing a device. Only rows whose write and flush
succeeded count as written. A failed write increments dropped rows and marks
its outcome uncertain because a partial write may have reached disk. Do not
treat a partial row or missing stream as a safe heater state. The run owner
must use independent native target-zero/guard evidence if observation fails.

The observer's `actuator_connection_created: false` describes this component,
not the whole machine. If the optional PB8 binding is loaded, record its
`WriteStatus` output as well. PB9 remains observed but unbound in that profile.

`tests/run-passive-nozzle-streaming.sh` passes 35 actual C# checks plus CSV/JSON
validation for flush visibility, fresh-file rejection, bounded output, errors,
uncertainty, lifecycle and unchanged physical/ADC/GPIO/guard state. A test-only
reflection operation disposes the actual writer to exercise the I/O-failure
path; it cannot be invoked through the production observer API. The original
37-check passive test and 40-check GPIO heater-binding test also pass. No
firmware or full native run is started by these tests.
