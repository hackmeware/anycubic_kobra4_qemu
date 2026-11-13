# Validation record

Validated 2026-11-04 with supplied RV1106 QEMU 9.2.0 and Renode 1.17.0
portable .NET, Linux x86_64. Packages in adjacent directories as documented.

- `python3 firmware/make_test.py`: generated independent ARMv7/Thumb binaries.
- `python3 scripts/run_link.py --test`: passed 256 transformed byte round trips.
- `python3 tests/run.py`: passed two additional full 256-byte exchanges and the
  negative control (MCU transformation deliberately changed, RV mismatch detected).
- Python `py_compile`: all three Python sources passed.

Successful logs: `test-results/roundtrip-1/` and `roundtrip-2/`.
Expected failure logs: `test-results/wrong-response/`.

The negative control is an intentional test failure that the test runner requires.
QEMU's log ends with SIGTERM because the launcher stops the infinite test firmware
loop after the result. That is expected cleanup, not a crash.

Additional original-application tests are documented in REAL-APPLICATION.md:
- Two fresh runs identify the original main MCU as v1.3.3 with 5 ms host-byte pacing.
- Native app advances to the separate nozzle MCU, which is not present.
- Direct transport and 1 ms pacing did not complete application identification.
- Five passive frame-decoder unit tests pass, including corrupt-CRC rejection.

No physical wiring, actual baud-rate behavior, flow-control correctness,
deterministic timing, physical host serial, or full printer operation validated.

Latest thermistor baseline: all four original-firmware open/short tests passed.
Normal bed/nozzle inputs clear ADC errors, revealing the remaining TMC response
timeout; see CURRENT.md. Virtual-baud round trips and addressless wire integration
passed. Python sources compile, and five passive frame-decoder unit tests pass.
