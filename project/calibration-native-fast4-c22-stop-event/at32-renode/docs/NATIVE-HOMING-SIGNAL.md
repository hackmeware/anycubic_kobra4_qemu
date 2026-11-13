# Native homing signal route, recovered 5 November 2026

Read-only static trace of main v1.3.3, SHA256 9bd702c8a076f29c0ac019cc7c8ea6c7afa52d13580fea04e977e3dce0a5d517, loaded at0x08004000. No firmware or wiring changes were made for this finding.

Endstop constructor0x08006444 allocates52 bytes, stores GPIO base at object+0x0c and mask at+0x10, and initializes endstop mode+0x2a to1. Endstop-home handler0x080061c8 checks that mode. Mode2 branches to0x08006254, sends motor command2 at0x0800628a using motor index(+0x29), sample count and polarity, and increments+0x2c.

Crucially, serial arming then rejoins ordinary homing setup at0x0800620c and installs callback0x08006a25. Callback0x08006a24 reads the GPIO input register at [object+0x0c]+8 and tests mask+0x10 against requested polarity. Debounce callback0x080069c8 repeats the same input read; qualified samples call trigger routine0x08006970 at0x08006a12..18. Thus serial mode2 arming does not itself replace GPIO completion sampling.

Motor residual detector evidence is in motor-renode/docs/ROTOR-FEEDBACK-EVIDENCE.md: detector state at0x20003a2c + axis*0x54 +0x50 drives genuine PB5/PB4/PB15 outputs for axes0/1/2. The inspected event path stops trajectory execution through0x08012508 and sets those outputs; the inspected later0x0800d284 portion updates internal state rather than transmitting a serial completion. This scoped finding does not prove absence of every other serial path.

Original host config names mainPA6/PA15 for X/Y. Historical initialized descriptors in firmware-evidence/initialized-endstop-objects.json agree, but actual connector/PCB mapping to motorPB5/PB4 is not established. Do not silently add a physical wiring claim or drive DIAG directly from geometry.

Next passive validation, once real G28 reaches command2: read fresh endstop OID10/13 constructor/object pointers, descriptor+0x0c/+0x10, mode/motor-index+0x24..0x2a and callback+4. Observe referenced IDT bits together with original motor detector+0x50/+0x51, PB5/PB4 transitions and CRC-valid serial traffic. Keep native homing guards intact. If an explicitly assumed virtual cable is later chosen, label the assumption separately from observed board evidence.

## Software correspondence and polarity, 5 November 2026

The strongest software-consistent correspondence is X = serial motion motor index 0 = motor PB5, and Y = serial motion motor index 1 = motor PB4. Original host configuration names X DIAG PA6 and Y DIAG PA15, with no inversion prefix. `firmware-evidence/native-motion-config.json` preserves the recovered configuration and source RAM locations. `NATIVE-MOTION-CONFIG.md` documents native stepper OIDs 9/12 and initialized object+0x45 indices 0/1. Historical endstop OIDs 10/13 and PA6/PA15 descriptors are recorded in `firmware-evidence/initialized-endstop-objects.json`; its SRAM SHA256 is f6ccfc3b6a8000dfa9133c85dd4d20f9f36934adbe46b54b74eb9ea4bef4a596.

TMC UART register addresses are a separate namespace: original X uses address 3 and Y address 1. Do not substitute these for motion motor indices 0 and 1. The motor firmware evidence maps **indices**, not TMC UART addresses, to its detector outputs.

The inspected motor arm/configuration path clears the selected output, and the qualified detector path sets it high. Main home setup stores flag value 3 for requested polarity 1, or 2 for polarity 0. The sampler XORs the low flag bit with the observed input level; equality qualifies the sample. Thus the previously observed X command2 payload [0,4,1] is consistent with an active-high input, and with the original non-inverted DIAG configuration. A fresh capture must still establish the actual request and state in each run. A command request is not evidence of successful detection or homing.

## Proposed assumed virtual cable, not implemented

An optional **assumed non-inverting XY diagnostic cable** could carry motor GPIOB pin 5 to main GPIOA pin 6, and motor GPIOB pin 4 to main GPIOA pin 15. This is a software-consistent simulation scenario, not a verified physical connector or PCB claim. This document adds no executable wiring.

The cable must forward only genuine resolved motor GPIO electrical levels, including both transitions. It must not inspect or convert geometry, motion targets, detector RAM, counters or elapsed time into an endstop level. It must not write firmware state, positions or homed flags. Reset and initialization must not manufacture a pulse. Inspect GPIO configuration before interpreting ODT: the current model distinguishes a latch from the resolved pin level, including alternate-function and open-drain modes. Any required pull or electrical behavior would be a separate explicit assumption, not a reason to force a high level.

Do not cross-connect motor PB4 and PB5. They also appear as inputs in an alternate gated detector path; the proposed cable is only motor-to-main. No Z cable or probe behavior is justified here. A contact scenario changes physical torque and measured current only. A no-contact negative control remains necessary before attributing detection to contact rather than another electrical condition.

## Exact passive capture addresses

Always identify the selected MCU: main and motor share numerical address ranges.

**Motor GPIO:** GPIOB configuration low/high at 0x40010c00/0x40010c04; IDT at 0x40010c08; ODT at 0x40010c0c. Masks are PB5 0x20 (index 0), PB4 0x10 (index 1), PB15 0x8000 (index 2). Preserve configuration alongside both IDT and ODT; latch state alone is insufficient.

**Motor detector and control RAM:**

| Field | Index 0 | Index 1 | Index 2 |
|---|---|---|---|
| Detector record | 0x20003a2c | 0x20003a80 | 0x20003ad4 |
| Event state +0x50 | 0x20003a7c | 0x20003ad0 | 0x20003b24 |
| State +0x51 | 0x20003a7d | 0x20003ad1 | 0x20003b25 |
| Detector path selector byte | 0x2000064c | 0x20000652 | 0x20000658 |
| Alternate-input event byte | 0x2000064d | 0x20000653 | 0x20000659 |
| Event counter word | 0x2000063c | 0x20000640 | 0x20000644 |
| Commutation dispatcher byte | 0x2000000a | 0x2000000b | 0x2000000c |
| Status halfword | 0x20000c00 | 0x20000c10 | 0x20000c20 |

Selector zero follows the residual-event path; nonzero follows the alternate-input event path in routine 0x08018d70. Nonzero byte 0x20003b3f suppresses the inspected XY GPIO assertion. These fields are observations, not values to force. Event state is not necessarily a Boolean: the consumer increments it after handling, and can later clear detector state. Capture transitions rather than interpreting a final zero as proof that no event occurred. Alternate external inputs are motor PB4 for index 0, PB5 for index 1, and PD2 for index 2; their physical meaning and cross-coupling remain unverified.

**Main GPIO:** GPIOA configuration low/high at 0x40010800/0x40010804; IDT at 0x40010808; ODT at 0x4001080c. PA6 mask is 0x40; PA15 mask is 0x8000.

**Main endstops:** OID count byte 0x2000013c; OID table pointer word 0x20000140. Each entry is eight bytes: constructor pointer then object pointer. Resolve OIDs 10/13 afresh and require constructor 0x08006445. Do not reuse historical heap addresses. Capture object callback +4, GPIO base +0x0c, mask +0x10, trigger-object pointer +0x20, flags/sample state +0x24..0x27, motor index +0x29, mode +0x2a, and words +0x2c/+0x30. `tools/inspect_homing_objects.py` provides hash-gated, read-only snapshot parsing. A 96 KiB final dump from `runs/native-precise-contact` had OID count/table 0/0 (SHA256 99d6508df91cacd34066dce23f9b23683e9b0062c64eb5ace995462fc3cad224), so it supplies no initialized runtime mapping evidence.

## Exact binary provenance and offsets

Main `inputs/mcu.bin`: SHA256 9bd702c8a076f29c0ac019cc7c8ea6c7afa52d13580fea04e977e3dce0a5d517, load base 0x08004000. File offsets below are address minus load base, not Thumb-tagged function pointers.

| Main operation | Instruction address | File offset |
|---|---|---|
| Endstop constructor | 0x08006444 | 0x2444 |
| Endstop home handler | 0x080061c8 | 0x21c8 |
| Mode-2 arm serialization call | 0x0800628a | 0x228a |
| Shared sampler setup | 0x0800620c | 0x220c |
| Initial GPIO sampler | 0x08006a24 | 0x2a24 |
| GPIO debounce sampler | 0x080069c8 | 0x29c8 |
| Qualified trigger call | 0x08006a18 | 0x2a18 |
| Trigger routine | 0x08006970 | 0x2970 |

Motor `inputs/motor.bin`: SHA256 76b439293ab08207317007f5179243a0684c1b27668442781bcb2e201ff62661, load base 0x08008000. Instruction evidence is preserved in `motor-renode/firmware-evidence/sensorless-residual-and-gpio.asm`; contextual interpretation is in `motor-renode/docs/ROTOR-FEEDBACK-EVIDENCE.md`.

| Motor operation | Instruction address | File offset |
|---|---|---|
| Residual detector | 0x08019aac | 0x11aac |
| Qualified event store | 0x08019d88 | 0x11d88 |
| Detector/output consumer | 0x08018d70 | 0x10d70 |
| GPIO-set calls | 0x08018e54 / 0x08018e8e | 0x10e54 / 0x10e8e |
| GPIO-clear call | 0x08018478 | 0x10478 |
| Alternate external-input path | 0x08013da0 | 0xbda0 |

GPIO IDT/ODT register behavior is also explicit in `motor-renode/peripherals/AT32F403A_IO.cs` and the main copy. All findings above preserve the distinction between original instructions, saved runtime observations and unverified electrical/board assumptions. Native homing and calibration remain unvalidated.
