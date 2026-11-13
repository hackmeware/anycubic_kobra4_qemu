# Runtime/source review, 2026-11-12

Read-only inspection of recovered private project. Not a legal certification or
permission to redistribute proprietary firmware. No publication performed.

## Scalar QEMU: exact source relationship exists

Runtime bin/qemu-baseline SHA256:
d295efe337e46357fa6cc9bf28356ba6e0cc0df5c82198aa3bf0a4d1eae7bfb1

Recovered rv1106-qemu/hw/arm/rv1106.c SHA256:
3e93fe0cddb52937db806f844278a216873b29a8be3f54634cb3f63321ff50cd

This matches baseline_board and baseline_binary in
rv1106-at32-link/experimental/clock-snapshot/evidence/build-provenance.json.
BUILD.de.md describes exact reconstruction. Its source-inputs directory contains
exact24-source-checkpoint.tar.gz (architecture original/patched sources, patch,
apply script and build script) and pinned DTC source. Required upstream archive
qemu-9.2.0.tar.xz SHA256 f859f0bc65e1f533d040bbe8c92bcfecee5af2c921a6687c652fb44d089bd894
is identified there; full QEMU source was separately saved in Library source bundle
libfile_0e8d2b2359d881a48655b1adb9762994. Do not substitute a newer display source overlay.

Thus 'matching scalar board source missing' is not a correct blocker. Complete
corresponding-source assembly and verification still requires the upstream inputs,
all overlays/build scripts and library source obligations. The scalar runtime has
11 private loader/library files but only COPYING and COPYING.LIB at its root.
Some dependency copyright notices exist under recovered build-deps/root/usr/share/doc;
that is not yet a complete audit of every actual runtime dependency's source/notice.
QEMU is GPLv2; bundled LGPL libraries need their applicable compliance path too.

## Renode 1.17.0 portable

renode SHA256:
822209a27168e2ce2e5e679ed481686b555c8e154745431b25d8b4104c34138f
Renode.dll SHA256:
b2087934786916d0e1101207a656a0145b776a0ce475528f7094470d5562c68f
Infrastructure.dll SHA256:
02b3510bed195f43c56aa8c7b08c7d5dacf03c02656fc53ff562718df68b3c9c

The existing portable distribution includes an extensive licenses directory.
renode-license is MIT with Antmicro notice; tlib-license explicitly identifies
LGPL2.1 code based on libqemu. Retain the whole notice collection when restoring
this package. MIT for Renode alone does not describe all bundled .NET/native/plugin
dependencies. No exact matching tlib source revision/source-offer mapping was found
in this inspection. That remains a concrete source-compliance gap, not proof of
infringement or a claim the runtime cannot legally be delivered.

## Delivery distinction

User's private restoration is not public release, but private delivery is not a
blanket exemption from license conditions. It is possible to deliver open-source
runtimes without vendor firmware when applicable notices and source obligations
are fulfilled. Do not characterize firmware-free as forbidding QEMU/Renode.
No blanket 'safe redistribution certified' conclusion is supported by this pass.
Prefer exact original portable runtime plus preserved notices and verified source
closure rather than new unrelated binaries. Avoid bundling proprietary guest
kernel, MCU images, rootfs/app images or private credentials under this rationale.
