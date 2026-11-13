# Original motor MCU integration (opt-in)

Add `--motor-image /absolute/path/motor_firmware_v1.6.01_20260313.bin` to
`scripts/run_combined.sh`. The default two-MCU launch is unchanged. Requires
`--virtual-baud`; the combined launcher already specifies 576000.

The additional independent Renode process executes the original motor image at
0x08008000, using `motor-renode/scripts/load.resc`, `board-clock-and-rtc.resc`,
and `generic-stationary-rl.resc`. The motor is allowed one virtual second of
startup before QEMU starts. Main USART2 and motor USART2 are joined by a
byte-transparent local PTY bridge. Both receiving UARTs use virtual-time baud
adapters without enlarging their hardware FIFO. There is no gateway response
replacement and no firmware patch.

The electrical model is explicitly generic: stationary RL coils, 24 V, 2 ohm,
3 mH, 500 ADC counts/A. It derives current from firmware PWM outputs. It does
not model rotor motion, encoders or printer mechanics. Board clock/RTC and
silicon assumptions remain those documented in motor-renode. Separate Renode
and QEMU clocks are not synchronized in deterministic lockstep.

`--motor-plant zero-current` selects the earlier stationary ADC fixture for a
negative comparison. The unchanged original firmware reports real faults in
that fixture. No resulting status is suppressed or changed by this bridge.

Evidence files: main-motor-tx.bin and motor-tx.bin preserve the two directions;
motor-bridge.json reports direction byte counts and relay failures;
motor-status.bin is the 48-byte motor state region, not a full memory dump;
motor-cpu-faults.bin holds CFSR/HFSR. The native host console and framebuffer
remain authoritative for application outcome. A “Printer is ready” log line
alone is not proof of successful initialization, because prior runs logged it
after shutdown.

`python3 tests/test_pty_bridge.py` verifies all byte values in both directions.

## First full-stack observation

`test-results/three-mcu-electrical` records a 90-second native/UI session. The
native application initialized X/Y/Z, UI received `state:ready`, and the final
actual framebuffer showed the first-run language selection screen. The
native `/tmp/shutdown.log` check found no file. Extruder GCONF initialization
still logged error 11820, so this is not proof all peripherals are complete.

All captured motor request/response CRCs validate. The native status request
was `7e6225020103173c`, response `7e26080103100800080000122b`. These bytes must
not be described as the isolated all-zero status test: the native application
has already sent configuration/control traffic, and its returned status fields
are different. The motor CPU CFSR/HFSR were zero. Relay transferred 4216 bytes
main→motor and 3808 bytes motor→main with no reported relay error.

Use `scripts/decode_motor_frames.py capture.bin` (add `--response` for motor
replies) to validate complete captures. It validates frames and lists command
IDs, but deliberately does not invent vendor status-bit meanings.

## Full-stack negative control

`test-results/three-mcu-zero-current` uses the same unchanged original host and
three MCU images, but selects `--motor-plant zero-current`. The real motor
status response is `7e26080103400840084000a23b` (all three fields retain bit 0x40).
Native UI logs report codes 12003/12004/12005, and the final original framebuffer
reads “Z-axis unresponsive, please check if the connection cable is properly
connected”, CODE 12005. Motor CFSR/HFSR remain zero. This verifies electrical
fault propagation through actual firmware and UI, not a fabricated fault panel.

The host still reports `state:ready` in that negative case; it is therefore
not a sufficient success criterion. The positive electrical run lacks these
axis-error dialogs. Neither result proves motion, homing or printing.

## Nozzle driver overlay

For the optional virtual extruder TMC2209, add
`--nozzle-setup-commands tests/nozzle-ntc-tmc.commands` (use the correct path
relative to your current directory). This loads both the nozzle NTC and the
GPIO-level TMC2209 diagnostic device. It does not create extruder mechanics.
The full original three-MCU test `three-mcu-nozzle-tmc` completed 75 seconds:
extruder GCONF 11820 was absent, UI reported ready and the shutdown-file check
was absent. The no-network Wi-Fi initialization failure remains expected.
