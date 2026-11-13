# Experimental RV1106 QEMU machine

Source overlay for QEMU 9.2.0, focused on ARMv7 firmware and U-Boot bring-up.
This is not a complete RV1106 silicon emulator. See [MODEL.md](MODEL.md) for
implemented hardware and known limitations. See [tools/README.md](tools/README.md)
for firmware container inspection and extraction.

## Build

On Debian or Ubuntu, install the build prerequisites:

```sh
sudo apt-get install build-essential curl xz-utils pkg-config \
  libglib2.0-dev libpixman-1-dev libfdt-dev ninja-build \
  python3 python3-venv python3-pip
```

Run from the source kit:

```sh
./scripts/build.sh
```

The script downloads the official QEMU 9.2.0 release and verifies its SHA-256:

```text
f859f0bc65e1f533d040bbe8c92bcfecee5af2c921a6687c652fb44d089bd894
```

It copies the board source, enables its GIC and serial dependencies, builds only
the ARM system target, and runs ARM/UART and register tests. QEMU may download
Python build dependencies during configuration. The script does not install
system packages. The checksum pins the source to the release used for testing;
it is not a separate verification of the upstream release signature.

Default output: `.build/build/qemu-system-arm`.
Set `RV1106_BUILD_ROOT=/absolute/path` to keep sources/build elsewhere and
`JOBS=4` to limit parallel compilation. Additional script arguments are passed
to QEMU's configure command. Re-running replaces the extracted board overlay
with this kit's version; use a dedicated build directory, not a working QEMU
checkout with local board edits. Header files and dependency versions may vary
by distro, so this is a repeatable source build, not a bit-for-bit binary build.

## Run a raw U-Boot image

```sh
.build/build/qemu-system-arm -M rv1106 -m 64M \
  -display none -monitor none -serial stdio -kernel u-boot.bin
```

The loader accepts a raw image loaded at physical `0x00200000`, or an ARM ELF
with load addresses in DRAM. The raw image must already be extracted from any
FIT/vendor container. Use one of `-kernel` or `-bios`, not both. Firmware build
options and peripherals can require additional modeling; the smoke tests do
not establish that arbitrary vendor firmware boots successfully.

## Tests

```sh
python3 tests/smoke.py .build/build/qemu-system-arm
python3 tests/registers.py .build/build/qemu-system-arm
python3 -m unittest discover -s tests -p 'test_*.py'
```

The smoke test executes generated ARM instructions and checks UART output.
Register tests use QEMU's qtest channel through standard-input/output pipes,
with no network or Unix socket required.

## Included Linux executable

The runnable kit includes `bin/qemu-system-arm`, built for **Linux x86_64** and
tested on Debian 13. It is not a native Windows, macOS, or ARM-host executable.
For those hosts, use the source build workflow in a supported Linux environment
or build QEMU natively with the corresponding host prerequisites.

The binary needs glibc 2.38 or newer (tested: 2.41), system GLib/GModule (tested:
2.84.4), zlib, Nettle/Hogweed, GMP, and GLib's usual system dependencies. The kit includes libfdt.
On Debian 13 the runtime packages are `libglib2.0-0t64`, `zlib1g`, `libnettle8t64`, `libhogweed6t64`, and `libgmp10` (and their
normal package dependencies). For older hosts, rebuild from source rather than
replacing core system libraries. Inspect missing libraries with:

```sh
ldd bin/qemu-system-arm
```

The binary's relative runtime search path finds `lib/libfdt.so.1`; keep `bin`
and `lib` beside one another. It does not depend on the original build directory.

```sh
bin/qemu-system-arm -M rv1106 -m 64M -display none -monitor none \
  -serial stdio -kernel /path/to/extracted/u-boot.bin
```

The separate `qemu-9.2.0-rv1106-source.tar.xz` contains the complete modified
QEMU source corresponding to the executable, with upstream licenses retained.
The board overlay and build script in this kit are also sufficient to reproduce
the integration against the checksum-pinned upstream tarball. See `licenses/`
for distribution notices. This private kit includes the user-supplied firmware normalized for this task; it is not covered by the QEMU license or licensed here for redistribution.

## Experimental eMMC controller build

`bin/qemu-system-arm-emmc` is the newer experimental build with DW-MSHC
PIO/32-bit chained IDMAC support and upstream QEMU's eMMC card model.
`bin/qemu-system-arm` is retained as the earlier no-card executable.
The current source overlay and `scripts/build.sh` build the eMMC variant.

Attach a power-of-two-sized raw disk with:

```sh
bin/qemu-system-arm-emmc -M rv1106 -m 64M \
  -display none -monitor none -serial stdio -kernel /path/to/firmware.elf \
  -drive if=sd,index=0,file=/path/to/disk.img,format=raw,snapshot=on
```

Snapshot mode protects the source disk from guest writes. This command does
not by itself create a Linux-compatible loader or device tree. The separate
Linux probe supplies those; full original-board peripheral support remains
incomplete. Controller-level tests:

```sh
python3 tests/emmc.py bin/qemu-system-arm-emmc
```
