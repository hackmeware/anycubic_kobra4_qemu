# Current snapshot: 2026-11-13

Firmware-free Linux x86-64 host package including original QEMU/Renode runtimes, all three MCU models, SWU import, persistence, native offline UI and existing headless SLIRP profiles. **Not a completed printer emulator; full calibration is not yet proven.** Firmware must be imported locally.

New explicit options: `--host-runtime-profile no-history-autosave` and `--synthetic-thermal-rate 4`. Defaults remain the original runtime and thermal rate 1. See [current instructions and test limits](docs/CURRENT-SNAPSHOT.md). Older sections below retain development history and may describe superseded checkpoints; this current status takes precedence.

---

# Snapshot status: 2026-11-13

Complete firmware-free host package with bundled QEMU/Renode runtimes and SWU preparation tools. Import your authorized firmware locally before starting. Native GUI boot and the 3600-second model contract were observed in current testing; **full calibration is NOT completed/proven**. Synthetic thermal/motion/sensor profiles remain experimental. The existing native UI profile requires `--network off`; SLIRP remains available through existing headless network profiles. No experimental LIS allocation optimization is included.

New: `--profile r9-calibration --virtual-limit-seconds 3600` configures the absolute shared virtual-time bound. Default: 719 seconds; host `--seconds` remains separate. See `docs/LONGRUN-INTEGRATION.md`. The application instructions there describe the development overlay; this full snapshot already contains those changes, so do not reapply it.

---

> Current R9 integration status: see [R9-INTEGRATION](docs/R9-INTEGRATION.md) and CHECKPOINT-STATUS.json. Full calibration is not yet verified.

# Kobra 4 Emulator: private firmware-free recovery snapshot

**Work in progress for Linux x86-64. No Anycubic firmware included. Do not flash this onto a real printer.**

This package combines the existing R9 model tree with a new local SWU importer, a bounded launcher and SLIRP USB Ethernet. It includes the matching host runtimes already used by the private project, along with their license notices. It is not yet a publicly released or anonymized GitHub package.

> **New combined development snapshot:** The UI candidate and opt-in persistence are now integrated into the launcher. All 116 tests pass (31 import, 46 launcher/persistence, 19 network, 20 UI). The persistence tests use synthetic writers, including the actual namespace/supervisor process chain. **No actual guest run of this combined snapshot yet**, and neither a persisted print job nor a working UI has been demonstrated. The older boot evidence below applies to the unchanged version 1 baseline, not automatically to these new changes.

## New optional modes (still requiring guest-side verification)

- `--ui --profile three-mcu-scalar --network off` launches the reconstructed UI experiment with local-only VNC. UI operation with Internet access or port forwarding is refused. Without `--ui`, the launcher remains headless. No automatic touch or calibration actions.
- `--instance /absoluter/privater/instanzordner --execute` uses a dedicated persistent disk instead of the temporary QEMU overlay. Without `--instance`, the previous behavior remains unchanged. The imported base remains unchanged; each run still requires a fresh `--output`.
- A disk whose state is uncertain after process termination explicitly requires `--recover-instance`; the complete previous disk state is retained and never automatically discarded. Profile or source changes are refused. Details: `docs/persistence-candidate.txt`.
- Guest-side `sync`/orderly shutdown is not yet integrated. A full backup is therefore retained on every restart without a confirmed guest sync. This requires additional storage. There is no guarantee for data still buffered in guest RAM, and no VM/MCU RAM snapshot.
- New UI logs are created exclusively under a fresh `/data/kobra-runs/<Lauf-ID>/` directory. Earlier default logs are not overwritten. Their actual persistence inside the guest has not yet been tested.
- `--stop-when-ui-observed` is a test option for ending a run early once a UI connection, a nonuniform actual guest frame and an associated local viewer have been demonstrated. It proves neither complete calibration nor completion of the full run duration.

## Historically verified tests (version 1 baseline)

- The actual supplied entry point, `prepare.py`, interactively decrypted the real K4_1.2.1.3 SWU and strictly verified it against known hashes; the complete local import finished with exit code 0 and seven independently checked output files.
- Created the system and app filesystems, empty userdata/data filesystems and a new synthetic 512 MiB GPT disk. File contents, modes and symlinks were compared against R9; ext4 and GPT CRCs were checked. The new filesystem metadata explicitly does not constitute a byte-for-byte restoration of old images.
- Booted the new SWU-derived medium through the new launcher using QEMU/Renode runtimes that had actually been saved and downloaded again: Linux/BusyBox and the main/nozzle MCUs, exit code 0 after 48.92 seconds, all inputs unchanged.
- USB Ethernet on the previous private R9 medium: generic-xhci, cdc_ether, eth0 and DHCP 10.0.2.15/24 with SLIRP restrict=on. The final package test confirms an isolated local-only configuration and actual QEMU forwarding listeners bound exclusively to 127.0.0.1. No router or DNS settings were deliberately supplied under restrict=on; no Internet connectivity or DNS resolution is claimed.
- Third MCU: integrated the existing motor add-on. The actual package tree reached Linux/BusyBox with all three MCU models in coupled scalar/lockstep mode. After correcting an unsuitable host CPU budget, the package passed the full 300-second observation: 4,976 coupled steps, Linux ready, exit code 0, unchanged inputs and clean termination. The cause of the earlier process termination remains unproven retrospectively because no signal was recorded. This bounded test also does not demonstrate continuous operation over several days. The add-on is an experimental register model, not a verified representation of the actual motor silicon.

**Not demonstrated:** complete calibration, original UI/app services, actual printing mechanics, Internet/cloud access, persistent guest changes or a resumed VM state. Booting to a Linux shell is not equivalent to a fully calibrated virtual machine.

## Requirements

- Linux x86-64, Python 3.11+, sufficient disk space for several gigabytes of private import and run files.
- Unprivileged Linux user/PID/mount namespaces (`unshare`); an additional network namespace is required for network mode off. The launcher does not modify host security rules or use an unprotected fallback.
- At least approximately 2 GiB of free RAM for the verified two-MCU test, preferably more. The launcher monitors its own process tree using a sampled 4 GiB limit.
- Host programs `mke2fs`, `debugfs` and `e2fsck` from e2fsprogs, plus `mksquashfs` from squashfs-tools. Tested versions and package hashes are listed in `tools/swu/README-PREPARATION.de.txt`. These system tools are not installed by this package.
- Your own legally obtained `K4_1.2.1.3.swu` and its corresponding password. Other firmware versions are not silently accepted.

## Installation and integrity verification

Extract the archive into a new directory while preserving Linux file permissions. The included QEMU/Renode files must remain executable. Do not mix these files with an older run.

```sh
python3 verify.py
mkdir -p ../kobra-private
```

`verify.py` checks files/hashes, not host requirements or the ability to start. Keep private import/run files outside the package directory; they contain firmware and must not be committed to Git.

## Prepare firmware locally

```sh
python3 prepare.py --swu "$HOME/Downloads/K4_1.2.1.3.swu" \
  --output ../kobra-private/import1 --tools-root /
```

The password is requested interactively only. It is not stored, supplied with the package or expected as a command-line argument. The importer does not execute firmware or update scripts, mount images or flash hardware. It aborts if the hash or layout differs. Fresh output directories are mandatory.

Optionally, use `--url` instead of `--swu`, together with `--sha256`. You must specify an exact HTTPS source that you have independently verified; no manufacturer URL is built in. The known SWU hash is:

`ba1938de6241e6918f4ab19450e2a5aa876ceb71a35fc038080026839a975c19`

The actual local import has been verified; the actual download path has not been tested end to end. Hash pinning establishes project continuity here, not independent verification of a manufacturer signature.

## Bounded startup

```sh
python3 start.py --inputs ../kobra-private/import1/prepared/inputs \
  --output ../kobra-private/run1 --seconds 30 --execute
```

Without `--execute`, the same command only generates a launch plan with private boot files. The default is the verified two-MCU diagnostic boot, with networking disabled. After the observation window, the launcher terminates only its own processes. Termination due to a time or memory limit is not a successful test.

`RUN-PLAN.json`, `launcher.log`, `logs/`, `SUPERVISOR.json` and `EXIT.json` document the run. The guest receives a QEMU snapshot overlay: writes are possible, but changes are discarded when the run ends. There is no hidden access to real printers.

### Existing third MCU

For the slower coupled diagnostic mode, the tested observation window of `--seconds 300` is appropriate; 30 host seconds may elapse before Linux becomes ready. The launcher explicitly reports missing guest readiness as an error.

`--profile three-mcu-scalar` selects the existing shared_mcu/printer-shared-mcu add-on, including motor firmware, the USART2 connection and PA8-to-motor-timer coupling. This mode uses the scalar QOM deadline clock with lockstep and icount0; the global quantum selection is explicitly documented. It is not identical to all historical R9 mechanics/heating/sensor calibration profiles. No unsupported claim of complete calibration is made.

## SLIRP and networking

`--network off` is the default. `--network isolated` enables SLIRP with restrict=on; `--network internet` explicitly permits outbound access with restrict=off. No TUN/TAP, host firewall changes or VPN changes. USB Ethernet is not a real Wi-Fi chip and is not silently presented as one.

Optional `--http-port PORT` and `--mqtt-port PORT` bind exclusively to 127.0.0.1 and forward to guest ports 18910 and 9883, respectively. These forwarding rules do not start guest services. Manufacturer services do not start automatically in diagnostic mode. `restrict=on` permits explicitly configured host forwarding; it is not a complete air gap. Successful DHCP alone does not prove isolation. In the actual test, listeners belonging to the QEMU process were verified through socket inodes, rather than merely inspecting arguments. No credentials, cloud registration or TFTP share are included.

## Guest changes

The system reconstruction incorporates the two verified R9 diagnostic changes: a dedicated `/emulation-init.sh` PID 1 for the offline shell, and disabled hardware SDIO initialization. In the app/start.sh extracted from the SWU, only the known Wi-Fi/DHCP lines are replaced in memory, with hashes checked before and after. The kernel and MCU payloads are not binary-patched. The device tree and boot ELF are explicitly diagnostic derivatives.

## Troubleshooting

- **Hash mismatch:** Do not continue with different firmware/runtimes or blindly change pinned values.
- **Namespace unavailable:** Use a suitable Linux environment; do not automatically relax host security settings.
- **Missing tool:** Install e2fsprogs/squashfs-tools through your normal trusted package manager; do not use a firmware ARM program as a host tool.
- **No Linux readiness marker:** Check logs, kernel/DTB, the diagnostic PID 1 hook and the layout.
- **No UI:** Intended in diagnostic mode; do not infer full app/calibration functionality from it.
- **No eth0/DNS:** Review device, DHCP and resolver evidence separately; successful DHCP assignment does not prove Internet connectivity.

## Reproducibility and publication

`project/` contains unchanged selected historical sources and their earlier reports. Older experiment launchers with hard-coded pins in that directory are not the recommended new entry points. `prepare.py` and `start.py` use the new explicit workflow without overwriting historical pins. `FILE-MANIFEST.json` identifies and hashes the exact files supplied.

Existing individual licenses are preserved; the project as a whole is not universally MIT-licensed. Before public redistribution of the runtimes, the complete corresponding dependency sources/notices and the exact Renode-tlib source mapping, among other items, still need to be assembled. This package does not grant a license to the firmware. A separate GitHub package will receive the promised identity/metadata/secrets audit at a later stage. Nothing has been published, and anonymity is not guaranteed.
