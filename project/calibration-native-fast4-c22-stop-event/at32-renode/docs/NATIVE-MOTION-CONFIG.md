# Native motion configuration and actual execution route

## Evidence, not an invented machine profile

`tools/recover_motion_config.py` reads the known 64MiB native host RAM capture `rv1106-linux-emmc/app-ram.bin`, SHA256 `915424f5dc77b05510509d78b9eab3ad602e6ed6ea2ae707df67bbc02d1ecfaa`. It does not decrypt files, modify RAM, or change firmware. Native execution had already materialized its configuration as strings and ordered maps.

The extractor recovers virtual-to-physical page correspondences from repeated libstdc++ inline-string self-pointers. It then validates map parent pointers, binary-tree order, entry counts and three matching copies of the motion sections. It refuses another RAM hash. Individual virtual node addresses and physical capture offsets are preserved in `firmware-evidence/native-motion-config.json`. The page mapping is a reconstruction from this specific snapshot, not a reusable fixed address delta or kernel page-table dump.

Native console `three-mcu-native-control/console.bin` directly reports X/Y/Z stepper OIDs9/12/15 and endstop OIDs10/13/3. Both old and fresh MCU SRAM give the same software GPIO descriptor pairs.

| Axis | STEP / DIR | Configured steps/mm | Configured travel limits | Homing source |
|---|---|---:|---|---|
| X | PG5 / inverted PG4 | 3200/39 = 82.051282… | -18.5 to280mm | TMC virtual endstop; DIAG PA6 |
| Y | PC4 / PA7 | 3200/39 = 82.051282… | -7.5 to272.5mm | TMC virtual endstop; DIAG PA15 |
| Z | PC9 / PB1 | 3200/8 = 400 | -4 to262mm; home0 | probe:z_virtual_endstop; main PB2 |
| E | nozzlePA12 / inverted PA11 | 3200/4.449 = 719.262756… | Not a bounded carriage | No endstop established |

Kinematics are configured as `cartesian`. Each motor uses16 microsteps and200 full steps per revolution. XYZ configuration declares shared active-lowPC13 enable, but native startup explicitly says virtual enable is used for the three TMC steppers. Thus the configuration string alone is not evidence that a real GPIO enable drives the initialized motor model. Nozzle extruder declares its own active-lowPC13.

These values are original **software configuration**, not measured mechanical calibration. Initial physical positions remain unknown. X/Y are sensorless homing sources, not ordinary mechanical switches. Z's source is a probe, not automatically a minimum switch. Connecting arbitrary position-clamp outputs to these inputs would not validate the original sensor chain.

## Crucial distinction: configured pins versus active serial motion

Fresh `three-mcu-heater-trace/main-sram.bin` (SHA256 `f6ccfc3b6a8000dfa9133c85dd4d20f9f36934adbe46b54b74eb9ea4bef4a596`) shows:

- OID9/12/15 object+0x4d = **2**; object+0x45 = motor index0/1/2 respectively.
- The older pre-motor SRAM had mode1. It cannot describe the final runtime route.
- Main queue handler0x08006820 dispatches mode2 to0x080068ce. This serializes motor command5 through0x0800b700 instead of running its GPIO step callback.
- Direction handler0x08005fe6 sends command4; clock reset0x08006070 sends command17.

Therefore simply adding GPIOG and counting pulses cannot prove XYZ movement in the current full system. The configured PG4/PG5 are unbonded on the assumed RGT7 package and are not treated as physical pins. A deliberately optional software GPIOG shim exists only for mode1 diagnostics; it does not correct or replace the real mode2 route.

`rv1106-at32-link/scripts/inspect_motion_queue.py` passively decodes CRC-valid main-to-motor captures:

- command4: motor index u8, direction level u8.
- command5: index u8, interval u32, count u16, signed interval increment i16, main DWT clock sample u32; little-endian multibyte values.
- command17: motor index u8, clock-reset request.

Instruction evidence: `firmware-evidence/motor-queue-mode2.asm`. The parser reports **transmitted queue requests**, never accepted/executed steps. It does not deduplicate retransmissions, infer unknown initial directions, manufacture homing, or synchronize independent emulator clocks. Heater-trace capture contains zero motion requests, matching native `Must home axis first` rejection. A zero queue count is not a successful print.

## Optional GPIO observation

`VirtualStepperCommandObserver.cs` and `platforms/virtual-commanded-motion.repl` provide bounded passive edge traces with original configured scales. Main overlay adds an isolated GPIOG register object without IOMUX or any physical pin claim. Nozzle overlay observes E. The observers do not drive pins, gate enable, supply endstops, mutate positions, or control hardware. Their reported travel is relative **commanded** travel, not an absolute or physical position.

`bothEdges: true` is explicit in the profiles because runtime stepper flags0x10 indicate the zero-pulse-width both-edge mode. Rising/falling edges and interpreted step events are separately exported. The default generic class remains rising-edge-only. GPIO profiles must not be confused with current main serial mode2. Nozzle's step descriptor and flags are independently visible at OID4/address0x20000790 in the fresh nozzle SRAM.

Reproduction:

```sh
python3 tools/recover_motion_config.py ../rv1106-linux-emmc/app-ram.bin
bash tests/run-commanded-motion.sh
python3 ../rv1106-at32-link/tests/test_motion_queue.py
python3 ../rv1106-at32-link/scripts/inspect_motion_queue.py /path/main-motor-tx.bin
```

The Renode unit test exercises actual GPIO register transitions, both-edge/rising-edge counters, reversal, duplicate high levels, configured scale, reset retention and bounded traces. It is not an original-firmware motion test.
