# Motor saved power-down query investigation

Original motor command 0x22 is registered to 0x0800e3a8; response command 0x23 serializes three 32-bit values from 0x20003644, 0x20003648 and 0x2000364c. The command ignores its input payload. Command0x24 is the paired setter at 0x0800e3dc.

These are not arbitrary driver configuration defaults. The 16-byte record at0x20003640 is loaded by0x0800d3a4 from persistence key `PowerDown_data` (string0x0801ee9c). Startup calls that loader at0x08018040. Function0x080089e8 snapshots the three values from per-motor position helper0x0801230c. The helper incorporates timer-derived movement when active and returns a signed32-bit value. Units/axis order are not yet established. Reading these values does not establish that axes are homed or currently at those positions.

A fresh original-image execution under the provisional24MHz/LICK profile for0.3seconds yielded16zero bytes at0x20003640, PC0x0801b696. This observation alone may be before the persistence loader and is not proof of a real device's stored values. Persistence flash writes are unsupported in that profile. No user flash/persisted positions have been imported.

Any diagnostic response must explicitly represent a blank virtual saved-power-down record, or a record deliberately configured for that simulation. It must not silently claim measured machine position, calibration, or successful homing. Unsupported setter/motion semantics must remain visible.

The currently packaged gateway is frozen and unchanged during package testing. Implementation is pending confirmation of initialized blank-store behavior.

## Explicit diagnostic implementation

Source gateway now exposes `BlankPowerDownRecord`, defaultfalse. Only explicit opt-in permits command0x22 to return command0x23 containing12zero bytes (three saved32-bit words), with normal transport acknowledgment. The original handler ignores the request payload; the diagnostic query does too. It neither executes nor acknowledges the paired setter0x24 or motion commands. External disconnection still prevents all replies. `PowerDownQueries` records accepted reads and resets with diagnostic counters.

Use `scripts/blank-powerdown-record.resc` after `scripts/virtual-tmc-gateway.resc` only when a synthetic blank saved-record state is intended. The main gateway profile does not enable it. This does not establish actual printer power-loss recovery state. The V3 frozen snapshot predates this opt-in extension.

The serializer `%d` case at0x0800e71e emits four bytes least significant first. The query's three-word layout is directly evidenced by0x0800e3b4–0x0800e3c8. All31 expanded Renode checks pass. Native integration accepted two queries and logged `powerloss_step 0 0 0`.

Native combined run `rv1106-at32-link/test-results/tmc-powerdown-nozzle` completed: main36reads/30writes, zero CRC rejects, two saved-record queries. With the independently modeled nozzle PA3 waveform, extruder12reads/10writes and zero rejected frames were also observed. Next unsupported request was motor0x17, leading to host msgtag146 timeout and shutdown10111. This is not printer readiness. Both0x22 requests had payload00; the original handler ignores this byte. Raw main-to-motor capture is decoded in `native-motor-capture.json`.

## Next runtime-status blocker (not implemented)

After the optional image-version reply, the native host reaches reported state:ready, but the displayed UI raises CODE10002. Captured requests include ten command0x25 payload0103 queries, plus one command0x2e and0x2f. Command0x25 handler0x0800efd8 reads the16-bit status words at0x20000c00/0x20000c10/0x20000c20. Selectors1/2/4 return the first/second/third word respectively in command0x26 after OID/selector bytes; other selectors return all three words. These are runtime fault flags, mutated by helpers0x08011724 (set),0x0800d928 (clear) and checked by0x0800a338. Motor state transitions consume them at0x0800de58/0x0800df4a. Returning zero would falsely assert fault-free modeled feedback, so this query remains unsupported until the relevant motor behavior is modeled. Late repeat `tmc-version-late` confirms the exact chain: CheckXYZConnectionLineStatusRequest at33.870s, host msgtag151 timeout at38.875s, RPC error reply at38.943s, UI CODE10002 at38.958s. Native host remains ready; the connection-status check has not passed.
