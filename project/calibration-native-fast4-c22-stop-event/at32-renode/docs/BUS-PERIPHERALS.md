# SPI, I2C and CRC implementation notes

`peripherals/AT32F403A_Bus.cs` dynamically compiles in Renode 1.17.0. Register layout and masks are based on Artery's AT32F403A/407/407A reference manual Rev 2.06, chapters 10, 11 and 13, and the official AT32F403A/407 firmware headers. No external source code is included in this file.

## Implemented behavior

- **AT32SPI**: Renode `ISPIPeripheral` child registration; enabled master transactions; 8/16-bit frame serialization; MSB/LSB byte order; receive-data and transmit-empty flags; receive overrun; DT then STS overrun clearing; receive/transmit/error interrupt gating; DMA request outputs; programmable SPI frame CRC accumulation; documented configuration registers and reset values. Unconnected MISO reads `0xFF`, not loopback. Disabling an enabled controller finishes the child transaction.
- **AT32I2C**: Renode `II2CPeripheral` children at 7/10-bit addresses; master START, address, transmit, receive, repeated START and STOP; accumulated writes delivered at repeated START/STOP; one/two-byte receive buffering controlled by ACK/POS; retained final receive bytes after STOP; address-status clearing through STS1 then STS2; missing-slave ACKFAIL and write-zero error clearing; separate event/error IRQs and DMA request outputs. Software reset clears the controller state.
- **AT32CRC**: reset values, independent common byte, programmable initial value and polynomial, 32/16/8/7-bit polynomial widths, 8/16/32-bit DT accesses, input bit reversal by byte/halfword/word and word-wise output reversal. RESET loads the programmable initial value without resetting the common byte or configuration.

Attach real board devices in REPL, for example `sensor: I2C.BME280 @ i2c1 0x76` or a supported SPI memory under `spi1`. SPI board-level chip select must be connected/configured as required by the chosen slave. The test echo and memory devices under `tests/` are deliberately synthetic and are never loaded by the production platform.

## Fidelity limits

Transfers complete synchronously. Baud/prescaler and bus timing configuration is readable/writable but does not create wire timing, real busy windows, arbitration, clock stretching or analog behavior. Peripheral clock/reset wiring depends on the board/platform system model; these classes do not themselves subscribe to CRM gates.

SPI external-clock slave operation, I2S audio, hardware chip-select waveforms, multimaster errors and CRC-next automatic frame generation/comparison are not implemented. SPI CRC accumulation is available, but do not use this model to validate a CRC-appended SPI protocol. Byte-level Renode SPI devices exchange logical bytes; bit order only affects ordering of the two bytes in a 16-bit frame. Receive-only automatic clocking without a data write is not implemented.

I2C slave mode, general-call matching, SMBus/PEC, bus electrical faults, timing-sensitive ACK/STOP races, DMA-last-byte handling and per-byte slave NACK are not implemented. `II2CPeripheral` does not expose a per-byte ACK response. Writes are grouped until STOP/repeated START to respect Renode child transaction semantics. Read buffering may prefetch two bytes when ACK/POS is enabled; side-effectful slave reads and uncommon ACK sequences need board-specific testing. START/address clearing is functionally permissive on DT writes rather than requiring every prescribed status-read sequence. Software reset discards an in-progress buffered transaction.

DMA request GPIOs expose availability; they do not on their own implement a DMA controller or connect channels. Never infer full peripheral support merely from successful register reads.

## Validation

Run `tests/run-bus.sh` with the workspace runtime, or set `RENODE` to a compatible Renode launcher. It uses `BusPeripheralTests.cs` and `bus.repl` and requires an explicit pass marker, because monitor errors can still return shell exit status zero.

37 assertions execute inside Renode, covering five independent standard CRC check vectors (CRC-32/MPEG-2, reflected CRC-32, CRC-16/CCITT-FALSE, CRC-8 and CRC-7/MMC), SPI child round trips/16-bit frames/IRQ/overrun, I2C child writes/repeated START/receive-after-STOP/NACK/error IRQ, and a 10-bit addressed receive transaction. These are functional register tests, not proof of electrical, cycle or complete driver compatibility.
