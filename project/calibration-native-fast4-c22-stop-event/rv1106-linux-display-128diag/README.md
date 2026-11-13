# Explicit 128 MiB display diagnostic

Copied generator from rv1106-linux-display/prepare.py, invoked with
`RV1106_RAM_MB=128 python3 prepare.py`. Original kernel bytes unchanged;
only diagnostic DT memory and boot ELF wrapper differ. Original input locations
remain those listed in prepare.py. This directory does not replace the stable
64 MiB profile or establish physical board RAM capacity.

Use with QEMU `-m 128M` or UART launcher `--memory 128`. Combined-session evidence
and exact launch are documented in rv1106-at32-link/REAL-APPLICATION.md.
