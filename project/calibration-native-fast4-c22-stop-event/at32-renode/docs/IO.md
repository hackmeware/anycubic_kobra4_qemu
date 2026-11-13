# IO and DMA model behavior

## GPIO, IOMUX and EXINT

`AT32GPIO` models CFGLR/CFGHR, IDT/ODT, SCR/CLR (set wins over clear), WPR locking and HDRV readback. Reset configuration defaults to 0x44444444; constructor reset overrides are available for board-specific debug pins. `OnGPIO(pin, level)` supplies external drive; `ReleasePin(pin)` removes it. Pull-up/down inputs use ODT to choose pull direction. Open-drain high is released and reads the external level; this is digital logic, not electrical simulation.

Pass `iomux` and `portIndex` (A=0 through E=4) to GPIO constructors to route resolved pin levels. `AT32IOMUX` numbered outputs 0..15 select one source port per EXINT pin. It also accepts direct inputs `portIndex*16+pin`. Its non-EXINT remap registers retain configuration but warn because peripheral alternate-function wiring is not simulated.

`AT32EXINT` inputs and numbered IRQ outputs use line indices. Connect lines 0..4 individually, and use `IRQ5_9` and `IRQ10_15` for grouped NVIC vectors. Do not connect several individual outputs to one NVIC input without combining them. It supports rising/falling detection, software triggers, interrupt/event enables, pending/W1C and an `Event` pulse output. AT32F403A line19 is reserved; `hasEthernetWakeup=true` is an optional 407-style extension. Event output is not automatically connected to Cortex-M wake logic.

## USART

`AT32UART` exposes `IRQ`, `RxDMA`, `TxDMA`, the standard Renode UART byte backend and live `BaudRate = Frequency / BAUDR`. Update `Frequency` when APB changes; APB timer doubling does not apply to USART.

The hardware has a single unread receive-data register. Default `receiveFifoDepth=1` preserves the first byte and raises overrun if another arrives before it is read. A larger depth is an explicit emulator convenience, not hardware FIFO behavior. Status/data read sequences clear receive errors. TX completes synchronously, not at baud-rate timing. `SignalIdle()` and `InjectReceiveError(mask)` provide deterministic testbench stimuli; automatic idle timing is not implemented.

USART alternate-function pins, 9-bit transfer, silent mode, LIN, IRDA, smartcard, synchronous mode and electrical RTS/CTS behavior are not simulated. Their configuration warns. Byte and halfword bus access translations are available.

## DMA

`AT32DMA` has seven channels per instance. Explicit channel-override request inputs are **1..7**; numbered IRQ outputs are **0..6**. Peripheral source inputs are **100 + source ID** from RM table 9-5. Set constructor `secondController=true` on DMA2. Fixed mapping implements tables 9-3/9-4 by ORing independent source states; flexible mode (SRC_SEL1 bit24) selects each channel's source from its SRC_SEL0/SRC_SEL1 byte. A mapping change observes already-asserted source levels. Channel overrides remain ORed with mapped sources for testbench use. Transfers use element counts, independent peripheral/memory byte/halfword/word widths, and independent address increments. Narrow sources are zero-extended; narrow destinations truncate. Memory-to-memory starts on enable and runs synchronously. Peripheral transfers service asserted request levels. Reentrant request changes from UART/SPI/I2C are observed during transfer.

Completion leaves EN latched until software disables the channel. Disabling permits updating count/address/control. Half/full/error flags generate IRQs according to channel interrupt-enable bits; CLR supports individual or global W1C. Circular transfer reloads count and addresses after a block. A continuously high circular request is capped at one block per service invocation to avoid an infinite synchronous loop; another request invocation resumes it. There is no cycle timing, arbitration or priority contention.

Reserved widths and unaligned addresses set TE and clear EN. Bus exceptions are caught and converted to TE. Renode's ordinary unmapped reads may return zero rather than throwing, so unmapped-bus detection is not guaranteed. Peripheral outputs must be wired to the source inputs of both DMA instances. Firmware must choose the same fixed/flexible mode on both DMA controllers, as required by the RM; instances do not enforce that global consistency rule. Timer requests remain unavailable unless an appropriately DMA-enable-gated timer output is connected. DMA2 channels6/7 have no fixed peripheral sources but work with flexible routing. Memory-to-memory circular mode is invalid and its circular bit is ignored with a warning.

## Reproducible checks

From any directory, run `python3 tests/run-io.py --renode /path/to/renode` or `python3 tests/run-dma.py --renode /path/to/renode`. The scripts run packaged `.resc`/`.repl` fixtures and C# assertions, isolate runtime configuration in a temporary directory, and fail when the success marker is absent. Neither test runs guest firmware.

### DMA source input IDs

Use input `100+ID`: ADC1=1, ADC3=3, DAC1/2=5/6; SPI1 RX/TX=9/10, SPI2=11/12, SPI3=13/14, SPI4=15/16; I2S2EXT=17/18, I2S3EXT=19/20; USART1 RX/TX=25/26, USART2=27/28, USART3=29/30, UART4=31/32, UART5=33/34, USART6=35/36, UART7=37/38, UART8=39/40; I2C1 RX/TX=41/42, I2C2=43/44, I2C3=45/46; SDIO1=49, SDIO2=50. Timer IDs follow RM table 9-5. Reserved source numbers should never be driven.
