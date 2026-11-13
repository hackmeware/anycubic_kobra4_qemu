# Startup-error review, revision2

The first native nozzle attempt stopped before any request or heater demand because the observer treated an already-known optional startup configuration error as a printer failure. The record is preserved; no retry was performed during this fix.

The fix is narrowly in the observer: retain all startup errors and classify exactly five source/capture-verified auxiliary startup messages separately, only with matching severity, source-log identifier and native timestamp before ready. Native ready response plus fresh native/model/ADC baseline are still required. Changed, post-ready, unknown, TMC/thermal/shutdown and corrupted errors remain blocking. A late readiness record retroactively revokes any incompatible earlier classification.

Source evidence verifies templates and local return/cleanup only. Full paths/ENOENT come from captured native runs. It does not establish generic configuration failures as benign.

No central files, firmware, model, PID, native guards, heater request schema, clock model, UART timing or TTY setup were changed. See source-evidence.json, source-evidence.asm and captured-startups.json.
