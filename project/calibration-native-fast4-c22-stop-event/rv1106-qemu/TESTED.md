# Verified results (2026-11-04)

## User-provided firmware

Normalized U-Boot+original control DTB SHA256:
`a2621d3b343666d4044502cc3f522a1ef15555c3920417607099e77e57378ce1`

With `-M rv1106 -m 256M`, the supplied firmware reaches the command interpreter. Its runtime global flags contain `GD_FLG_DISABLE_CONSOLE` (0x40). Therefore normal execution produces no UART console output. This is distinct from a CPU hang.

Clearing **only that volatile debugging flag** (not modifying the firmware file or its DTB) enables the console. Verified commands: `version`, `printenv`, `help`. Full output is in `test-results/user-console.txt`.

Version:
`U-Boot 2017.09-gf616e842c5 # (Apr 27 2026 - 17:27:44 +0800)`

The optional diagnostic launcher explicitly describes this change. It is specific to the supplied image and is not a silicon feature or an automatic patch for arbitrary firmware.

## USB update question

The running supplied U-Boot reports:

- `bootcmd=boot_fit;boot_android ${devtype} ${devnum};`
- `bootdelay=0`
- No `preboot` variable in the current default environment.
- `usb_update` exists in `help` as `usb auto upgrade`.

This demonstrates that the default environment does **not explicitly call `usb_update`**. It does not establish behavior of a real device's saved environment or every hardware boot path. This package has **no working USB host or USB mass storage**, so it cannot prove that an attached stick is detected or an update is executed.

Do not run `usb_update` against real storage merely to inspect its availability: upgrade commands may write firmware. The included tests use only read-only console queries.

## Reference firmware

Official JetKVM RV1106 v0.2.8 U-Boot (2017.09, Apr 28 2026) reaches `=>` without console override or control-DTB changes. FIT extraction and direct-start handoff are required. It reports missing boot media as expected because the model presents no MMC card.

Reference download: https://github.com/jetkvm/rv1106-system/releases/tag/release/v0.2.8

Reference normalized image SHA256:
`c68e1f3bc7dd3d8d844cb4cba6a87ddb1d9948db5bd5ef1b2b6dd2e149f8b938`

## Automated tests

- `tests/smoke.py`: executes actual ARM instructions, firmware entry and UART TX/LSR polling.
- `tests/registers.py`: DDR/SERIAL handoff, UART/DW status, PLL lock and masked registers, GIC, TRNG, SARADC and no-card MMC semantics.
- `tests/test_image.py`: FIT/raw/ELF preparation helper regression cases.

These original baseline tests passed on the built Linux x86_64 QEMU. By themselves they do not certify Linux boot, accurate electrical behavior, storage, USB or compatibility with every RV1106 build. See the later eMMC extension results below.

## Experimental eMMC extension (2026-11-04)

`tests/emmc.py` verifies upstream QEMU eMMC enumeration, PIO sector reads,
32-bit IDMAC sector reads/writes, chained multi-block reads, descriptor ownership
clearing, completion status and automatic CMD12. Tests use a disposable temporary
64 MiB raw disk and do not write supplied firmware. Existing no-card register
behavior is retained when no disk is attached. These are controller-level tests;
they do not on their own establish Linux boot or faithful hardware timing.

The supplied Linux 5.10.160 kernel has additionally booted with this build,
EL3 disabled and a reduced diagnostic DT (fixed eMMC clock and nonsecure timer).
It enumerated the 512 MiB eMMC and all 14 partitions using explicit `blkdevparts`
(the kernel does not recognize the synthetic disk's GPT). A separately prepared
offline profile mounted squashfs on device 179:8 and launched its diagnostic
init script, producing `RV1106_OFFLINE_USERSPACE_READY` and a BusyBox 1.27.2
shell on the actual emulated UART. This is not a claim that the original vendor
startup sequence, networking, printer control, USB or Klipper works. See the
separate Linux probe's preserved console and boot logs for boot evidence.

A separate baseline probe also mounted the unchanged original `system.img`
squashfs from the original synthetic GPT disk with `init=/bin/sh`. The shell
executed and exited zero without a usable initial console, causing the expected
PID1-exit panic. Thus unchanged rootfs mounting is verified separately from the
interactive offline profile; default vendor boot scripts were not executed.
