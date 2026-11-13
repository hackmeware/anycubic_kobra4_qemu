# Shared virtual-time printer MCU experiment

`python3 tools/generate.py` creates isolated C# namespaces for main, nozzle and motor from the current source trees. It does not change instructions, registers, parameters or original firmware. `generated/manifest.json` records every original and generated file hash. Generated paths are absolute to the selected output directory; regenerate after relocation or source changes.

`generated/shared-load.resc` boots the three platform definitions in one Renode emulation, named `main`, `nozzle`, `motor`. It loads the explicit main24MHz oscillator and motor24MHz/RTC/generic stationary-RL hypotheses. Main USART2 and motor USART2 connect through a Renode UART hub and separate virtual576000baud receive wires. The real main GPIOA8 output connects through Renode's GPIO connector to motor TMR2 channel1 capture input0. This is supported by the original timestamp/edge/send code and receiver capture handler; physical FCES package identity/mux remains unconfirmed.

No main/nozzle thermistor, heater, TMC, mechanical or host UART overlays are automatic. The launcher owns those explicit options. Load user-provided binaries at their established offsets and create host UART1 PTYs after selecting the corresponding machine. Core bootstrap returns with `main` selected. Use generated copies of all board-specific overlays to avoid mixing namespace types.

Tests: `python3 tests/run-wires.py` checks actual CPU-driven GPIO capture and serial byte transport. Original three supplied firmwares were also run together for1 virtual second: CFSR zero for all, motor low status halfwords zero. This did not include native-host configuration or motion. The original boot log records its tested source snapshot; do not mistake the test for complete printer readiness.

Performance remains a limitation: observed three-core original startup took roughly21 wall seconds per1 virtual second under the measured workload. Shared MCU time removes independent-MCU drift, but does not synchronize QEMU's guest clock with Renode. The host integration must measure and address that honestly, without modifying firmware clock/fault checks.

## Required sub-frame scheduler quantum

The bootstrap sets global quantum10µs. A separate three-active-Cortex-M CPU regression queues64bytes through the real576000baud adapter into unchanged FIFO1 and a polling firmware. Default quantum delivered64 wire attempts but only43 CPU reads. At10µs, the same test delivered64/64. UART status afterward wasC0 in both because firmware's status/data reads clear historical overrun. Thus wire DeliveredBytes and zero current error bits are not sufficient proof of lossless reception. This is a scheduler-resolution correction, not a larger hardware FIFO or reduced baud. Evidence: tests/rx-default.log and tests/rx-10us.log.

## Clock-coordinator telemetry

Include `peripherals/VirtualTimeTelemetry.cs` once, select main, instantiate `PrinterShared.VirtualTimeTelemetry @ sysbus`, then call `Enable` with an absolute run-specific JSON path. It publishes actual elapsed virtual nanoseconds immediately and every10ms virtual time through atomic same-directory replacement. No CPU/firmware state is read or changed. `Stop` publishes enabled=false. Epoch changes identify reset/time rewind; a pacing controller must explicitly handle or reject epoch changes and backwards time, missing/stale/malformed data and stopped telemetry. File-write errors stop publishing and are surfaced, never silently authorize free-running QEMU. A stopped emulator naturally stops periodic updates, so the controller must distinguish its own coordinated pause from unexpected lack of progress.

`tests/run-telemetry.py` checks initial/periodic samples, exact25ms stop timestamp and atomic temporary-file cleanup. This telemetry is a measurement, not a clock-coupling policy; QEMU stop/continue coordination belongs to the launcher.
