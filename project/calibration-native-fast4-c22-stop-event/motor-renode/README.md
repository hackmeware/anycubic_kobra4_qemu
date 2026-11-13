# Original motor firmware: experimental Renode profile

This profile executes the supplied, unmodified `motor_firmware_v1.6.01_20260313.bin`. It is an investigation model, not verified silicon emulation or a complete motor/printing simulation.

## What works

- Image load at0x08008000, initial SP0x20015EC0, reset0x08008199.
- Firmware initialization under the explicit clock/RTC hypotheses below.
- Actual timer-trigger chain TMR2→TMR1→TMR8→three ADC injected sequences.
- Original firmware's offset calibration with a virtual stationary-current input fixture. Its counters run naturally; no state bytes are changed.
- Real USART2 replies to command8 and status request0x25, with CRC-valid0x26 responses and ACKs.
- Status replies match actual firmware RAM. The generic stationary R/L plant yields0000 after the original current-response test; the constant zero-current fixture correctly yields0040.

## Current boundary

Two explicit testbenches are available. The constant fixture supplies2048 and correctly fails energized-current response with0040. The generic stationary R/L plant derives currents from actual PWM, supply, resistance and inductance, then supplies ADC samples. With unchanged illustrative24V/2Ω/3mH/500counts-per-amp parameters, the original firmware completes its electrical test and reports0000. Zero supply and open winding still trigger0040. No firmware targets, state or fault words are read or modified by the plant. These are assumed generic electrical values, not recovered board calibration. See `docs/GENERIC-STATIONARY-RL.md`.

There is no demonstrated encoder/mechanical motion or complete third-MCU printer integration. Flash program/erase, complete PWM behavior and alternate-function electrical routing remain incomplete and warn visibly.

## Reproduce the status test

From the workspace, run:

```
python3 motor-renode/tests/run-original-status.py /path/to/motor_firmware_v1.6.01_20260313.bin --no-idle --electrical
```

Omit `--electrical` to reproduce the constant-current baseline and its genuine0040 status. Use `--renode /path/to/renode` if needed. Original firmware is not included. The runner verifies SHA256 `76b439293ab08207317007f5179243a0684c1b27668442781bcb2e201ff62661`, boots the image, requests all motor masks, and checks response CRCs, ACKs, runtime status and CPU fault registers. See `docs/ORIGINAL-STATUS-QUERY.md` and `tests/verified/`.

Manual loading from this directory:

```
include @scripts/load.resc
include @scripts/board-clock-and-rtc.resc
include @scripts/generic-stationary-rl.resc
sysbus LoadBinary @/path/to/motor_firmware_v1.6.01_20260313.bin 0x08008000
cpu VectorTableOffset 0x08008000
```

## Explicit assumptions and identity limits

The user supplied the exact designation **GD32FCESRBT6**, supported by JLC partC9900165928. JLC verifies the catalog name and LQFP64 package, but supplies no datasheet or electrical attributes. It is not established as equivalent to public GD32F303/F305 or GD32C103/C113 devices. The latter families have meaningful RAM/peripheral differences. See `docs/GD32-IDENTITY.md`, `docs/GD32C113-COMPARISON.md` and the catalog-evidence JSON.

This model still uses an AT32-compatible register hypothesis. The optional board setup selects24MHz HEXT and a pre-enabled40kHz RTC oscillator. Those settings allow the image to run but are not independent physical-board measurements. GD32 and AT32 PLL encodings differ; a computed240MHz here is not proof of the actual FCES clock. Inherited AT32 chip-ID/UID tags were removed; flash capacity and its size tag describe model assumptions, not observed silicon.

The initial stack and used RAM near0x20014EAC require more than64KiB in this image. Do not infer FCES capacity from the unrelated F303/F305 “RB” suffix alone. Exact firmware-to-board association and manufacturer documentation remain important.
