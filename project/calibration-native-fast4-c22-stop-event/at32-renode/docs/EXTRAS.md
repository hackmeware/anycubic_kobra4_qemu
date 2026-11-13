# RTC, watchdog and DAC scope

These custom models target the AT32F403A register layout documented in the official AT32F403A/407 reference manual rev2.06 (sections15–17 and20). Rev2.07 research found no corresponding register-map changes. Timing uses Renode virtual-time `LimitTimer`; it is independent of wall-clock time.

## RTC (`AT32RTC`)

- Base0x40002800. IRQ3 is the combined second/alarm/overflow interrupt. `AlarmIRQ` is the alarm output; platform wiring should route via EXINT17 to IRQ41.
- 32-bit retained counter and alarm,20-bit divider, hardware reset values, configuration write gate, second/overflow/alarm flags, W0C clearing, and output IRQs.
- `ConfigureClock(ulong frequency,bool enabled)` must be connected to CRM clock selection/RTCEN. It starts disabled. `Reset()` is a system reset preserving battery-backed count/divider/alarm; `BackupReset()` clears the whole backup domain.
- DIV and alarm programming registers are write-only and read zero. Split divider-counter registers show live remaining ticks. Synchronization completion is immediate when clocked rather than delayed over APB cycles. Config writes and counter increment are not cycle-accurate; backup supply voltage, calibration drift and real calendar time are not modeled. Backup write protection must be enforced externally if required.

## Watchdogs (`AT32Watchdog`)

- `windowed:false` implements WDT at0x40003000 using40kHz LICK by default. StartCCCC, unlock5555, refreshAAAA; prescaler4..256;12-bit reload; protected writes. Update-busy flags settle immediately. Timeout is `(reload+1)*prescaler/frequency`.
- `windowed:true` implements WWDT at0x40002C00. PCLK1 defaults8MHz and is set through `Frequency`; divider4096..32768,7-bit counter, sticky enable, programmable refresh window, early-warning IRQ0 at0x40 and machine reset at0x3F. Refresh above window immediately requests reset.
- Both models emit `ResetRequested` and invoke Renode's `machine.RequestReset()`. CRM reset-cause flags require platform integration. No hardware-start option bytes, debug-halt freeze, voltage effects or low-speed oscillator variation. WDT has no hardware IRQ; its exposed IRQ output remains low.

## DAC (`AT32DAC`)

- Base0x40007400, two12-bit channels, output data latches, individual/dual right12,left12,right8 formats, channel enable, trigger selection and software trigger. 8-bit values occupy output bits11:4.
- `Channel1Output`/`Channel2Output` expose digital values. `OutputChanged(channel,value)` uses one-based channel numbers. `Trigger(source)` accepts hardware event IDs0..6, matching the datasheet; platform wiring is required for timer/EXINT trigger events. Software triggering requires selection7 and enable.
- Register-to-output update delay is immediate rather than1–3 APB cycles. Analog output voltage, buffer settling, noise/triangle generators and DMA request generation are not implemented. Enabling waveform or DMA mode produces a warning; it does not simulate those features.

## Regression

`tests/extras.robot` independently instantiates the four blocks and verifies RTC timing/alarm/W0C/retention, DAC alignment/software triggering, WWDT early interrupt followed by actual machine reset, WDT locked writes and actual timed reset. Run with Renode's `renode-test`, passing an absolute `MODEL_ROOT` if overriding its default. Tests use standalone clocks to isolate the model behavior from clock-controller integration.

## AT32 timer adapter (`AT32Timer`)

`peripherals/AT32F403A_Timer.cs` derives from Renode `STM32_Timer`. Constructor parameters are `machine`, `frequency` (default8MHz), and `supports32Bits` (defaultfalse). Set `supports32Bits:true` only on TMR2/TMR5. All instances reset period PR/ARR to zero rather than the upstream initial maximum. The upstream timer stays stopped with PR zero.

CTRL1 PMEN bit10 extends CNT,CxDT and PR to32 bits on TMR2/5; without PMEN their accesses are masked to16 bits. The adapter reimplements the bus interface, including explicit interface forwarding, so these rules apply to firmware MMIO rather than only monitor commands. Default16-bit counting follows the masked period. Clearing PMEN deterministically discards high halves, including stored compare values; hardware behavior when changing width mid-flight is not characterized. Keep the timer disabled while switching width.

The manual's principal PMEN description and official SDK `tmr_32_bit_function_enable()` support this behavior. An adjacent translated sentence in RM2.06 is contradictory about write width; the implementation follows the principal description. Features inherited from the generic STM32 timer remain approximations, especially advanced complementary outputs, dead time, DMA burst, and internal trigger matrix wiring. `tests/timer-adapter.robot` checks reset, default masking, TMR2/TMR5 extension, actual counting across0xFFFF, and ignored PMEN on TMR3.
