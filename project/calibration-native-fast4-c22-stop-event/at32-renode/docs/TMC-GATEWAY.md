# Diagnostic motor/TMC gateway (opt-in)

This is a small **diagnostic substitute for the downstream motor controller**, not the supplied motor firmware and not a complete motor/driver simulation. It must never be described as original-firmware motor execution, physical printing, successful homing, or a validated printer-ready state. It is separate from work to execute the original motor binary.

## Verified transport evidence

Main MCU image v1.3.3 SHA256 `9bd702c8a076f29c0ac019cc7c8ea6c7afa52d13580fea04e977e3dce0a5d517` forwards TMC requests through **USART2**, peripheral `0x40004400`, IRQ38. Startup configures **PA2 TX and PA3 RX**; see `firmware-evidence/startup-usart2-pins.asm`. These are firmware GPIO assignments, not independently verified board wiring. There is no evidence of direct main-MCU bit-banged TMC UART on the candidate endstop pins.

Actual native-session capture `rv1106-at32-link/test-results/tmc-uart-probe/usart2.bin` begins:

```
7e 00 08 05 02 f5 03 02 25 e7 14
```

- Main→motor format: `7e sequence command length payload crc16-low crc16-high`.
- Command8 payload: OID2, then `f5 03 02 25`.
- This is a valid TMC UART read for slave address3, register2 (IFCNT), CRC8 `25`.
- The capture contains ten IFCNT requests without a downstream reply before the native startup timeout. Periodic command0x10 carries four-byte clock values.
- Main's receive parser uses an **asymmetric** format: `7e command length payload crc16-low crc16-high`, without the sequence byte.
- Main registers command9 at `0x08005078` to handler `0x0800aafc`, which forwards the first payload byte as OID and the remaining bytes as the host TMC response.
- Command0x12 handler `0x0800b424` consumes acknowledged host sequence + status0. This acknowledges transport queue reception, not movement completion.

The first run with symmetric response framing still timed out; it is preserved as `tmc-gateway-initial`. This failure is not a successful TMC integration claim.

## Scope and limitations

`VirtualMotorTmcGateway` subscribes only to USART2 TX and returns bytes through the existing one-byte-deep hardware UART, paced at 10/576000 virtual seconds. It does not modify native application code, firmware, protection thresholds, or clock estimators.

Supported behavior:

- Outer CRC16 and inner TMC CRC8 validation.
- Three independently addressed virtual TMC register banks (addresses1–3), matching the original motor handler’s accepted range.
- Register write/readback, 8-bit IFCNT increment and wrap, GSTAT write-one-to-clear.
- Exact captured original motor register-table defaults, including IOIN=0 and GSTAT=0; no fabricated hardware identity or standstill flag.
- Transport acknowledgment only for accepted register operations and observed clock updates.
- Invalid CRC, unknown register, unsupported command, and injected disconnection do not return invented success. Unsupported motion/homing requests remain unanswered.

The model is not a complete TMC datasheet implementation. Current scaling, physical phase/velocity, chopper dynamics, motor feedback, endstops and motion are absent. Readback proves only the diagnostic register bank, not the actual motor MCU or external driver silicon. Zero stationary phase/load values are illustrative. Register defaults come from the original motor firmware’s initialized table, recorded in `firmware-evidence/motor-register-defaults.json`. They are vendor gateway values, not measured external TMC2209 silicon state. Three logical bank addresses are1–3; the original firmware maps them to motor indices1,2,0.

Fault controls:

```
sysbus.tmcGateway Disconnected true
sysbus.tmcGateway CorruptTmcReplyCrc true
sysbus.tmcGateway DriverFaultStatus 2
```

DriverFaultStatus is ORed into DRV_STATUS, never masked. External fault settings survive reset, while register state and queued UART replies reset. GPIO/thermal native protection remains independent.

## Running and tests

After loading the AT32 platform, explicitly include `scripts/virtual-tmc-gateway.resc`. It is never included by the normal platform/load scripts or combined launcher.

Run `python3 tests/run-tmc-gateway.py` from this package or give its full path. The assertions run the actual C# peripheral inside Renode, not a separate Python reimplementation. They test captured IFCNT request, checksums, readback, per-slave isolation, IFCNT wrap, GSTAT semantics, fault injection, reset persistence and refusal of unsupported motion commands.

Native integration findings are recorded separately and must be consulted before claiming it clears any startup blocker.

The supplied original motor image has command8 handler `0x0800e11c`. It calls register-table processor `0x08012e34`; reads return eight bytes beginning `05 ff register`. For writes with no read result, handler `0x0800e15e` returns command9 with the entire original payload (OID plus original write datagram), using `%*s` at `0x0800e17c`. The gateway follows this controller-completion echo. This is not a UART response from physical TMC2209 silicon. The empty-write-response and no-write-response experiments did not work and are not promoted as supported behavior.

## Comparison with upstream Klipper (checked 2026-11-04)

Primary sources reviewed (moving `master`, not a pinned historical vendor source):

- https://github.com/Klipper3d/klipper/blob/master/klippy/extras/tmc_uart.py
- https://github.com/Klipper3d/klipper/blob/master/src/tmcuart.c
- https://github.com/Klipper3d/klipper/blob/master/klippy/extras/tmc2209.py
- https://github.com/Klipper3d/klipper/blob/master/klippy/extras/tmc2208.py

`tmc_uart.py` confirms CRC8-ATM with polynomial7, syncF5 requests, write-bit0x80, big-endian register values, and replies identified by sync05/addressFF. Its register writer verifies IFCNT advances by exactly one modulo256. Those semantics support this model's real register counter, rather than returning a constant fabricated success. Upstream adds UART start/stop bits in software, packing four request bytes into five and eight reply bytes into ten. That **does not match the captured vendor link**, which wraps raw four/eight-byte datagrams in USART2 gateway frames. Upstream's normal bit-bang rate is40kbaud; this is distinct from the576kbaud main-to-motor transport.

`src/tmcuart.c` implements GPIO-timed UART edges, switching single-wire direction and detecting receive timeout. It reports completion to the host even for write-only operations, and clears the receive length on timeout. The vendor motor-controller completion is different: it echoes the original request through command9. Consequently upstream's empty write-only completion cannot be transplanted unchanged to this vendor host. The gateway preserves the hardware UART's actual receive/overrun path; it does not claim GPIO-level TMC timing simulation.

`tmc2209.py` defines address range0–3,12MHz nominal driver clock, and TMC2209-specific SGTHRS/SG_RESULT/COOLCONF/TCOOLTHRS fields. Its IOIN mapping confirms ENN, MS1/MS2, DIAG and version fields. The motor firmware gateway accepts only1–3; this is a vendor-layer restriction, not a TMC2209 limit.

`tmc2208.py`, inherited by TMC2209, confirms the GCONF/GSTAT/IFCNT/IOIN/CHOPCONF/DRV_STATUS register numbers and status bit meanings. In particular DRV_STATUS bit1 is overtemperature and bit31 is standstill. These allow explicit fault injection without disabling the native host's status checks.

The gateway deliberately validates incoming CRC and withholds responses for malformed/unknown requests. The original motor register-table routine is more permissive and echoes some invalid requests; that is not copied as a successful transaction. GSTAT uses TMC-style write-one-to-clear for explicitly injected bits rather than the original callback’s blanket low-bit clear. These are documented diagnostic differences.

No Klipper source file has been copied into this MIT-licensed model package. The implementation was based on protocol behavior and supplied-firmware evidence; upstream files are linked for comparison and retain their GPLv3 licensing.


## Native integration result

`tmc-gateway-echo` completed36 reads and30 writes across the three main motion-driver banks with zero CRC rejects. It advanced native initialization through X/Y/Z. It then honestly stopped on missing extruder driver support (GCONF error11820) and unsupported motor command0x22 (ready-callback msgtag155). The native host printed a later `Printer is ready` log despite these faults; the UI remained in shutdown10111. This is **not** printer readiness or print execution. The `tmc-gateway-final` repetition with the exact extracted motor defaults independently confirmed the same result: 90 valid transport frames, 36 reads, 30 writes, zero CRC rejects and six refused command0x22 requests. X/Y/Z initialization advanced; extruder error11820 and ready-callback msgtag155 remained. The focused Renode test suite passed all27 checks against this final model.

The fallback is opt-in and remains distinct from original motor-MCU execution. Normal launch profiles are unchanged.

## Optional blank saved power-down record (experimental)

A separate `scripts/blank-powerdown-record.resc` enables `BlankPowerDownRecord` on the gateway. Default behavior remains to refuse motor command0x22. The opt-in returns the original command0x23 layout: three little-endian signed32-bit saved-position values, all zero for an explicitly synthetic blank persistence record. Evidence shows the original firmware loads these from `PowerDown_data`; this is not a generic TMC default or proof of current position/homing. The original setter0x24 and movement remain unsupported. See `experimental/powerdown-query/README.md` and its disassembly. All31 expanded Renode tests pass; native query integration is verified; the frozen V3 snapshot does not include this change.

## Optional original-image version metadata

`scripts/motor-image-version.resc` enables `EmulateFirmwareVersion`, defaultfalse. Original motor handler0x0800e198 returns response0x18 containing the first request byte (OID) followed by literal version bytes1,6,1. The diagnostic model can reproduce those bytes for compatibility with the supplied v1.6.01 image; this is not a claim that the original motor MCU is executing. Empty/malformed version requests remain rejected. `VersionQueries` counts replies. All34 expanded Renode checks pass; native follow-through is verified in `tmc-version-nozzle`: one version response, two saved-record queries, all four register-init paths complete, and host/UI protocol reports `state:ready`. The displayed UI still raises CODE10002 while runtime motor-status command0x25 remains unanswered. Host-ready is not full UI readiness or print capability. No motion or homing behavior is implied by either metadata query.

Late repeat `tmc-version-late` confirms UI10002 is the failed CheckXYZConnectionLineStatus RPC after native msgtag151 timeout, caused by the unanswered runtime motor-status query0x25. The model deliberately does not substitute fault-free zero status. See `experimental/powerdown-query/motor-status-evidence.asm`.
