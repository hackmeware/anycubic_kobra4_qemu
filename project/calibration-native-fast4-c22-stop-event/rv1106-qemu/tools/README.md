# Firmware inspection and controlled loading

`rv1106_image.py` is a Python 3 standard-library tool. It does not invoke vendor
unpackers, execute scripts from firmware, flash devices, or mount filesystems.
`run` prints a command by default; only `run --execute` starts QEMU.

## Inspect first

```sh
python3 tools/rv1106_image.py inspect /path/to/uboot.img
python3 tools/rv1106_image.py inspect /path/to/u-boot.elf
python3 tools/rv1106_image.py inspect /path/to/u-boot.bin --format raw
```

An arbitrary `.bin` filename is not proof of format. Raw interpretation requires
`--format raw`. Recognized Rockchip RKFW/RKAF update containers, Android images,
and plain DTBs cannot be passed off as raw executable firmware. Other unknown
containers are refused automatically, but a user can explicitly label unknown
bytes raw, so use this option only after reviewing their origin and contents.
A Linux `boot.img` FIT can be inspected but is not a U-Boot launch image.

Input is limited to 256 MiB; each decompressed member to 128 MiB. FDT offsets,
lengths, tree nesting, duplicate properties, image references, ELF load segments,
entry points, and DRAM limits are checked. Supported stored hashes are SHA-1,
SHA-256/384/512 and CRC32. A mismatch aborts inspection/extraction. A missing hash
is reported as an empty `verified_hashes` list, not a verification success.

FIT signature nodes are reported but **cryptographic signatures are not
verified**. An attacker can replace both data and its hash. SHA-1/CRC32 are weak
integrity mechanisms, not authentication. No output from this tool certifies
that firmware is trustworthy.

## Extract a U-Boot FIT

```sh
python3 tools/rv1106_image.py extract /path/to/uboot.img \
  --config conf --output /tmp/u-boot-with-dtb.bin
```

`--config` defaults to `/configurations/default`; explicit selection is required
when no default is available. The selected configuration must identify exactly
one ARM `firmware` or `standalone` image via `firmware` or `loadables`, with load
and effective entry at **0x00200000**. Additional loadables, kernel/ramdisk
configurations, other load addresses, and ELF-inside-FIT are deliberately refused.
A referenced `flat_dt` without a load address is appended as the U-Boot control
DTB. This matches the supplied RV1106 vendor image; it is not a universal FIT
boot implementation.

Inline data, absolute `data-position`, and aligned external `data-offset` are
supported. Compression: `none`, `gzip`, and `lzma`. Rockchip LZMA's optional
four-byte little-endian decompressed-size trailer is checked. Rockchip `digest`
nodes are checked against decompressed data; standard `hash*` nodes against
stored bytes. Unsupported compression/hash schemes fail closed. Extraction uses
an exclusive new file and never overwrites an existing path.

## Launch through the RV1106 machine

Build the patched QEMU separately. This helper does not install or build it.

```sh
# Prepare a normalized file and print the command without executing:
python3 tools/rv1106_image.py run /path/to/uboot.img --config conf \
  --output /tmp/u-boot-with-dtb.bin --qemu /path/to/qemu-system-arm

# Run an already reviewed raw image, with a bounded execution deadline:
python3 tools/rv1106_image.py run /tmp/u-boot-with-dtb.bin --format raw \
  --qemu /path/to/qemu-system-arm --execute --timeout 30

# Or an ARM ELF32 ET_EXEC image linked into physical DRAM:
python3 tools/rv1106_image.py run /path/to/u-boot.elf \
  --qemu /path/to/qemu-system-arm --execute --timeout 30
```

The command uses `-M rv1106 -m 64M -display none -monitor none -serial stdio
-nic none -kernel IMAGE`. `--ram-mib` accepts 64, 128, or 256. Raw images load at
0x200000; ELF segments and entry must lie in DRAM without overlapping the
preloader ATAGS region. A normal U-Boot prompt runs indefinitely, so deadline
termination (exit status **124**) is expected, not proof of boot failure.
Other QEMU exit statuses are propagated. Parse/I/O errors exit 2.

No host filesystem sharing or disk attachment is configured. Nevertheless,
**QEMU is not a security boundary**: run unfamiliar firmware in a disposable,
restricted environment, and do not add host passthrough devices or writable
disks. Keep inputs unchanged between inspection and launch. The modeled board
is experimental and does not promise full Linux boot or hardware fidelity.

## Reproducible regression tests

From the source-kit directory:

```sh
python3 -m unittest discover -s tests -p 'test_image.py' -v
python3 -m py_compile tools/rv1106_image.py tests/test_image.py
```

The suite creates synthetic FITs/ELFs and requires no firmware downloads,
compiler, external dependencies, or QEMU binary. It tests inline and both
external data modes, gzip/LZMA, Rockchip trailers, hash corruption, invalid
configurations/load addresses, unknown/update container refusal, ELF validation,
all truncated prefixes of a valid FDT, invalid offsets/tokens, output limits,
non-executing dry runs, and overwrite refusal.

Integration checked against the public test FIT and the supplied RV1106 FIT:

| Input | Input SHA-256 | Normalized SHA-256 |
| --- | --- | --- |
| Public test `uboot.img` | `d2d03008d0b2de4b5220998c35c3c818fb9ea0c141de0633bd2b372075ab51e3` | `c68e1f3bc7dd3d8d844cb4cba6a87ddb1d9948db5bd5ef1b2b6dd2e149f8b938` |
| Supplied `uboot.img` | `0d6877f7c4a0646b510e68617c9eef9c6b98fd8ed3bd841e99bf30aae536ace1` | `a2621d3b343666d4044502cc3f522a1ef15555c3920417607099e77e57378ce1` |

These are reproducibility identifiers, not vendor authentication. The supplied
normalized output is 520112 bytes (511184 bytes U-Boot plus 8928 bytes DTB).

## Interactive console for the supplied original image

The supplied, unmodified U-Boot reaches its prompt but disables console input
through its runtime global-data flags. To use the explicitly diagnostic console:

```sh
python3 tools/run_console.py /path/to/u-boot-normalized.bin \
  --qemu /path/to/qemu-system-arm --enable-console-debug
```

This starts the model with **256 MiB RAM**, inherits your terminal for UART2,
and uses private FIFO pipes for QMP/qtest (no debugger TCP listener). After boot,
it pauses QEMU, discovers the relocated global-data address from ARM R09,
validates the DRAM pointer and initialization flags, clears only
`GD_FLG_DISABLE_CONSOLE` (0x40) in guest RAM, checks the result, and resumes.
The firmware file is never modified. This diagnostic changes firmware behavior;
it is not an unmodified boot or hardware-accurate fix. It is allowed only for
normalized SHA-256 `a2621d3b343666d4044502cc3f522a1ef15555c3920417607099e77e57378ce1`.

Once the diagnostic confirmation appears, press Ctrl-C then Enter if needed.
`version`, `printenv`, and `help` were verified against the real QEMU process.
Without `--enable-console-debug`, the launcher applies no runtime patch and can
run another reviewed normalized raw/ARM ELF image. Firmware formats still need
review with the inspector above; FIT files must be extracted first.

Stop the wrapper with SIGTERM from another terminal, or use `timeout 60s` before
the command for a bounded session. SIGTERM cleans up QEMU and temporary FIFOs.
The pure UART stdio backend does not provide QEMU's Ctrl-A X monitor shortcut.

Run console flag regression tests with:

```sh
python3 -m unittest discover -s tests -p 'test_console.py' -v
```
