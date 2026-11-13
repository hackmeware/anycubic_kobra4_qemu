# Experimental shared MCU time domain

`--shared-mcus` is an opt-in diagnostic profile, not a replacement for the
verified independent-process baseline. It requires all three original MCU
images and the576000baud electrical motor profile. The launcher generates
namespace-isolated copies using printer-shared-mcu/tools/generate.py; a source
and generated-file SHA256 manifest is saved with the run.

Main USART2 and motor USART2 connect through a Renode UART hub and virtual
baud adapters. The real main PA8 output connects to motor TMR2 CH1 capture.
All three MCUs run inside one Renode emulation. Linux/QEMU remains a separate
time domain; shared MCU time does not establish QEMU/MCU lockstep.

The model worker's synthetic Cortex-M test verified actual PA8 edges caused
800 captured timer ticks and an actual UART transmission0x5A reached the
other MCU. Original firmware boot tests also passed. These do not establish
full native application compatibility.

The first native run `test-results/shared-mcu-baseline` FAILED main MCU
identification: all3474 injected host bytes reached the serial adapter, but
main emitted only startup and a negotiation packet, and host repeatedly
reopened ttyS3. No motor configuration traffic occurred. Motor status zero
in that run must NOT be treated as initialized healthy status. Investigating
UART FIFO/interruption scheduling and timing; this profile remains diagnostic.

Current initial throughput is approximately21wallseconds per virtual second
under the motor workload. Clock coupling, RX acceptance and actual original
host handshake must be established before any physical-print claim.

## Verified corrected profile (current)

The later `test-results/shared-mcu-10us` run supersedes the failed initial
attempt. A10us global Renode quantum corrected proven receive FIFO scheduling
loss: synthetic64-byte test receives64/64 instead of43/64 at the old quantum,
without changing baud or the hardware FIFO.

With the real PA8 capture connection and current event-time electrical model,
original main/nozzle identification and native X/Y/Z initialization completed.
The original motor replied `7e2608010300000000000040f5`, with all three status
fields zero; final status fields remained zero and motor CPU fault registers
were zero. This is genuine firmware output, not replaced responses. Mode bytes
were040404. Native UI reported ready. The driver/ADC/clock assumptions remain
those documented by the individual model packages.

Use `scripts/run_shared.sh` with DISK, MCU_IMAGE, NOZZLE_IMAGE and MOTOR_IMAGE.
It adds the shared-MCU profile and virtual nozzle TMC2209 to the combined UI
launcher. It does NOT enable the separate experimental clock coordinator.

QEMU/Linux still advances roughly20times faster than these MCU models under
the tested workload: the run recorded7.594seconds shared virtual time versus
154.28seconds host time, including startup. Thus timing-sensitive heating,
motion and printing are not validated by ready UI/status alone. Nozzle60C
trace was diagnostic and does not establish a complete thermal feedback loop.
The prototype `--clock-coupled` path is NOT part of this verified snapshot
profile and must not be enabled by default until independently tested.
