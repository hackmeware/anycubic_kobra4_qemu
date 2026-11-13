# Validation results

## Environment

Executed on Debian GNU/Linux 13 x86_64 using official Renode 1.17.0,
build `1.17.0+20260907gitf1dd1b4af`, bundled .NET 8.0.12.
The portable distribution and Python virtual environment were installed in the
workspace without root privileges. Upstream `tests/example.robot` also passed.

## Full-platform smoke suite: 13 / 13 passed

`tests/smoke.robot` runs the complete AT32 platform, not a mock of its C# classes.

1. ARM Cortex-M boot from a vector table, execute Thumb instructions, transmit
   `AT32 RENODE BOOT OK` through USART1, and write an SRAM completion marker.
2. Flash alias at reset address zero.
3. SRAM word retention and byte updates.
4. GPIO output data, atomic set/reset, and clear register.
5. DMA1 channel1 copies two 32-bit elements, decrements count, sets completion,
   and clears flags.
6. CRM oscillator ready flags and PLL source status.
7. Flash unlock and explicit programming-error response for unimplemented writes.
8. GPIO edge propagation through IOMUX and EXINT to NVIC pending IRQ6.
9. Supplied ADC channel conversion, result, and end-of-conversion clearing.
10. SRAM bit-band set/read/clear aliasing.
11. DWT cycle-counter advancement with virtual time.
12. Timer3 update interrupt and NVIC pending IRQ29.
13. Optional 224 KiB SRAM overlay, including the final SRAM word and its bit-band alias.

The generated 372-byte smoke binary is reproducible without an ARM toolchain:
`python3 firmware/make_smoke.py`. Its Thumb instructions and literal pool are
explicitly documented in the generator. It is test firmware, not a replacement
for the user's application.

Run `tests/setup-runtime.sh` once, then `tests/run-all.sh` for the complete
aggregate, or `tests/run.sh` for the platform smoke suite. Existing Renode installs
can be selected with `RENODE_TEST`, `RENODE_HOME` and `RENODE_RUNTIME`.
The runner gives each process a unique temporary directory, avoiding collisions
when separate containers expose the same process IDs to a shared filesystem.

## Additional suites: all passed

The final aggregate also executed 4 RTC/watchdog/DAC Robot cases and 3 timer-adapter
Robot cases: **20 generic Robot cases total**, plus **162 C# assertions** executed
inside Renode (IO 39, DMA 35, SPI/I2C/CRC bus 37, CRM/ADC system 51).
The separate uploaded-application test below is a 21st Robot case. See the
component documents for exact limits of those fixtures. The recorded command was
`tests/run-all.sh /absolute/path/to/mcu_firmware_v1.3.3_20260311.bin`.

## Uploaded application: bounded boot test passed

Input: `mcu_firmware_v1.3.3_20260311.bin`, 39,681 bytes.
SHA-256: `9bd702c8a076f29c0ac019cc7c8ea6c7afa52d13580fea04e977e3dce0a5d517`.
The input firmware is not included in the generic model package.

- Loaded at `0x08004000`, with vector-table offset set to that address.
- Initial SP: `0x20008000`; initial reset PC: `0x08008099`.
- Ran for **one second of emulated time**, not one second measured on real hardware.
- Final PC: `0x08004f2c`, inside the supplied image and outside its default handler.
- VTOR: `0x08004000`.
- DWT cycle count: `0x026242d8` (39,994,072).
- CFSR and HFSR: zero.
- USART1 output: seven binary bytes, `5b 75 ed 55 02 d0 a9`.
- USART2 produced no bytes in this interval.
- No unmapped peripheral accesses were logged in the final run. One expected
  IOMUX warning states that alternate-function/electrical routing is not modeled.

Reproduce using:
`tests/run-user-firmware.sh /absolute/path/to/mcu_firmware_v1.3.3_20260311.bin`.
This sets the application entry point directly and therefore **bypasses the
missing bootloader**. It is not evidence of the full board's reset/upgrade path.

## Interpretation and limits

These tests establish executable CPU boot, selected register semantics and
interrupt routing, plus bounded progress of this particular application image.
They do **not** establish full firmware correctness, real-time/cycle accuracy,
complete peripheral coverage, external board-device behavior, hardware pin
multiplexing, USB/CAN/SDIO/XMC support, bootloader behavior, or flash update
correctness. A stable in-image PC is not by itself proof of healthy application
behavior. No real hardware comparison or application protocol exchange was made.
The binary UART output has been captured but not assigned a protocol meaning.

Machine-readable evidence is in `tests/verified/platform-smoke.xml` and
`tests/verified/user-firmware.xml`; the final application log and captured UART
bytes are alongside them. Reports may contain paths from the test environment.

## Virtual-printer extension (0.2.0)

Purely virtual additional components, no discovered physical board mappings:

- `tests/run-thermal.sh`: 29 analytic/ADC/fault/reset assertions, real Renode timer progression, and25% GPIO PWM averaging.
- `tests/run-mechanics.sh`:25 axis/step/direction/enable/endstop/stall/reset/digital-switch assertions.
- Isolated sandbox: heater25°C→34.5162581964°C after10virtual seconds at50%duty with illustrative40W/20J·K⁻¹/0.2W·K⁻¹ parameters; ADC3824. Unpowered bed remains25°C; one80steps/mm axis pulse changes10→10.0125mm.
- Read-only real-application startup probe: ADC1 CTRL1/CTRL2/OSQ1/2/3 all zero after1virtual second without host input. This does not establish actual sensor assignments.

These tests validate the simulation components, not an entire functional printer or real-heater safety. The new extension does not change the tested MCU core/platform; it is opt-in and disconnected from real MCU channels in the demonstration.
