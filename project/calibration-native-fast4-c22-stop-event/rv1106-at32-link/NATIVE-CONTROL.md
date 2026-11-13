# Native local control and diagnostic print workflow

The original native host exposes an insecure local-only gRPC service at guest
127.0.0.1:50051. No QEMU external NIC or port forwarding is added. The small
ARM Linux probe invokes this actual service using HTTP2 over guest loopback.
It does not replace the service or synthesize firmware responses.

Verified original serialization:
- `/applink.AppLinkService/RunGcodeScript`: field1 string `script`.
- `/applink.AppLinkService/StartPrint`: field1 string `file_path`, field2 string
  `file_name`; optional booleans3–7 remain false in this test.
- RunGcodeScriptResponse field1 contains ErrorMessage; its field1 is numeric
  error and field2 message. Empty successful payload plus grpc-status 0 was
  actually observed, not assumed from an open connection.

`make_grpc_probe.py` creates a tiny ARM ELF and shell transfer commands without
changing original disk or application files. Its default script is M115/M105.
The `--method StartPrint` mode defaults to directory `/data/gcodes` and file
`diagnostic.gcode`. This mode is intended for the explicit diagnostic test,
not unrestricted remote control. The probe captures raw response bytes using
the existing BusyBox tools; `parse_grpc_capture.py` extracts HTTP2/gRPC frames.

The runner's optional `--console-input` reads complete appended lines from a
local file after startup commands. It allows controlled follow-on guest
commands during one session, still using the paced UART console. It is not a
network service or a new external listener.

## Verified diagnostic workflow

`test-results/three-mcu-native-control` contains the native execution evidence.
All three original MCU images run, with the explicit generic motor electrical
plant, thermistor fixtures and GPIO-level virtual nozzle TMC2209.

1. M115/M105 via RunGcodeScript returned actual grpc-status 0 and an empty
   successful protobuf response.
2. The guest created this 23-byte file on its snapshot-backed filesystem:

   M115
   M105
   G4 P100
   M400

3. Native StartPrint accepted `/data/gcodes` + `diagnostic.gcode`, then logged
   SDCARD_PRINT_FILE, successful file loading and parsing, PRINT_PRINTING,
   Finished print file, state:complete and PRINT_COMPLETE.
4. Original UI received state:complete, about 0.405seconds, filament_used 0.
   The original completion path reset both heater targets to 0.

This verifies the real application file-execution/completion path. It does
NOT verify homing, movement, extrusion, heater response, a sliced model or a
physical-print simulation. It deliberately includes no motion or heat command.
Future ordinary sliced files can trigger native preparation workflows and
must not be described as bounded no-motion simply because optional flags are
false. Main clock estimates showed a transient large mismatch under this
workload; deterministic timing remains unproven.

## Staged heater and guard probes

`test-results/three-mcu-heater-trace` uses passive GPIO observers, while both
thermistors remain independent fixed-temperature fixtures. Native StartPrint
executed bed-only `M140 S35 / G4 P3000 / M140 S0 / M400` and nozzle-only
`M104 S35 / G4 P3000 / M104 S0 / M400`. Actual native target changes and file
completion are recorded. CSVs retain each MCU's independent virtual timestamp
and explicit phase marks; do not merge clocks as if synchronized.

The next file `G91 / G1 X1 F60 / M400` hit the unchanged native “Must home axis
first” guard, error 10901. A separate `M83 / G1 E1 F60 / M400` file stopped
before extrusion at “Filament type not set”. It therefore does NOT test the
cold-extrusion minimum-temperature guard. Neither probe bypasses homing,
filament configuration or thermal checks.

RunGcodeScript's successful RPC alone remains insufficient proof of command
execution; the staged tests deliberately use the separately verified real
StartPrint/file-execution path.
