# Original motor firmware status query

The original unmodified motor image now answers its real serial status protocol after an explicitly modeled timer/ADC calibration sequence. No command reply, calibration state, status word or firmware instruction is replaced.

Run `python3 tests/run-original-status.py /path/to/motor_firmware_v1.6.01_20260313.bin`. The runner checks the known firmware hash, boots at0x08008000, enables the documented board-clock/RTC hypotheses, loads the stationary-current plant, and lets firmware run0.5 virtual seconds. It sends command0x25 with axis masks1,2,4,7 through the virtual576000-baud USART2 wire. An explicit idle notification follows a1ms virtual gap.

The test verifies response CRCs, four ACKs and that each command0x26 response matches the actual status halfwords at0x20000C00/0C10/0C20. CPU fault registers are also checked. In the recorded run all three status words are **0x0040**, not zero. The all-axis response is `7e26080207400040004000e642`. This is proof of real firmware execution and state-derived replies, not proof that the motor system is healthy.

A separate captured command8 TMC IFCNT read also produced the original firmware response, including OID2, register2 value0 and ACK. The calibration test with zero ADC inputs retains the actual calibration-fault bit0x0008; stationary mid-supply inputs2048 remove that bit but leave0x0040. The remaining condition is under investigation and must not be hidden.

Limits remain: exact FCES silicon is unverified; the clock/RTC initialization profile is a documented hypothesis; flash programming/erase, complete PWM semantics, encoder feedback and mechanical motor dynamics are not fully modeled. The stationary-current plant is not a closed-loop motor model. Main and nozzle model packages were not modified by this motor-only extension.

A repeat using `--no-idle` also passes, showing no explicit idle notification is required for these requests. Remaining0x0040 was traced to the original current-response test during state6: after1000 control iterations, measured transformed current must exceed half the requested target. Constant calibrated2048 input means zero current, so this condition fails legitimately. A PWM-coupled electrical plant is required; the query test deliberately reports that failure.

## Generic stationary R/L plant

Use `--electrical --no-idle` to select the explicit generic electrical plant and allow1s startup. This repeat verifies genuine status words0000 for all three motors, while checking response CRCs/ACKs against actual firmware RAM exactly as before. Evidence is under `tests/verified/original-status-rl/`. The plant does not read or write those status words; they are read only by the independent test harness after requests. Default24V/2Ω/3mH/500counts-per-amp parameters were not adjusted to a firmware acceptance threshold. Zero-supply and open-winding firmware tests retain0040. This validates a generic stationary electrical feedback loop, not rotor/encoder dynamics or the physical board.
