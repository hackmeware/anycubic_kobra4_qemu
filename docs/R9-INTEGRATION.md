# R9 model integration, experimental

Use the ordinary SWU preparation instructions. No firmware is included. Select `--profile r9-calibration` with your prepared inputs; `--ui` enables native UI monitoring and loopback VNC without automatic touches. Existing diagnostic profiles remain unchanged. The profile adds the recovered exact motor/TMC-autobaud/thermal/Z/LIS templates. Original component hash gates remain unchanged.

Example after firmware preparation:
```sh
python3 start.py --inputs /absolute/private-import/prepared/inputs --output /absolute/fresh-run --profile r9-calibration --ui --seconds 1200 --execute
```
The output directory must not exist. Runs remain bounded. Native calibration is not automatically started; this package does not claim a complete calibration pass. An observation window too short to reach Linux readiness exits nonzero rather than hiding that failure.

The external scalar-step guard refuses the next step at719 seconds of shared Renode time, below the historical720-second bound. This is an explicit stop/error, not successful completion. Existing wall-time, process isolation and RSS limits remain.

The historical R9 adapter selected default .NET host JIT. One real run died with SIGSEGV during setup. This integration retains the current diagnostic starter's single-tier host JIT instead. That changes host compilation policy, not guest frequency. Its stabilization effect remains unconfirmed at packaging time.

The short successful setup probe executed700 lockstep steps (0.700 virtual seconds in30.024 wall seconds), no coordinator error, max measured skew1ns; all7 original inputs unchanged. Linux/UI had not started before the30-second observation expired. A subsequent run's result was lost with the execution workspace. A longer restored offline run is separate and not a package validation claim.

51 starter,21 UI and19 networking regression tests passed after restore. Exact model-component gate passed;86/87 historical runner control files match. The absent old clock-snapshot/runtime/run-baseline wrapper is not used by this starter.

Synthetic model powers240W/800W are experimental4x values, not physical heater ratings. Never apply simulated calibration/PID values to a real printer. Sensor, wiring and mechanical fidelity remain hypotheses.

Existing `--instance` persistence requires a fresh or identically profile-bound instance and exclusive ownership. Never discard old state to bypass that check. Existing SLIRP modes remain; native UI+SLIRP simultaneously is still restricted by the current starter. Internet is not enabled by this R9 example. No claim that all printer functions work.

This is a private development snapshot. Firmware, actual OTP, credentials and private guest media are excluded. Public source/license/privacy review remains separate.
