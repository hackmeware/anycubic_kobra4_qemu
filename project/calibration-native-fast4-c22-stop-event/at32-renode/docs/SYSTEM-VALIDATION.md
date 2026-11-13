# CRM and ADC targeted validation

Run `tests/run-system.sh` (or set `RENODE` to a compatible launcher). The checked-in C# fixture runs **51 assertions inside Renode 1.17.0**, failing on mismatches rather than matching only startup log text. It is independent of the production board platform; its 12 MHz HEXT is intentional to exercise PLL ×40 with /2 input, giving 240 MHz.

## CRM review

Compared against official `at32f403a_407_crm.c` (`crm_pll_config`, `crm_clocks_freq_get`) and reference manual Rev 2.06 sections 4.3.1–4.3.3:

- SDK PLL multiplier encoding is not simply the raw number. ×40 is enum 39: low field 7, high field 2. The lower encoding range has an offset of two; extended encoding has an offset of one.
- PLL readiness requires its selected HICK/HEXT input to be enabled and ready. A requested system-clock switch remains pending until the source is ready.
- Software cannot disable the active system clock. The PLL input is retained while the PLL supplies the core.
- HICK/HEXT/PLL readiness transitions set interrupt flags. Flags clear through the corresponding high write-one-clear bits without altering the enable bits unless those bits are explicitly written.
- Tests verify 240 MHz system/AHB, AHB/APB prescalers, NVIC clock propagation, oscillator ready/error-free transitions, W1C flags and IRQ deassertion, and registered peripheral resets on reset-bit rising edges.

Oscillator stabilization is instantaneous. Crystal failure, analog trim/calibration effects, voltage/frequency operating limits and cycle-accurate clock switching are not simulated. Reset callbacks are edge-based rather than holding peripherals inaccessible while the reset bit remains asserted. Clock-enable register values do not by themselves prove every peripheral is gated.

## ADC review

Compared against `at32f403a_407_adc.h` and RM sections 19.4.2.2 and 19.6:

- Calibration initialization and calibration complete immediately and clear their request bits.
- Ordinary software triggers require ADCEN, OCTEN and OCTESEL=7. A complete example CTRL2 value is `0x005E0001`. Preempt software triggering uses PCTEN and PCTESEL=7, for example `0x0020F001`.
- Rewriting unchanged CTRL2 with ADCEN already set triggers ordinary conversion, as specified by the alternate enable-bit trigger mechanism.
- Ordinary sequences select configured channel samples and retain the final result in ODT. Left alignment, CCE IRQ, data-read CCE clearing and write-zero status clearing are tested.
- Voltage monitoring respects ordinary/preempt enable bits and single-channel selection. Reading ODT does not clear a watchdog IRQ.
- Preempt results subtract the configured per-result offset and return signed values in 16 bits. Preempt completion sets PCCS, PCCE and CCE. Reading ordinary data does not clear PCCE or its IRQ.
- Automatic preempt conversion following ordinary conversion is implemented.

Inputs are deterministic values assigned by `SetChannelValue(channel, value)`; they are not electrical pin voltage simulations. Conversion/sample/calibration timing, timer/pin trigger routing, continuous periodic conversions, discontinuous subgroup scheduling, multi-ADC synchronized modes and analog temperature/reference behavior are not implemented. Software-triggered sequences complete synchronously. Repeat-mode configuration is retained but does not create an unbounded background conversion loop. The shared ADC class does not distinguish ADC1-only internal channels or ADC2's lack of native DMA. DMA request pulses require explicit platform wiring and a compatible DMA controller.

The startup-facing flash controller remains explicitly limited: it exposes startup configuration and rejects programming/erase rather than claiming physical flash behavior. These CRM/ADC tests do not validate flash programming.
