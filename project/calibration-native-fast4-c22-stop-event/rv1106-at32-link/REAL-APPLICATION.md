# Original Linux application ↔ original MCU firmware

## Verified result

The original `avata_main` from the user's K4_1.2.1.3 software bundle runs under
the original Linux 5.10.160 kernel in the offline eMMC profile and successfully
identifies the main MCU in Renode as **v1.3.3**.

This is a real application handshake, beyond the independent synthetic UART
transport test. It is **not** full printer readiness. Next, the native
application attempts `/dev/ttyS0` for another MCU, which is absent in this setup.
The emulator also explicitly rejects the main MCU's flash programming/erase
requests with PRGMERR; the purpose of those operations has not been established. No claim of flash persistence or operational printing.

The supplied MCU binary is SHA256
`9bd702c8a076f29c0ac019cc7c8ea6c7afa52d13580fea04e977e3dce0a5d517`.
It matches the main MCU payload in the same original host software bundle.

## Reproduction

Keep the eMMC Linux project, UART integration, QEMU, AT32 model and Renode
runtime beside each other. The Linux project must contain the UART3-enabled
reduced diagnostic DT and generated boot ELF.

```
DISK=/path/to/kobra4-offline-gpt.img \
MCU_IMAGE=/path/to/mcu_firmware_v1.3.3_20260311.bin \
rv1106-at32-link/scripts/run_native_main.sh \
  --pace-rv-byte 0.005 \
  --mcu-final-commands rv1106-at32-link/tests/mcu-final.commands \
  --log-dir ./native-main-run
```

The link exists **before Linux boots**. No late device bind or descriptor swap.
The offline PID1 shell starts the application only after its readiness marker;
original vendor rcS/S90/S91 startup is not run. Partitions containing original
app and OEM files are mounted read-only, scratch paths use guest tmpfs, and the
raw disk is attached with QEMU `snapshot=on`. No emulated network adapter.

Native runtime configuration names `/dev/ttyS3`, 576000, 8N1. QEMU UART3 is
connected to AT32 USART1. In the guest, native main's descriptor 168 resolves to
`/dev/ttyS3`. This experiment does not prove physical pin wiring or baud timing.

**Pacing is essential to the verified result:** direct PTY and 1 ms host-byte
pacing timed out; 5 ms diagnostic host-byte pacing allowed identification. The
RX register remains depth one. This workaround gives Renode time to service each
byte despite independently running emulators. It is not actual 576000-baud
throughput, cycle accuracy, or synchronized co-simulation.

## Successful evidence

`test-results/native-main-paced5ms/console.bin`:

```
[1970-01-01 00:00:14.205] [info] [1121] MCU 'mcu' version: "v1.3.3"
```

MCU transmitted 2534 bytes in that observation. A second fresh run reproduced
identification at guest 14.772 s, with 872 host bytes and 2519 MCU bytes.
The later Linux platform may enable UART0 as well, but enabling a UART alone
does not supply the missing nozzle MCU; the recorded runs predate that change. The final Renode snapshot showed
USART1 status 0xC0 (no RX data/overrun pending), CTRL1 0x202C, CTRL3 0, CPU PC
0x08004F2C, CPU not halted, NVIC IRQ37/38 enabled, no pending IRQs in that bank.
These are final snapshots, not proof that no transient overruns ever occurred.

## Wire format and exact frames

Captured traffic has Klipper-compatible length/sequence/CRC framing under a
vendor byte wrapper. It is **not plain Klipper bytes throughout**. In the
successful run, XOR each raw byte with 0x78 and rotate right one bit to obtain
these frames. The wrapper value changes between negotiations.

Host identify request at capture offset 34:

```
raw:     68 58 7a 78 28 c4 47 84
decoded: 08 10 01 00 28 5e 9f 7e
```

Length 8, sequence 0x10, identify request command 1, offset 0, count 40;
CRC16 0x5E9F matches. Corresponding MCU identify data at capture offset 22:

```
raw: 185a7878289efca0f86b3564e047626b0a37ae9553a65b00f8ade0ec629f3b05237d5ac9fbe8307dc38801f63b530684

decoded: 301100002873426c4089a60e4c9f0d8939a76bf6956f913c40ea4c4a0df3a1bead8211d8c1482482dd78bc47a1953f7e
```

Length 48, sequence 0x11, identify response command 0, offset 0, 40 data bytes;
CRC16 0x953F matches. Request/response matching here uses protocol fields and
stream order; raw captures do not contain per-byte timestamps. Guest log time
14.205 s identifies completion, not exact wire transmission time.

Earlier sequence-0x11 retries elicited the five-byte decoded frame
`05 10 9e 81 7e` before the host restarted at sequence 0x10. Startup bytes
`5b75ed5502d0a9` independently decode with XOR0x55/ROR1 to
`07 10 5c 00 ab c2 7e`, also CRC-valid. Two earlier unwrapped MCU packets
`0b105f33937c840b61da7e` and `0b105f339608867677e67e` have valid CRCs
0x61DA and 0x77E6. Those earlier packets alone did not establish a handshake.

`decode_frames.py` passively finds candidates using terminator, length,
sequence-prefix and CRC checks. It recovers a candidate wrapper byte independently
per frame, so it does not implement or fully describe the vendor negotiation.
Unmatched bytes remain uninterpreted. JSON frame lists accompany the successful
capture. Firmware/software command semantics and version confirmation come from
the native application's successful identification, not merely CRC coincidence.

## Second MCU: additional verified identification

The optional `--nozzle-image /path/to/nozzle_firmware_v1.2.9_20260120.bin`
starts a second independent Renode instance using sibling `nozzle-renode/` and
connects its USART1 to RV1106 UART0. Both links use the selected diagnostic
pacing. This platform is a provisional Cortex-M3/F1-compatible functional model;
the nozzle board's exact physical MCU has not been identified.

A native-main-only run (`test-results/native-dual-mcu/`) identified both original
firmwares: main **v1.3.3** at guest 15.646 s and nozzle **v1.2.9** at 20.103 s.
Final direction totals: main host/MCU 636/2431 bytes, nozzle host/MCU 879/2473 bytes.
Nozzle traffic is captured in `rv-nozzle-tx.bin` and `nozzle-tx.bin`.

This still does not reach printer-ready. Native logs then report substantial
clock-frequency mismatches, missing filament-hub/ACE configuration, Wi-Fi
initialization failure and a startup exception. The application itself tries
wpa_supplicant, but no emulated WLAN or Ethernet device is present. No external
network connectivity is supplied by this launcher.

## Display integration caveat

Paced guest console input defaults to 64-byte chunks, at least 10 ms between
chunks and 100 ms after each newline, preventing long scripted guest input from
being dumped in one burst. The main/UI command file can be passed explicitly.

`--screenshot /path/screen.ppm` uses the QEMU monitor over private FIFOs to stop
execution and dump the actual VOP DMA framebuffer. The display QEMU build lacks
`screendump`; the helper performs no synthetic UI rendering. This feature
requires the display-enabled QEMU and device tree. It saves PPM pixels plus
`display.json` and VOP registers. `--memory` must match the generated Linux ELF's
memory configuration; a larger value is a diagnostic configuration change, not
an assertion of physical RAM capacity.

The 64 MiB combined main+UI run exhibited memory pressure (about 25 MiB available
to Linux), no main-UART traffic during its observation and a black framebuffer.
Therefore the independently proven main/MCU and native-UI tests must not be
represented as a simultaneous successful full-system session.

## Combined 128 MiB diagnostic: simultaneous integration established

A separate generated Linux boot ELF under `rv1106-linux-display-128diag/` and
QEMU `--memory 128` overcome the 64 MiB test's memory pressure. This is an
explicit changed-RAM diagnostic, not a claim about the physical product's RAM.

`test-results/combined-128M/` proves, in the **same emulator session**:

- Original native main identifies main v1.3.3 and nozzle v1.2.9.
- Original native UI executes and renders actual pixels in the VOP DMA buffer.
- Captured 480×320 UI visibly says **“Unknown error occurred”** over startup.
- Clock mismatch warnings and a native host startup exception remain.

Therefore simultaneous host/display/two-MCU integration is demonstrated, but
functional printer readiness is not. No motion, heating, real peripherals,
correct clock synchronization, or completed printer initialization is claimed.

Reproduction:

```
DISK=/path/to/kobra4-offline-gpt.img \
MCU_IMAGE=/path/to/mcu_firmware_v1.3.3_20260311.bin \
NOZZLE_IMAGE=/path/to/nozzle_firmware_v1.2.9_20260120.bin \
rv1106-at32-link/scripts/run_combined.sh
```

Requires sibling `nozzle-renode/`, `rv1106-linux-display-128diag/`, and the
previously listed runtime/model directories. `run_combined.sh` runs a bounded
75-second observation then saves PPM pixels and stops all three emulators.
PNG evidence was losslessly converted from that PPM for inspection, not generated
or edited artwork. `summarize_run.py` produces a conservative JSON evidence report.

## Later transport correction: virtual-time UART wire

The current combined launcher uses `--virtual-baud 576000`, not the earlier
5 ms wall-clock workaround. The opt-in AT32VirtualSerialWire externally queues
host bytes and delivers one frame every 10/576000 virtual seconds (~17.361 µs).
The actual hardware UART receive register stays one byte deep. It is addressless,
reports queue overflow, and flushes its queue on reset. MCU TX remains immediate.
The two emulator time domains are still independent, not deterministic lockstep.

Boundary tests and the 256-byte instruction-executing round trip pass. Native
host subsequently initialized both MCUs (main 256 moves; nozzle 1024 moves),
with send/receive sequences aligned and zero invalid packets. A recorded run
had zero retransmissions; another had seven main retransmissions, so transport
is not described as universally lossless. Clock estimates improved to about
118.1 MHz / 120 MHz and 70.8 MHz / 72 MHz, with residual mismatch warnings.

The startup profile now reproduces original RW mounts inside the disposable
QEMU snapshot: p12 → /userdata, p13 → /app, p14 → /data. Original app files are
unchanged on the host disk. The native program creates /app/etc/last_print.cfg;
this removes the invalid read-only-filesystem precondition behind the earlier
"Failed to create file" startup exception. No factory identity is fabricated.

With default zero analog inputs, the firmware's real protection then stops on
nozzle ADC channel0/PA0 (OID10): eight-sample sum0 outside configured962–32593.
Native UI correctly displays extruder NTC error10124. An explicit illustrative
100k/B3950/4.7k virtual NTC at25C supplies raw3911 and clears that specific fault,
revealing the main bed NTC fault10123 next. Those environmental profiles do not
modify firmware limits, connect unverified heater pins, or establish calibrated
physical temperatures. Main ADC mapping and additional fault tests are being
recorded separately as that work progresses.

Current sensor/timebase evidence supersedes the earlier prototype faults above;
old captures are preserved to show the sequence of verified corrections.
