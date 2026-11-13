#!/usr/bin/env bash
# Build the overlay against the exact upstream QEMU release used for validation.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
WORK=${RV1106_BUILD_ROOT:-"$ROOT/.build"}
VERSION=9.2.0
SHA256=f859f0bc65e1f533d040bbe8c92bcfecee5af2c921a6687c652fb44d089bd894
ARCHIVE="$WORK/qemu-$VERSION.tar.xz"
SOURCE="$WORK/qemu-$VERSION"
BUILD="$WORK/build"
mkdir -p "$WORK" "$BUILD"
if [[ ! -f "$ARCHIVE" ]]; then
    LOCAL_ARCHIVE="$ROOT/../sources/qemu-$VERSION.tar.xz"
    if [[ -f "$LOCAL_ARCHIVE" ]]; then
        cp "$LOCAL_ARCHIVE" "$ARCHIVE"
    else
        curl --fail --location --retry 3 "https://download.qemu.org/qemu-$VERSION.tar.xz" -o "$ARCHIVE.part"
        mv "$ARCHIVE.part" "$ARCHIVE"
    fi
fi
printf '%s  %s\n' "$SHA256" "$ARCHIVE" | sha256sum --check -
if [[ ! -d "$SOURCE" ]]; then
    tar -xJf "$ARCHIVE" -C "$WORK"
fi
# Only re-use a source tree created for this overlay. Existing local edits to
# rv1106.c are replaced by the kit's version on each build.
cp "$ROOT/hw/arm/rv1106.c" "$SOURCE/hw/arm/rv1106.c"
if ! grep -q '^config ROCKCHIP_RV1106$' "$SOURCE/hw/arm/Kconfig"; then
    cat >> "$SOURCE/hw/arm/Kconfig" <<'KCONFIG'

config ROCKCHIP_RV1106
    bool
    default y
    depends on TCG && ARM
    select ARM_GIC
    select SERIAL_MM
    select SD
    select USB_DWC3
    select USB_NETWORK
KCONFIG
fi
# Upgrade an earlier copy of this overlay's dependency block in reused trees.
python3 - "$SOURCE/hw/arm/Kconfig" <<'PYCONFIG'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
s = p.read_text()
start = s.index("config ROCKCHIP_RV1106\n")
end = s.find("\nconfig ", start + 1)
end = len(s) if end < 0 else end
block = s[start:end]
for dependency in ("SD", "USB_DWC3", "USB_NETWORK"):
    line = f"    select {dependency}\n"
    if line not in block:
        block += line
p.write_text(s[:start] + block + s[end:])
PYCONFIG
if ! grep -q "CONFIG_ROCKCHIP_RV1106" "$SOURCE/hw/arm/meson.build"; then
    printf "\narm_ss.add(when: 'CONFIG_ROCKCHIP_RV1106', if_true: files('rv1106.c'))\n" >> "$SOURCE/hw/arm/meson.build"
fi
if ! grep -q '^CONFIG_ROCKCHIP_RV1106=y$' "$SOURCE/configs/devices/arm-softmmu/default.mak"; then
    printf '\nCONFIG_ROCKCHIP_RV1106=y\n' >> "$SOURCE/configs/devices/arm-softmmu/default.mak"
fi
cd "$BUILD"
"$SOURCE/configure" --target-list=arm-softmmu --without-default-devices \
    --disable-docs --disable-werror --disable-tools --disable-guest-agent \
    --disable-pixman --disable-curl --disable-gnutls --disable-zstd --disable-modules \
    --enable-slirp "$@"
ninja -j "${JOBS:-$(getconf _NPROCESSORS_ONLN)}" qemu-system-arm
python3 "$ROOT/tests/smoke.py" "$BUILD/qemu-system-arm"
python3 "$ROOT/tests/registers.py" "$BUILD/qemu-system-arm"
python3 "$ROOT/tests/emmc.py" "$BUILD/qemu-system-arm"
printf '\nBuilt and tested: %s\n' "$BUILD/qemu-system-arm"
