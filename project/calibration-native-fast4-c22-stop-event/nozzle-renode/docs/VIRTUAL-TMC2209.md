# External nozzle TMC2209 UART model (diagnostic)

Load `scripts/virtual-tmc2209.resc` after the nozzle platform, before firmware runs.
It attaches an external 40,000 baud 8N1 half-duplex device to PA3. No MCU firmware,
host application, CRC check, timeout or safety instruction is modified.

## Wiring evidence

The supplied nozzle v1.2.9 native host capture in
`rv1106-at32-link/test-results/tmc-gateway-final/rv-nozzle-tx.bin` contains decoded
config command `33 00 03 00 03 8e08`: OID 0, RX pin 3, no pull, TX pin 3, bit time 1800.
Configuration routine 0x080074f0 corroborates these fields (see `tmcuart-config.asm`).
An independent existing SRAM capture from `test-results/nozzle-adc-probe/nozzle-sram.bin`
confirms OID 0 object at 0x20000628: TX GPIO 0x40010800/mask 8 at offsets 0x0c/0x10,
RX GPIO 0x40010800/mask 8 at 0x14/0x18, bit time 0x708 at 0x20. This is PA3 in both
directions and 1800 ticks at the observed 72 MHz clock, or 40 kbaud.

Packed UART command payload `ea034820e4` decodes (start+8LSB+stop) to
`f5 00 02 c8`, an IFCNT read at slave 0. GCONF writes decode to
`f5 00 80 00 00 01 c4 ef`. Device CRC8 accepts the low-nibble 5 sync form.

## Behavior and limits

The model samples MCU GPIO edges at bit centers and drives GPIO input waveform
responses. Valid addressed writes update registers and increment the 8-bit IFCNT;
silicon writes produce no reply. Reads use master address 0xff, big-endian value,
and CRC8. GSTAT uses write-one-to-clear reset flags. Unknown/read-only writes and
unknown reads are rejected, rather than fabricated. Bad CRC and wrong addresses
produce no response. Response start is delayed 8 bit times plus configured
SENDDELAY; the electrical driver is released after reply stop.

Monitor fault inputs: `Disconnected`, `CorruptReplyCrc`, `DriverFaultStatus`, and
`InjectGeneralStatus`. Fault inputs survive peripheral reset. Driver status faults
remain visible in DRV_STATUS and GSTAT. Diagnostic counters `Reads`, `Writes`,
`RejectedFrames`, `ReceivedBytes`, `LastRequest`, `LastReply` expose actual traffic.

This is a bounded functional UART/register device, not a motor or thermal plant.
No movement, current, stallguard, homing, temperature, IOIN electrical pins,
analog baud auto-detection or electrical collision fidelity is claimed. DRV_STATUS
reports standstill because no motion plant is attached. Readable configuration
registers are retained; dynamic measurement registers are illustrative zeros.
The physical nozzle MCU SKU remains provisional.

## Validation

`python3 tests/run-tmc.py` executes 16 C# assertions in Renode, including version,
GCONF readback, IFCNT and wrap, GSTAT W1C, invalid address/CRC/register rejection,
read-only protection, disconnect, corrupted replies and preserved driver faults.
A timed PA3 GPIO test additionally sends the captured IFCNT request at 40 kbaud,
checks all four decoded request bytes, samples all eight returned UART bytes,
and verifies their CRC and stop bits. Evidence: `tests/verified/tmc-unit.log`.
Native application startup remains a separate validation requirement before
enabling this component in a release profile.

### Original-firmware register initialization

Native combined evidence is in sibling
`rv1106-at32-link/test-results/tmc-powerdown-nozzle/` (2026-11-04).
The original nozzle firmware exchanges 128 UART bytes with this GPIO device:
12 reads, 10 writes, zero rejected frames. Last request `F5-00-6A-AA` receives
`05-FF-6A-00-00-00-00-35`. The prior extruder GCONF error 11820 is absent; startup
advances through bed-level configuration and `powerloss_step 0 0 0`.

The combined session still stops in the ready callback: host msgtag 146 times
out after the separate motor gateway rejects unsupported command 0x17. Native
shutdown 10111 / MCU error 17 is retained. This proves nozzle register transport
and initialization, not printer readiness, homing, movement or a completed print.
Fault injection was verified in the device tests, not in this native session.
