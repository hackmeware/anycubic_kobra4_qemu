# Kobra board clock profile and cross-emulator timing

The generic chip platform uses an illustrative 8 MHz HEXT crystal. This is not a claim about the Kobra PCB. For the original Kobra main firmware, use `scripts/load-kobra4.resc` instead of `scripts/load.resc` before loading the binary. It selects HEXT = 24 MHz without changing the generic platform.

Evidence for this board-specific hypothesis:

- The original native host identifies main firmware v1.3.3, then reports an expected MCU clock of 120 MHz.
- The firmware programs CRM CFG = 0x000DE40A, resulting in PLL multiplication by 5 and APB division by 2 in the model.
- The firmware's fixed USART1 divisor is 104. A 24 MHz HEXT therefore yields 120 MHz core, 60 MHz APB2 and integer-reported UART baud 576923, consistent with the original host's requested 576000 (0.16% difference).
- An 8 MHz HEXT yields 40 MHz core and 192307 baud, a factor of three below both host expectations.

This is strong configuration evidence, not an independent measurement of a physical crystal. The original binary is unchanged. No safety check, firmware clock report or host clock validator is bypassed.

## Deterministic checks

With the original main image loaded at 0x08004000, the 24 MHz profile boots without CFSR/HFSR faults. After startup, DWT CYCCNT advances by exactly 12,000,000 over 0.1 seconds of Renode virtual time. The optional `tests/user_firmware.robot` checks the clock, UART divisor result and counter delta.

The separate provisional nozzle model runs the original v1.2.9 image with a 72 MHz core. Its DWT advances by exactly 7,200,000 over 0.1 seconds of Renode virtual time. Its USART1 divisor 63 gives 571428 baud from 36 MHz APB2, about -0.79% from 576000. Exact physical nozzle MCU identity remains unproven.

## Timing that these checks do not establish

The current bridge uses separate, independently running Renode processes and a QEMU/native-host timebase. Optional UART byte pacing uses host wall time, not a shared virtual time scheduler. Correct DWT frequency per virtual second does not establish synchronized MCU clocks relative to the host application. Scheduling delays, emulator throughput and UART transport latency can distort the host's clock-estimation samples.

In the first dual-MCU run the host estimated the nozzle at about 1.5–5 MHz despite the verified 72 MHz virtual-time counter. That observation must not be repaired by inventing a faster nozzle crystal or disabling clock/safety validation. A synchronized co-simulation clock or a measured real-time transport needs separate validation. Changing CPU instruction throughput alone is not a validated solution.
