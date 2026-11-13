# Current full snapshot and 24-hour example

## Scope
This distribution includes host runtimes and model/source code, not Anycubic firmware, private disks, real OTP data, credentials or bulk run logs. Import your authorized K4_1.2.1.3 SWU as described in README. This is a private development snapshot, not a finalized public release or proof of authentic hardware/update behavior.

## Start a fresh offline calibration instance
Run from the extracted Kobra4-Emulator directory:

```sh
python3 verify.py
python3 prepare.py --swu "$HOME/Downloads/K4_1.2.1.3.swu" --output ../kobra-private/import1 --tools-root /
python3 -B start.py --inputs ../kobra-private/import1/prepared/inputs \
  --output ../kobra-private/calibration-run1 \
  --instance ../kobra-private/calibration-instance1 \
  --profile r9-calibration --network off --ui \
  --host-runtime-profile no-history-autosave \
  --synthetic-thermal-rate 4 \
  --virtual-limit-seconds 86400 --seconds 86400 --execute
```

New output/import directories are mandatory. Use a new instance for changed profiles; do not reuse existing baseline PID state. UI interaction is manual through the locally announced VNC endpoint; this command does not automatically click the wizard or calibration. Do not add `--stop-when-ui-observed`, which would terminate early. `--seconds` is the host observation window; the virtual bound is separate and absolute. Startup/cleanup can add wall time, and faults/resource limits can stop earlier. This is not a promise that 24 virtual hours or complete calibration will be reached in 24 wall hours. Ctrl-C targets the owned process tree only. Existing persistence safeguards and recovery rules remain active.

## Host runtime optimization (opt-in)
The bundled AntShell.dll remains original. Selecting no-history-autosave creates a per-run full runtime copy and applies one exact SHA256/offset/byte-pinned 5-byte host IL patch. Unknown input hashes fail closed. Full runtime hashes and the only changed DLL are recorded in HOST-RUNTIME-MANIFEST.json and bound into instance compatibility. Automatic rewriting of the entire console history is disabled; in-memory history and command execution remain. Existing Renode logs remain and monitor command send intentions are retained in append-only monitor-commands.jsonl. An intent is not proof of command success. No firmware, clocks, sensor model or QEMU instruction budget is changed. Omit the flag for original behavior.

## Synthetic thermal rate 4 (opt-in)
This reduces hypothetical thermal capacitance by four for both heating and cooling. It does not quadruple CPU speed or merely change heater wattage. Default rate is 1. Its resulting PID values are not transferable to physical hardware.

## Verified and not verified
- CPU-free actual RunFor/GetTime/epoch acknowledgement parity passed.
- Sequential actual-firmware comparison: 999 equal 1-ms lockstep slices, same inputs/models/clocks/rate4/shift0, 350,000 preloaded inert history entries. Coordinator wall time 204.966 s original versus 103.731 s candidate, measured 1.976x. Single order and concurrent host workload: not a general performance guarantee.
- All clock boundary samples match except wall time; final private disk hashes match. Sensor contract passes both, but last_source_ns differs by 370 ns. Cause remains open; complete sensor bit-parity is NOT claimed.
- The parent reports the completed 4-hour thermal-rate4 run finished extruder PID. Bed PID and complete calibration are NOT completed/proven. That long run did not use this new host runtime option. The current 24-hour run is separate and was not altered for this snapshot.
- Native UI has booted in earlier R9 runs; this newly packaged combination has not completed calibration. Short fixed-work comparison does not prove UI/PID success.
- UI currently requires network off. Existing headless SLIRP modes remain available, without TUN/TAP; see README/network docs. This release does not claim native UI plus Internet works together. No cloud test is included.
- Full real-printer behavior, update/downgrade equivalence, physical safety, video and final print completion are not established.

## Distribution verification
FILE-MANIFEST.json covers every regular delivered file except itself. ZIP CRC and all archive member SHA256/length checks were verified at packaging. Linux executable modes are stored in ZIP attributes; use an extractor preserving Unix permissions. No Git setup required. Keep private imports, state, credentials and logs outside this directory.
