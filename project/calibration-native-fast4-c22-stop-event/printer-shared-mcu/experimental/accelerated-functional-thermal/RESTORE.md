# Restoration and verification

Archives contain only this new isolated directory and text source dependency copies under `dependency-snapshot/`. There are no firmware binaries, disk/RAM snapshots, running-state changes, launcher changes, or automatic profile switches.

Extract the archive into an empty staging directory. Verify its `PACKAGE-SHA256SUMS` from the staged `printer-shared-mcu/experimental/accelerated-functional-thermal` directory using `sha256sum -c PACKAGE-SHA256SUMS`. Copy that directory to the snapshot only if the destination is absent, or keep it under a separately named staging directory for review. Do not overwrite an active profile or restore a live thermal state. The saved dependency copies are reference material: do not overwrite central models with them. Compare their hashes against current dependencies before executing tests.

To remove/deactivate this preparation, select no accelerated profile in any future launcher. Nothing in this package activates itself. Preserve any experimental run and its hot/fault/latch state; never reset a warm run to ambient to satisfy a test.
