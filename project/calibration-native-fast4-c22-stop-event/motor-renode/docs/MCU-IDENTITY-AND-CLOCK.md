# Motor MCU identity and clock evidence

Updated2026-11-04. This report supersedes the earlier suggestion that `GD32FCESRBT6` might be an OCR error.

## Confirmed name, unconfirmed silicon specifications

The exact **GD32FCESRBT6** part string is externally supported by the user-provided [JLCPCB entryC9900165928](https://jlcpcb.com/partdetail/JLCPCBAssembly-GD32FCESRBT6/C9900165928). It specifies **LQFP64-10X10-0.5**. Its manufacturer field says “JLCPCB Assembly” and category “Others/SMT”; it supplies no MCU core, RAM, flash, clock, register-map or datasheet specification. This establishes the catalog identity/package, not equivalence to GD32F303 or GD32F305.

A [first-hand Anycubic Kobra S1 teardown](https://www.lesimprimantes3d.fr/anycubic-kobra-s1-combo-le-test-detaille-20250502/) also identifies GD32FCESRBT6 on the controller and provides chip photographs. Its accompanying numeric claims are M4,120MHz,128KB flash and32KB SRAM. Those specifications were not independently verified against a GigaDevice FCES datasheet, so the emulator must not treat them as certified limits. Targeted searches of GigaDevice/gd32mcu documentation and public SDK sources did not locate an FCES datasheet, reference manual, SVD or SDK during this research. Failure to locate documentation is not evidence that the part does not exist.

**Correction:** the earlier unrecognized/OCR interpretation was premature. Retain the exact FCES identity from the user and JLC listing. Do not replace it with a familiar GD32F30x SKU merely because the suffix looks similar.

## Firmware requirements and remaining contradiction

Observed firmware evidence supplied by the emulator investigation:
- Application95,017bytes, loaded at0x08008000: occupied flash extent127,785bytes from flash base, fitting128KiB but not proving that density.
- Initial SP0x20015EC0 and actual initialized-data accesses near0x20014EAC. SP is89,792bytes above0x20000000 (87.6875KiB); actual SRAM use exceeds64KiB.96KiB reaches0x20017FFF.
- FPU-access setup via CPACR, legacy clock-control base0x40021000, RTC base0x40002800. These do not uniquely identify a silicon family; CPACR setup alone is weaker evidence than executed FPU instructions.

The reported32KiB FCES SRAM figure therefore conflicts with the observed firmware. This discrepancy remains unresolved. Possible explanations must be tested, not asserted: undocumented FCES mapping, mistaken secondary specifications, board/firmware mismatch, or compatibility code. A readable chip photograph helps connect the listed SKU to the actual board; manufacturer/OEM documentation or read-only silicon and memory-map evidence is still needed for certified parameters.

## Conventional GD32 candidates are comparisons, not replacements

Official per-SKU pages and historical [GD32F303xx Rev1.9 table2-1,p8](https://www.gd32mcu.com/data/documents/datasheet/GD32F303xx_Datasheet_Rev1.9.pdf) establish:
- [GD32F303RBT6](https://www.gigadevice.com/product/mcu/mcus-product-selector/gd32f303rbt6):128KiB flash/32KiB SRAM.
- [GD32F303RCT6](https://www.gigadevice.com/product/mcu/mcus-product-selector/gd32f303rct6):256/48KiB.
- [GD32F303RET6](https://www.gigadevice.com/product/mcu/mcus-product-selector/gd32f303ret6):512/64KiB.
- [GD32F305RBT6](https://www.gigadevice.com/product/mcu/mcus-product-selector/gd32f305rbt6):128/64KiB.

All four lack enough specified SRAM for the observed runtime use. Official96KiB comparisons include [GD32F303RGT6](https://www.gigadevice.com/product/mcu/mcus-product-selector/gd32f303rgt6) (1024KiB flash), [GD32F305RCT6](https://www.gigadevice.com/product/mcu/mcus-product-selector/gd32f305rct6) (256KiB), and [GD32F307RCT6](https://www.gigadevice.com/product/mcu/mcus-product-selector/gd32f307rct6) (256KiB). Their pages specify Cortex-M4,120MHz,LQFP64. These satisfy broad memory/package constraints only; no source proves FCES equivalence to any of them. Family-level “up to96KiB” text must not override exact-SKU memory tables.

## CFG0=0xA00FA40A: family-dependent interpretation

Authoritative comparison source: downloaded GigaDevice Keil pack, `research/gd32-pack/Device/Firmware/Peripherals/inc/gd32f30x_rcu.h` lines114–147 and351–361, `Device/Source/system_gd32f30x.c` lines901–1000, and corresponding HD/XD/CL SVDs. Pack identity/version/source is recorded in `research/GD32F30x_DFP.pdsc`.

- F303 HD/XD multiplier extension bits: CFG0bit27 andbit30. CFG0bit29 is reserved;bit31 belongs to USB divider. This value decodes PLL×5, with PREDV0bit17 selecting/2. With HXTAL8MHz and HXTAL source selected in CFG1, system clock would be20MHz, not80MHz.
- F305/F307 CL extension bits: CFG0bit29 andbit30. This value decodes PLL×20. Its input clock depends on CFG1 at0x4002102C: PREDV0[3:0]+1, optional PLL1 path selected bybit16, and HXTAL/IRC48M selectionbit30.
- **CL alias caveat:** CFG0bit17 is the low bit of CFG1.PREDV0. An AT32 model storing these independently can reportCFG1=0 after firmware writesCFG0bit17=1; that is not faithful CL hardware evidence. Trace writes and implement the proven family semantics before deriving clock.
- Both APB divisors are/2;AHB is/1. Firmware delay-factor30 under a SysTick/8 calculation indicates a240MHz software assumption, not proof of oscillator frequency or actual silicon clock.

The AT32 interpretation, F303 interpretation and CL interpretation are not interchangeable. The GD32F30x parts above are officially120MHz devices. Do not alter the clock to240MHz or choose a24MHz crystal solely to make the delay loop fit; FCES clock behavior remains undocumented here.

## Modeling decision

Keep the existing motor profile explicitly experimental. Preserve the documented firmware requirements separately from claimed physical specifications. Do not advertise an AT32 ID, a synthetic GD32 ID, a certified GD32FCES clock, or an exact GD32F303/305 replacement. No production model change was made by this research. The next decisive evidence is FCES manufacturer/OEM documentation or validated read-only board identification and clock/memory measurements.
