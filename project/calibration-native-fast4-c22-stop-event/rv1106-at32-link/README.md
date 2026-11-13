# RV1106 QEMU ↔ AT32 Renode UART

Start with [CURRENT.md](CURRENT.md) for the latest tested combined profile and
[THERMISTOR-VALIDATION.md](THERMISTOR-VALIDATION.md) for the completed fault tests.

A working **byte-transport integration**, with a separately verified original
application/main-MCU identification experiment documented in
[REAL-APPLICATION.md](REAL-APPLICATION.md). Full product functionality is not
established. It connects the existing custom RV1106
QEMU machine to the AT32 Renode model through a private local pseudo-terminal.
No TCP listener, external service, root privileges, or physical hardware needed.

## Layout and requirements

Keep these directories beside each other:

```
rv1106-at32-link/
rv1106-qemu/         # supplied QEMU machine and executable
at32-renode/         # supplied platform/peripheral sources
at32-runtime/       # Renode 1.17 portable, installed separately
```

Linux host, Python 3, functioning `/dev/ptmx` and `/dev/pts`, and the runtime
requirements of both emulator packages. Tested with included Linux x86_64 QEMU
and Renode 1.17.0 portable .NET. This is not a Windows-native transport.
Install Renode using `at32-renode/tests/setup-runtime.sh` if needed.
Use `--qemu`, `--renode`, `--model` for non-default runtime paths.

## Reproduce the proof

```
python3 rv1106-at32-link/firmware/make_test.py
python3 rv1106-at32-link/scripts/run_link.py --test
python3 rv1106-at32-link/tests/run.py
```

The independent test firmware runs **actual ARM instructions in both emulators**:

1. RV1106 ARMv7 sends every byte 0x00 through 0xFF, one request at a time.
2. AT32 Cortex-M reads USART1, XORs the byte with 0x5A, and transmits it back.
3. RV1106 checks every response and prints the success marker on its separate
   UART2 debug console only after 256 correct round trips.
4. The integration suite repeats the full exchange twice, then changes the MCU
   transformation to 0x5B and requires a failure. An echoed or prewritten success
   string is therefore not the test mechanism.

`test-results/` contains Renode and QEMU logs plus the raw debug console. Both
processes are stopped and the PTY is removed at completion, timeout, failure,
or Ctrl-C. Generated test binaries are fully reproducible without an ARM toolchain.
They are **not** derived from or substitutes for product application firmware.

## Load your own firmware

Example (host UART selection is an assumption, see below):

```
python3 rv1106-at32-link/scripts/run_link.py \
  --rv-image /absolute/path/to/extracted/u-boot.bin \
  --mcu-image /absolute/path/to/mcu_firmware_v1.3.3_20260311.bin \
  --mcu-base 0x08004000 \
  --rv-uart 1 --mcu-uart usart1 \
  --timeout 60 --log-dir ./link-observation
```

No `--test` for real firmware. A normal observation ends after the requested
number of **host seconds** and saves logs. Completion of that interval is **not**
a protocol success assertion. MCU SP and PC are read from the first two vector
words in the supplied raw image. MCU firmware paths currently must not contain
whitespace. RV image handling is the QEMU board's existing raw/ELF loader; this
wrapper does not add Linux boot, a device tree, storage, or product peripherals.

`--rv-uart` chooses 0–5. `--mcu-uart` chooses usart1/2/3/6 or uart4/5/7/8.
The defaults (RV UART1 and AT32 USART1) are the **synthetic test wiring**, not
proven physical wiring of the user's device. Production MCU firmware was observed
transmitting on USART1. The host UART wired to it has not been established.

## Backend mapping

RV1106 board serial order is deliberately not UART numeric order:

| QEMU `-serial` ordinal | RV1106 UART | Physical MMIO |
|---|---|---|
| first (backend 0) | UART2, debug console | 0xFF4C0000 |
| second (backend 1) | UART0 | 0xFF4A0000 |
| third (backend 2) | UART1 | 0xFF4B0000 |
| fourth (backend 3) | UART3 | 0xFF4D0000 |
| fifth (backend 4) | UART4 | 0xFF4E0000 |
| sixth (backend 5) | UART5 | 0xFF4F0000 |

The launcher reserves UART2 for `console.bin` unless UART2 itself is selected
as the link, and attaches null backends to unused intervening UARTs. If UART2
is the link, there is no separate debug console capture.

## Manual connection / other host serial endpoints

In Renode, after loading the AT32 platform:

```
emulation CreateUartPtyTerminal "rv_link" "/tmp/private-directory/uart"
connector Connect sysbus.usart1 rv_link
```

In QEMU, for a link on UART1 and console on UART2:

```
-chardev serial,id=mcu,path=/tmp/private-directory/uart \
-serial stdio -serial null -serial chardev:mcu
```

The PTY path is a host serial endpoint. The same QEMU serial chardev can be
pointed at an explicitly authorized physical serial device instead, but this
kit has only tested the local Renode PTY. Do not run both an external terminal
and QEMU against the same endpoint. Keep it in a private directory. No socket
or network-exposure configuration is required.

## Scope and limitations

- Functional byte exchange only: no electrical signaling, pin mux validation,
  cycle accuracy, RTS/CTS, baud mismatch, UART errors, or break timing proof.
- QEMU and Renode use independent clocks. This is **not deterministic co-simulation**.
- AT32 retains its hardware-like one-byte RX depth. Bursts can overrun if the
  firmware does not service data promptly. The test uses one outstanding request;
  it does not silently enlarge the FIFO or claim high-throughput reliability.
- Model UART transmit is instantaneous. The PTY does not enforce baud pacing.
- MCU is advanced 10 ms in virtual time to initialize, then both run freely.
  Startup ordering and application handshake behavior require separate validation.
- Initial production MCU transmission (`5b 75 ed 55 02 d0 a9`) is observed evidence,
  not a decoded packet schema or successful product handshake.
- The real MCU application starts at 0x08004000 behind an absent 16-KiB bootloader.
  Direct entry cannot recreate unspecified bootloader initialization.
- No claim of USB updater, motor control, or full product behavior. Original Linux
  userspace and native main-MCU identification are separately demonstrated by the
  eMMC integration and REAL-APPLICATION.md.

## Linux offline profile integration (experimental)

The launcher also accepts `--cpu cortex-a7,has_el3=off`, `--disk IMAGE`
(always attached with `snapshot=on`), and `--console-commands FILE`. It waits
for `RV1106_OFFLINE_USERSPACE_READY` before writing explicitly supplied commands
to the guest debug-console shell. It does not run vendor startup by itself.
Use a generated Linux boot ELF from the separate eMMC integration project.

Direction captures are raw bytes: `rv-tx.bin` is host UART output and
`mcu-tx.bin` is AT32 output. These prove transmitted bytes, not acceptance at
the far end. The AT32 capture includes startup before Linux has opened its port.
The independent all-byte test verifies both captures contain exactly 256 bytes.

Runtime evidence from original `avata_main` configuration selects `/dev/ttyS3`
at 576000 baud, 8 data bits, no parity, one stop bit. Therefore real-application
experiments explicitly use `--rv-uart 3 --mcu-uart usart1`. The reduced Linux DT
must enable UART3; the older UART2-only DT cannot provide `/dev/ttyS3`. This is
application configuration evidence, not independently verified physical wiring.

Optional `--pace-rv-byte 0.001` inserts at least 1 ms of host-wall-clock delay
between host-to-MCU bytes using a second private PTY. This diagnostic prevents
instantaneous host bursts, without enlarging MCU receive registers. It is not
576000-baud timing and does not synchronize emulator clocks. MCU-to-host traffic
remains unpaced. A bounded 1 MiB relay queue fails explicitly rather than silently
losing data. Leave this option off for the direct transport test.
