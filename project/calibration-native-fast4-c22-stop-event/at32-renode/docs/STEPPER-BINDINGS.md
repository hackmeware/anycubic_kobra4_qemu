# Runtime-configured step/dir outputs

**Later evidence:** see `NATIVE-MOTION-CONFIG.md`. Axis identities/scales are now recovered, and fresh initialized SRAM proves current XYZ execution uses serial motor-command mode2 rather than these GPIO pairs. The observations below describe the earlier snapshot and static GPIO path.

Firmware: main v1.3.3, SHA-256 `9bd702c8a076f29c0ac019cc7c8ea6c7afa52d13580fea04e977e3dce0a5d517`.

The captured initialized SRAM in `rv1106-at32-link/test-results/main-adc-probe/main-sram.bin` contains three objects registered under constructor ID `0x0800599d`:

| OID | STEP | DIR | Semantic axis |
|---|---|---|---|
| 9 | PG5 | PG4 | Not established |
| 12 | PC4 | PA7 | Not established |
| 15 | PC9 | PB1 | Not established |

These are **configured software GPIO identities**, not verified physical connectors. Firmware GPIO ports use A=`0x40010800`, B=`0x40010c00`, C=`0x40011000`, D=`0x40011400`, E=`0x40011800`, F=`0x40011c00`, G=`0x40012000`. PG4/PG5 are not bonded in the assumed RGT7 LQFP64 package. This may indicate a virtual motor signal convention or a board/package assumption issue; it does not establish either interpretation. Do not silently rename these to X/Y/Z, map them to another port, or infer physical wiring.

## Evidence chain

- Constructor `0x0800599c` allocates 0x50 bytes for the OID. Config argument +4 is passed to the ordinary GPIO output helper at `0x080059c2`; returned GPIO base/mask are stored at object +0x20/+0x24 at `0x080059ca–ce`.
- Config argument +8 is passed to the same helper at `0x080059d8`, then stored at object +0x28/+0x2c at `0x080059ea–ee`.
- Step timer callback `0x080067b8` reads object +0x20/+0x24 and XOR-toggles GPIO ODT (+0x0c) at `0x080067bc–c4`. It schedules the two pulse phases using timing and count state.
- Queue handling at `0x08006740` uses a direction-change flag and XOR-toggles the second GPIO descriptor at `0x080067a2–ae`.
- Thus STEP and DIR roles are supported by observed code behavior, not just object ordering. Direction polarity, active STEP edge, steps/mm, mechanical limits, driver-enable source, and axis semantics still need separate evidence.

`firmware-evidence/stepper-config-and-output.asm` preserves the instruction bytes and disassembly. `firmware-evidence/configured-stepper-objects.json` preserves both input hashes and extracted objects. Reproduce with:

```sh
python3 tools/inspect_stepper_objects.py /path/mcu_firmware_v1.3.3_20260311.bin /path/main-sram.bin
```

This tool is read-only, rejects a different firmware hash, validates SRAM pointer ranges and GPIO bitmasks, and deliberately leaves axis identity, steps/mm and enable unassigned. No virtual mechanical objects are automatically attached from these partial bindings.
