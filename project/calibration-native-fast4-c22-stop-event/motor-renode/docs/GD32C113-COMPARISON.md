# Public GD32C parts compared with the motor firmware

Verified 2026-11-04. No silicon identity or model changes follow from this comparison.

## Conclusion

GD32C103 and GD32C113 share several peripheral addresses and the Cortex-M4/FPU architecture with the firmware, but their documented 32 KiB SRAM and two-ADC implementation do not explain the motor's active RAM near 0x20015EC0 and third ADC at 0x40013C00. The exact GD32FCESRBT6 catalog designation remains independently supported by JLC, but this is not evidence that FCES is an official public GD32C family or a synonym for C103/C113.

## User-supplied GD32C113 datasheet

Primary document: [GD32C113xx Datasheet Rev1.6](https://download.gigadevice.com/Datasheet/GD32C113xx%20Datasheet_Rev1.6.pdf). The download host timed out during this check; the same revision was retrieved from the [official GD32MCU host](https://www.gd32mcu.com/data/documents/datasheet/GD32C113xx%20Datasheet_Rev1.6.pdf). Local PDF/text: `../research/gd32-c/C113.pdf` and `C113.txt`. Page numbers below are printed document pages.

- Table 2-1, p8: all TB/CB/RB/VB devices have 128 KiB flash and 32 KiB SRAM. The RB variant has both advanced timers 0 and 7.
- Sections 3.1 and 3.2, p34: Cortex-M4, FPU, maximum 120 MHz; up to 32 KiB SRAM.
- Table 2-2, p13: RCU at 0x40021000; ADC0 at 0x40012400; ADC1 at 0x40012800; TIMER7 at 0x40013400.
- Table 2-2, p14: GPIOA at 0x40010800.
- Crucially, Table 2-2, p13 labels 0x40013C00–0x40013FFF **Reserved**. It does not contain a third ADC.
- Table 2-2, p15 labels a broad SRAM aperture through 0x2001FFFF. This broad address-map label must not be mistaken for the implemented SRAM capacity: the exact SKU table and memory description explicitly say 32 KiB. No evidence here establishes extra implemented RAM or usable mirroring.

Firmware evidence supplied by the model investigation: initial SP 0x20015EC0; actual initialized data/accesses around 0x20014EAC; FPU enable; clock controller at 0x40021000; GPIOA at 0x40010800; ADC accesses at 0x40012400, 0x40012800, and 0x40013C00; advanced timer at 0x40013400. Parent additionally verified third-ADC calibration and IRQ code, so the third ADC is not merely an unused constant. SP lies 89,792 bytes above SRAM base. This is incompatible with an ordinary contiguous 32 KiB SRAM implementation.

The timer naming differs: the firmware/AT32 model calls the block at 0x40013400 TMR8; GD32 calls it TIMER7. Matching its address does not imply identical register semantics. Likewise, CPACR enable shows an intended floating-point environment, not a unique chip identity. A firmware-derived 240 MHz assumption cannot be treated as the C113's rating; the datasheet limit is 120 MHz.

## User-supplied GD32C103CBT6 candidate

The [exact official SKU page](https://www.gigadevice.com/product/mcu/mcus-product-selector/gd32c103cbt6) specifies Cortex-M4, 120 MHz, 128 KiB flash, 32 KiB SRAM, **LQFP48**, two ADC units, and one advanced timer. Thus CBT6 is a different package from the JLC FCESRBT6 LQFP64 listing; it is not just another spelling of that catalog part.

[GD32C103xx Datasheet Rev2.0](https://www.gd32mcu.com/data/documents/datasheet/GD32C103xx%20Datasheet_Rev2.0.pdf), Table 2-1 p8, assigns the CB device only advanced TIMER0; TIMER7 is present on RB/VB, not CB. Its family memory map (Table 2-2 pp13–14) shares RCU/GPIOA/ADC0/ADC1 addresses above, but also reserves 0x40013C00. Section 3.1 explicitly includes an FPU. Consequently CB adds a TIMER7 availability mismatch to the RAM/third-ADC/package conflicts. RB resolves the package and TIMER7 differences, but not RAM or third ADC. Local source: `../research/gd32-c/C103.pdf` and `C103.txt`.

## Other public C family

The public product catalog lists C103/C113 under C1x3 and C231 under C2x1; it does not establish a CES family. [Official C231 page](https://www.gigadevice.com/product/mcu/entry-level-mcus/gd32c2x1-series/gd32c231) and [GD32C231xx Datasheet Rev1.6](https://www.gd32mcu.com/data/documents/datasheet/GD32C231xx_Datasheet_Rev1.6.pdf) describe Cortex-M23, up to 48 MHz, 32/64 KiB flash and 12 KiB SRAM. The memory map puts GPIOA at 0x48000000, a single ADC at 0x40012400, and reserves 0x40012800, 0x40013400 and 0x40013C00. RCU remains 0x40021000. It is a substantially worse match; matching RCU alone is not discriminating. Local PDF/text: `../research/gd32-c/C231.pdf` and `C231.txt`.

## What remains unresolved

The exact FCES marking is real catalog evidence, but no manufacturer FCES datasheet, reference manual, or SDK has been established. Public C-series documentation provides useful comparisons, not permission to assign C113/C103 memory or clock characteristics to FCES. The minimal next evidence would be a manufacturer/distributor cross-reference or exact FCES documentation, together with confirmation that this binary belongs to this physical motor board.
