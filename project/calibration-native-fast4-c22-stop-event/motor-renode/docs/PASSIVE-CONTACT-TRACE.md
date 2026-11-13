# Optional passive contact transition trace

Disabled by default. This observes the generic assumed electromechanical model, not physical-printer wiring or calibrated position. No geometry signal is connected to DIAG.

After loading the plant and configuring the fixed contact fixture, before running:

```
mach set "motor"
sysbus.electromechanicalPlant StartContactTrace "/absolute/new/contact-transitions.csv" 100000 true
```

The path must not exist. The maximum row count is 1..1,000,000. The boolean selects immediate per-row flush for live readers; false buffers until stop/disposal. Three initial rows snapshot cached physical state without integrating. Each later row observes a zero↔nonzero contact-reaction torque change after an already-existing positive-dt integration call. No new integration, clock synchronization, firmware/GPIO access, or physical update is initiated by logging. Start/stop do not advance state. Exceptions during writing stop logging and set ContactLastError, without propagating into the physical calculation.

At finalization:

```
sysbus.electromechanicalPlant StopContactTrace
sysbus.electromechanicalPlant ContactRowsWritten
sysbus.electromechanicalPlant ContactDroppedRows
sysbus.electromechanicalPlant ContactLastError
sysbus.electromechanicalPlant IntegrationCalls
```

Rows include observation time, previous integration time, state time, axis, initial/transition kind, nonzero flag, physical angle, velocity, relative travel, and contact-reaction torque. Dates/times are motor-local shared virtual seconds. ContactRowsWritten counts initial rows too. Once bounded capacity is reached, later transition rows are dropped and counted; physics continues normally. Check zero drops and empty LastError before claiming a complete boundary-level record. Dispose closes the stream; reset preserves the stream and physical state, following existing plant reset behavior.

## Interpretation limits

A transition row records contact present at the end of the existing integration interval, not an analytically exact continuous-time crossing. It bounds an observed zero-to-nonzero onset between previous_integration_time_s and state_time_s, assuming unchanged fixture parameters. Internal RK substeps are not logged; enter/leave entirely within one interval can still be missed. No added integration steps are justified by observation needs. Compare the interval with actual motor PB5/PB4 edge time; if its upper endpoint precedes DIAG, contact was observed before DIAG. If the interval overlaps the edge, retain that uncertainty. Initial rows can contain stale state_time_s relative to observation time, explicitly recorded.

Read-only GetContactTorqueNewtonMeters(axis) and GetLastIntegrationTimeSeconds(axis) also support future edge-side snapshots without advancing the plant.

## Lightweight invariance test

PassiveContactTraceTests uses a halted-CPU synthetic model, 80 existing 100us time intervals, real normal plant sampling, a small compliant contact region, and load reversal. The enabled, disabled and three-row-capacity runs must produce byte-identical physical CSV, exactly 240 axis integrations each, and correct contact enter/leave/reenter records. Start, stop and same-time callbacks are checked not to integrate. Reproduction scripts and logs are in evidence/passive-contact-trace; verify with tests/verify_contact_trace.py. These are synthetic observer tests, not a firmware homing replay.
