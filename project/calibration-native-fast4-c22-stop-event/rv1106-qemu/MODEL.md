# Model scope

This is an **experimental U-Boot-proper bring-up machine**, not a cycle-accurate RV1106 and not a replacement for hardware validation.

Implemented:

- One Cortex-A7 with ARMv7 instructions, MMU/caches as modeled by upstream QEMU, and a 24 MHz architectural timer.
- DRAM at physical zero (32/64/128/256 MiB), SRAM window at 0xff700000.
- GICv2 at 0xff1f1000 / 0xff1f2000 with UART and CPU timer connections.
- UART0–5 16550-compatible core with 32-bit register spacing, debug UART2 first serial backend. Minimal DW APB status extension.
- Rockchip preloader CORE/DDR/SERIAL ATAG handoff at 0x001fe000. Firmware starts directly in initialized DRAM; no DDR training or BootROM is executed.
- GRF, IOC, PMU IOC and GPIO register storage using Rockchip high-half write masks. GPIO inputs are unconnected/pulled high. No GPIO interrupts, electrical pinmux behavior or external peripherals.
- CRU register storage, known UART fractional registers and synthesized PLL lock bits. This is not a clock/reset-tree model. Clock values do not alter the CPU frequency or peripheral timing.
- Secure timer bank counter reads driven by QEMU virtual time. No timer IRQ/expiry/reload model; architectural timer interrupts are real QEMU CPU/GIC signals.
- TRNGv1 request/status protocol backed by QEMU host entropy, not deterministic fake random data. No hardware health-test/failure model.
- SARADCv2 with two unconnected channels returning full-scale 1023 and immediate conversion-complete status. No physical analog behavior or interrupts.
- Experimental DW-MSHC at 0xffa90000/0xffaa0000 with IRQ48/49, upstream QEMU eMMC card protocol, PIO and 32-bit chained IDMAC block I/O. Attach with `-drive if=sd,index=0,file=DISK,format=raw,snapshot=on`. No attached drive preserves no-card behavior. No electrical signalling, DDR/HS200 tuning, 64-bit descriptors or complete hardware timing model. Use snapshot mode to protect source disk images.

Unsupported or deliberately approximate:

- BootROM, DDR initialization/training, proprietary miniloader, SPL boot chain, secure boot and authentication.
- SPI NOR/NAND, SFC, USB/USB download mode, Ethernet/PHY, video/ISP, secondary MCU, most clocks/resets and arbitrary board peripherals.
- Saved VM state and migration are blocked because board register state is not serialized.
- `-kernel` / `-bios` accept ARM ELF or a normalized raw U-Boot payload at 0x00200000. They do not interpret FIT, Rockchip containers, update.img or Linux boot.img. Use the supplied preparation helper for supported FIT images.
- A successful banner/console is not proof of Linux boot, storage operation or arbitrary U-Boot-version compatibility. Missing MMIO devices remain explicit errors, not silently successful devices.

For debugging use `-d guest_errors,unimp -D guest.log`. The latter reports approximate clock/pinmux writes as well as truly unimplemented accesses. Use `-S -gdb tcp::1234` on a host where listening sockets are allowed, then connect an ARM-aware GDB to inspect actual guest code.

### Diagnostic Linux eMMC mode

With `-cpu cortex-a7,has_el3=off`, GIC security is disabled and the vendor
GICC_AIAR/AEOIR accesses are aliased to the single interrupt view. This is a
diagnostic boot configuration, not secure firmware emulation. The eMMC OCR
reports the board-specific voltage window `0x00ff8080` required by this vendor
kernel, with immediate power readiness. Commands complete on a virtual timer
after 10 microseconds. No physical timing, power-ramp or signal tuning fidelity
is claimed.
