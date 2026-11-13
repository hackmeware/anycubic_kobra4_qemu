# Sensor30 virtual fixture

Independent r7 fixture with pre-reviewed host-time budget adjustment. Only model change: public ambientCelsius 25 to 30 in nozzle-renode/platforms/virtual-nozzle-recovered-ntc.repl. PB8/PB9 remain UNCONNECTED; heater and fan duties must be zero. No real printer, heater requests, bypasses, motion, printing, calibration completion or hardware accuracy claim. Bed remains baseline and has no passive measurement.

Predetermined acceptance: exact model 30 degrees C; exact ADC 4004; native nozzle integer 29 through 31 inclusive, native bed 23 through 27 inclusive, both targets zero. First default-zero message is preserved and never selected; second message is selected. Prediction proof is retained outside this profile in recovery-evidence/sensor30-prediction.

Read-only shell-first lifecycle, two allowlisted RPCs, transport/parser, generation timing, fresh isolated pycache, resource and cleanup predicates remain inherited. Bounds: outer 1500, inner 1480, active 1468 seconds; capture entry before 1280 seconds; post-Ready budget remains 180 seconds; Legacy 1-second bootstrap, scalar, 1-us quantum, icount 0, autobaud.

Copied historical ambient directory is unchanged and disabled. Its manifest is an inactive historical record, not proof for r4. New sensor30 closure includes that directory and excludes only its own experiment, with its observer, protocol and baseline explicitly included. Wrappers and manifest remain outside their own closure to avoid circular pins; parent pins wrappers after review. No native execution performed during preparation.
