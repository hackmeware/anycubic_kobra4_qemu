Current revision: **4**. See [CONTROL-SAFETY-V4.md](CONTROL-SAFETY-V4.md) for mandatory console ownership, the graceful-stop hook, explicit4× functional criteria and the next reviewed invocation. r3 is completed but incomplete as a qualification test; its zero/off/cooling were not verified. Earlier invocations below are historical and must not overwrite existing runs.

# Explicit native thermal step-response controller

Revision3 streaming correction (see STREAMING-STATUS.md). Revision2 startup-error review: the parent attempted r1, which stopped before every RPC/heat command on an already-known optional startup configuration error. That failed run is preserved. No native invocation was started by this package's author; revision3 is offline-tested only. The parent's preserved r2 reached native ready, then timed out on a misclassified streaming status request before any heater target. That unary assumption was a controller mistake. This is an isolated experiment using the separately reviewed `synthetic-calibration` thermal profile. It is not a native PID-calibration command, print runner, real-printer calibration or safety certificate.

## Exact permitted actions

Each new run sends one initial read-only `PrinterState`, a bounded read-only `GetStatus` baseline, exactly one normal target request, bounded sequential read-only two-message `GetStatus` snapshots, and at most one normal zero request. Each capture has unique markers and a five-guest-second client timeout. PrinterState and heater setters retain the unchanged strict unary stream-end transport. GetStatus uses a separate two-message streaming snapshot client, explicit local RST_STREAM(CANCEL), shutdown and close, with distinct exit20 and no claim of terminal RPC success. A capture timeout, malformed response, partial command append or missing transport outcome is never retried. Request bytes and executable client are archived before queuing.

- Nozzle: `/applink.AppLinkService/ExtruderPreheating`, field1 omitted/defaultfalse, uint32 Celsius field2.230°C canonical bytes `10 e6 01`; zero is empty.
- Bed: `/applink.AppLinkService/HotbedPreheating`, same scalar shape.60°C canonical bytes `10 3c`; zero is empty.
- Read-only temperatures: `/applink.AppLinkService/GetStatus`, empty request, SERVER-STREAMING. Each snapshot captures exactly two messages and always selects message2 by sequence, retaining both, without filtering for desired temperatures. Response field1→GetStatus; nested fields2/3→Extruder/HeaterBed; scalar fields1/2→current/target signed int32. Native code rounds its double temperatures to whole degrees. These are actual native interpreted values, not an inversion of the physical model's ADC.
- `PrintInfo` is metadata and is not used for temperatures.

`schema-heaters/` contains the newly recovered bed setter/parser/serializer evidence. Nozzle evidence remains `evidence/extruder-preheating-schema/`. `schema-temperature/` contains source hashes, original disassembly, mapping proof and strict decoder tests. All use original host ELF SHA256 `5ab198028c4b64a5f8a77ca41fb74f074070b0681cb68ace3ff29b7209953c06`.

The production `make_grpc_probe.py` diagnostic0..35°C restriction is untouched. This module has no arbitrary G-code, arbitrary target, factory bypass, homing or PID override interface. There are no temperature/duty/ADC writes. All generated packets connect only to guest loopback127.0.0.1:50051.

## Bounded procedure

1. Require a new run directory and explicit profile/heater/TMC arguments. No environment thermal, alternate binary, geometry or clock override is inherited. The wrapper uses the original clocks, explicit1µs scheduling quantum, fresh paused profile setup and original firmware/PID/guards.
2. Verify the generated profile and TMC manifest. Require native readiness, an exact complete ready `PrinterState`, fresh physical25°C observations, actual low heater pads/zero integrated duty, initial4023/3911 ADC codes and native temperatures near25°C with both targets0. No motion is needed. Native baseline settling is capped at3 successfully canceled snapshots or10 controller-virtual seconds after ready; default-zero readings never become an ambient baseline. Any uncertain transport still stops immediately.
3. Send the selected normal target once. Preserve RPC acceptance, GetStatus native target, physical heat, actual PB8/PA0, ADC and native interpreted temperature as separate facts.
4. At most one read-only status request is pending. New snapshots are scheduled no faster than1s controller-virtual cadence and only after the prior one closes; each includes two native stream messages, normally about1s apart. Physical observer time remains source-local; the controller never subtracts guest log timestamps from Renode/host time. Physical and native target±2°C windows each need30s of consecutive fresh samples to satisfy the report criterion. Native samples are integer-rounded; this is not sub-degree verification or continuous internal-firmware tracing.
5. Request normal zero on a native fault, sensor/model fault, stale telemetry, recorded physical250°C nozzle/75°C bed, or completion of the report criterion. Normal zero is also scheduled conservatively at232s after target queue, reserving up to8s for the bounded transport. If zero is not confirmed by240s after queue, stop the virtual run. Queue time is earlier than actual native acceptance, so the hard cap is no later than240s after acceptance. This is an external experimental stop, not a changed firmware watchdog. No-rise can only be a negative result, never an excuse to retune or extend the cap.
6. Require zero's complete native RPC response, separately observed native target0, actual GPIO low and integrated duty0 for at least5 source-local seconds, and at least0.1°C subsequent physical cooling. Cooling observation is capped at30 controller-virtual seconds. Native regulation, target clearing, actual output-off and cooling are separately reported. Failure to see any fact stays unverified.
7. A transport, console truncation, source/monitor or clock uncertainty stops the virtual run and preserves evidence. It does not claim the target was cleared. Signal escalation affects only the controller's new owned process group after bounded graceful export. A hot plant is never reset to ambient. The exact historical complete absent-video-service error is exempted. Five separately source/capture-verified auxiliary messages are classified only before original native readiness, with exact full text, severity and source-log identifier. Every startup error is retained separately. Unknown, changed, corrupted, TMC, thermal and shutdown errors remain blocking; historical timestamps are not blanket-discarded.
8. Final success additionally requires explicit zero-loss/zero-error stopped stream status, row-count agreement, actual final low binding states, reviewed source hashes unchanged, and independent replay of actual GPIO duty through the unchanged thermal equation plus ADC conversion checks. A missing/incomplete final export prevents complete-evidence status.

The run manifest exposes `regulation_criterion_met`, `zero_response_verified`, `native_zero_target_observed`, `actual_heater_off_observed`, `physical_cooling_observed`, and `complete_regulation_evidence`. `pid_calibration_completed` and `print_completed` always remainfalse.

## Invocations

From the snapshot root, generate requests only, without launching anything:

```sh
python3 printer-shared-mcu/experimental/synthetic-calibration-thermal/native-controller/controller.py prepare-nozzle-230 \
  --thermal-profile synthetic-calibration --heater nozzle --nozzle-tmc-model autobaud
```

A subsequent reviewed native nozzle test, **not run during preparation**:

```sh
python3 printer-shared-mcu/experimental/synthetic-calibration-thermal/native-controller/controller.py native-nozzle-230-synthetic-r3 \
  --thermal-profile synthetic-calibration --heater nozzle --nozzle-tmc-model autobaud \
  --execute --seconds 28800 --cleanup-seconds 120
```

Only after reviewing nozzle results, a distinct bed run:

```sh
python3 printer-shared-mcu/experimental/synthetic-calibration-thermal/native-controller/controller.py native-bed-60-synthetic-r1 \
  --thermal-profile synthetic-calibration --heater bed --nozzle-tmc-model autobaud \
  --execute --seconds 28800 --cleanup-seconds 120
```

Heaters are never intentionally heated together.8h is a wall cap, allowing approximately74wall seconds per virtual second. Hard heat cap remains240virtual seconds, absolute observation cap360virtual seconds, cooling30virtual seconds, stalled controller-clock wall cap300s. Cleanup120s plus bounded5s TERM/5s KILL waits is separate. Do not treat the wall cap as permission to extend any virtual limit.

Results: `runs/<name>/thermal-observation.json`, exact `thermal-*.elf`, `.protobuf.bin`, `.http2.bin`, `.commands`, console and original logs; automatic `nozzle-thermal-live.csv`, `bed-thermal-live.csv`, corresponding final status/binding JSON, original final MCU SRAM and shared source/profile manifests. Exit0 means the report criterion and required clearing/cooling/evidence checks passed. Exit2 is negative or incomplete, never authorization for an automatic repeat.

## Offline tests and limitations

```sh
python3 -m unittest discover -s printer-shared-mcu/experimental/synthetic-calibration-thermal/native-controller -p test_controller.py -v
python3 -m unittest discover -s printer-shared-mcu/experimental/synthetic-calibration-thermal/native-controller/schema-temperature -p test_temperature_schema.py -v
```

Tests never launch a native printer emulator. The streaming tests execute emitted ARM ELF bytes in the existing instruction interpreter with mocked Linux syscalls, not a Linux/QEMU process or real socket. They cover exact restricted request encodings, captured native ready/low-temperature heater responses, strict transport failure/truncation, GetStatus decoding, actual historical GPIO-to-heat/ADC replay, sustained-band accounting, separate off/cooling evidence, no-rise/time caps, sensor/native faults, and mocked complete controller nozzle/bed/shutdown/uncertain-response flows. Mocked thermal values are explicitly synthetic test vectors, not new firmware results.

Physical constants remain hypothetical. PB9 heat-break fan is observed and intentionally thermally unbound. Bed B3950/4700Ω divider remains an existing unverified assumption. Original heat-up watchdog compatibility is not established. Native high-temperature GetStatus behavior and performance are statically prepared but not live-validated. Passing stable regulation would not complete native PID calibration, full sensor-fault/warm-reset qualification, ACE/filament modeling or a print.

## Revision2 startup evidence and preservation

The original `native-controller-source-checkpoint.tar.gz` and its SHA256 `09d0acd2142f79fd65f9a719088e34e93f9429875de713dc008ff485f469be5d` are unchanged. Revision2 uses a new versioned checkpoint/archive/manifest, never overwrites the prior archive or failed run, and changes no central launcher, model, firmware, PID, native setting or transport setup.

`startup-error-review/source-evidence.json` and `.asm` verify the original five logging templates and their local normal-return/cleanup paths. Dynamic path/ENOENT arguments are corroborated by six captured startup histories in `captured-startups.json`. These paths do not prove global benignity; independent native readiness and fresh physical/native/ADC baselines remain mandatory.

Exact startup-only candidates:
- Source218: `Unable to read config file /app/etc/avata_main_mutable.cfg`.
- Source123: `filament hub config file open failed: No such file or directory`.
- Source360: `Unable to open config file /app/etc/ace_list.json`.
- Source58: the exact failed `wpa_supplicant` command shown in the evidence, including interface/config path.
- Source36: `wifi init failed`.

The three clean autobaud readiness histories each contain these five and reach native ready. The longer XYZ console additionally has three corrupted command-echo/error concatenations, while older fixed-model runs have genuine TMC verification errors. Neither class is exempted. No prefix-based cleanup or generic error suppression was added. Console echo isolation remains a distinct possible future transport improvement, not part of this change. The known auxiliary failures do not establish ACE/filament or Wi-Fi availability.

Tests add complete five-error startup followed by normal nozzle/bed flow, unknown startup blocked before all RPC, exact severity/source/path/text matching, post-ready errors rejected, delayed readiness revoking a mistaken startup classification, historical successful startup replay, and older guards/corruptions still rejected.

Revision3 source/report/checkpoint: STREAMING-STATUS.md, checkpoint-v3-streaming.json, SHA256SUMS-v3-streaming, and native-controller-source-checkpoint-v3-streaming.tar.gz. Prior archives and raw r1/r2 remain preserved.
