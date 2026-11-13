# Revision 4: serialized commands and accelerated functional test

This revision does not launch native emulation. Prior source archives and r1/r2/r3 captures remain unchanged. r3 reached physical78.412°C with PB8/duty high and last verified native73°C/target230°C, then stopped after external command echo corrupted status019. Its normal zero, heater-off and cooling were not verified. r3 is incomplete; it is not resumed, reset to ambient or treated as a successful regulation test.

## Console ownership and graceful stop

All controller RPCs and log reads share one pending-batch latch. No next console input is appended until the current RPC's exact complete end marker, transport result and strict payload validate, or the current log batch's unique end marker arrives. Initial console startup must complete before a request. Routine log reads have scheduling opportunities between requests, with a3-second virtual deadline; native observations retain their5-second freshness limit. An uncertain/invalid batch stops the virtual run without retry or target-clear claim.

ELF uploads remain separate input lines. The entire chmod/execution/timeout-result/raw-dump/completion-marker suffix is one final shell input line. Its echo therefore precedes execution, with no subsequent input while the result is printed. Each log batch is likewise one line. The strict octal/HTTP2/gRPC/protobuf parser is unchanged. Actual corrupted r3 status019 remains a negative regression fixture, not sanitized evidence.

Do not append commands directly to console-input.commands or issue a separate competing heater request. To request a graceful stop, publish the dedicated intent through:

```sh
python3 printer-shared-mcu/experimental/synthetic-calibration-thermal/native-controller/request_graceful_stop.py RUN_NAME \
  --reason 'User requested stopping this test'
```

The helper atomically publishes graceful-stop-request.json without replacing an existing intent. It does not itself send an RPC, create stop-request, or prove heater shutdown. Its exact schema is `{"action":"stop_heating","reason":"plain nonempty reason"}`. The controller permanently latches the request, checks it again immediately before a target append, drains a pending validated RPC/log batch, and then sends at most one normal target-zero. Before any heat command, the intent instead ends the run without heating. A pending uncertain target/status result is never retried or bypassed with another command.

Successful graceful stopping requires the normal zero response, a fresh subsequently queued native status showing target0, actual resolved heater GPIO low and duty0 for at least5 source-local seconds, subsequent cooling≥0.1°C, and complete final exports. No pre-zero rows are counted retrospectively. An unfinished final batch must drain before normal completion/export. User-requested early termination stays incomplete for test qualification even if the separate graceful-stop facts are verified.

## Explicit 4× functional mode

Only the original synthetic-calibration and explicit accelerated-functional-4x selections are accepted by this controller. The integrator's2× profile is a documented possible later fallback requiring a separate reviewed decision/invocation. There is no automatic fallback, repeated native attempt or retuning.

The4× selection changes only hypothetical thermal capacities, nozzle20→5J/K and bed600→150J/K. Powers60/200W, conductance0.2/1.5W/K, ambient25°C, ADC curves, update10ms, firmware/PID/smoothing/watchdogs, clocks and actual heater bindings remain unchanged. It is unrealistic functional testing, not real PID validation. The fixed selected scenario, explicit metadata and helper identities are validated and source-pinned.

The selected external functional criterion is **both physical and fresh native temperature within target±2°C, each sustained for5 virtual seconds in its own observed clock domain**, then normal zero/off/cooling. It is not merely arrival within220..240°C plus a5-second response window; that earlier proposal is superseded. The controller preserves criterion-crossing timestamps, durations and sample/row identities before cooling resets live band counters.

For4×, normal zero is requested by52 virtual seconds after target queue when a command boundary is available. The hard60-second cap is never extended if a pending batch/zero takes too long. The8-second margin does not guarantee time for both a full pending-request deadline and a full zero deadline. Physical abort caps remain250°C nozzle and75°C bed. Native guards are untouched. Failure to establish the criterion within these limits is negative/inconclusive and is preserved.

The original synthetic-calibration selection retains its separate30-second dual-band criterion, normal-zero lead232s and hard240s heat cap. Both modes retain5s heater-off,≥0.1°C cooling,30s cooling cap,360s absolute observation cap, source/fault/transport checks and separate heater invocations.

Accelerated results use functional_band_criterion_met and complete_functional_evidence. They never set regulation_criterion_met or complete_regulation_evidence. real_pid_validation, pid_calibration_completed and print_completed remain false. Independent GPIO/heat/ADC replay uses the fixed selected capacity without altering any captured data.

## Reviewed next invocation

From the snapshot root, parent-owned launch after checkpoint review (not executed here):

```sh
python3 printer-shared-mcu/experimental/synthetic-calibration-thermal/native-controller/controller.py native-nozzle-230-functional4x-r1 \
  --thermal-profile accelerated-functional-4x --heater nozzle --nozzle-tmc-model autobaud \
  --execute --seconds 10800 --cleanup-seconds 120
```

The3-hour wall budget is only an upper bound for slow emulation; it does not relax virtual caps. No concurrent heater or second emulator run. Bed remains a later separate invocation after nozzle review.

Tests are offline. Delayed scheduling and thermal values in controller tests are explicit mocks, not native evidence. Existing emitted ARM execution tests use an instruction interpreter with mocked syscalls, not Linux-native ARM/QEMU execution. No new native run or hardware/PID validation is claimed.

The snapshot ELF remains byte-identical (SHA25694bacb120ff6378771ab0ece268b69614406ca97058d9683e4317bc471701216) to the client that produced18 validated GetStatus snapshots in r3's emulated ARM/Linux guest. This is prior native-guest evidence for that unchanged client, not live validation of revision4 console scheduling or the accelerated fixture. Static emitted marker commands also include empty shell quotes, preventing a wrapped input echo from matching an exact standalone marker while leaving actual emitted marker text unchanged. The compound capture line is bounded to768 characters and checked with shell syntax-only tests.
