# Passive GPIO mapping experiments

`VirtualGPIOTrace.cs` observes existing `AT32GPIO` electrical-level outputs without driving them. It attaches an additional sink, retaining existing sink connections. It assigns no printer roles to pins. Main-board and nozzle-board overlays are respectively `at32-renode/platforms/virtual-gpio-trace.repl` and `nozzle-renode/platforms/virtual-gpio-trace.repl`.

After loading the board and `AT32F403A_IO.cs`, include the tracer C# and load its overlay before starting firmware. During or after execution:

```
sysbus.virtualGPIOTrace Mark "before_bed_only_command"
sysbus.virtualGPIOTrace WriteCsv @/absolute/path/main-gpio.csv
sysbus.virtualGPIOTrace CapacityReached
```

CSV fields: virtual time in microseconds since observer construction, pin, observed electrical level, GPIO configuration nibble, output latch, and event label. Initial attachment and explicit markers snapshot every connected pin. Ordinary rows record actual level changes, suppressing repeated unchanged callbacks. The default cap is one million rows; overflow is visible in `CapacityReached`. `Clear` starts a new bounded recording but retains the running clock. MCU reset records a marker and does not erase earlier evidence.

A configuration nibble's low two bits distinguish input (`0`) from output (`1`–`3`). The upper two bits further distinguish push-pull/open-drain and alternate function. Alternate-function drivers are currently unconnected in the GPIO model: absence of edges on such a pin does not prove it is unused. ADC analog-input levels likewise are not heater evidence. The trace records both configuration and latch to prevent confusing an input pull or configuration transition with a driven output.

## Causal mapping protocol

1. Boot the unmodified local firmware and native host, with known simulated sensor inputs, and capture baseline.
2. Send only the bed target command through the established host interface (for example M140 S35); retain its host acknowledgement and timeline.
3. Return bed target to zero. Repeat the off/on/off transition while nozzle target remains zero.
4. Repeat independently for the nozzle (for example M104 S35), with bed target zero.
5. Correlate command delivery/acknowledgement, firmware peripheral configuration and GPIO changes, preserving both board traces. A single coincident edge is insufficient. Report inhibition/errors rather than assuming a nonchanging candidate must be the heater.
6. Only after causal identification add a separately named heater-input overlay. NTC curve and thermal parameters remain illustrative unless independently established.

No heater-input bindings are supplied by this tracing component. It cannot establish real printer wiring, physical calibration or safety.

## Standalone validation

`tests/run-gpio-trace.sh` loads the real Renode GPIO model and two simultaneous observers. It verifies a 2500 us output pulse, configuration/latch metadata, initial and labeled snapshots, and preservation of both sinks' observations.
