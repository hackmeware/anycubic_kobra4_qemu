# Passive resolved GPIO edge trace

Optional source-only observer `peripherals/PassiveGpioEdgeTrace.cs`, namespace Antmicro.Renode.Peripherals.PrinterShared. No default platform or launcher changes. It observes actual BaseGPIOPort.Connections and reads their current IsSet levels. It never writes GPIO/firmware/registers/plant state, never calls SyncTime, and never advances virtual time.

Create one instance per machine, include the shared source once, then load `edges: PrinterShared.PassiveGpioEdgeTrace @ sysbus { maximumRows: 100000 }`. Before starting emulation, call Observe with a GPIO port object, pin number and unique plain label. For example in the motor machine:

    sysbus.edges Observe sysbus.gpioB 5 "motor_PB5"
    sysbus.edges Observe sysbus.gpioB 4 "motor_PB4"
    sysbus.edges Observe sysbus.gpioB 2 "motor_PB2"
    sysbus.edges Start "/new/path/motor-edges.csv"

In the main machine, observe gpioA6, gpioA15 and gpioC13 with matching descriptive labels and a separate output file. Attach after functional cables are installed; Start snapshots each current resolved level (not a synthetic edge), so previously high signals are represented even if attachment notifications default low. Then every changed value delivered by the GPIO object is logged and flushed, including multiple edges at one timestamp. Existing functional receivers remain attached.

CSV columns: local virtual_time_s, per-file sequence, kind(initial/edge), label, pin, level. Each machine uses its own ElapsedVirtualTime; callbacks delivered through a connector may have a later receiver-local timestamp. Do not demand identical timestamps or conceal connector propagation latency. No timestamp synchronization is introduced by this observer.

RowsWritten includes initial snapshots. EdgeCount counts subsequent actual value changes, including those dropped after capacity. DroppedRows counts omitted initial/edge rows. CapacityReached indicates the configured bound; 1..1000000 rows allowed. Enabled/LastError expose recording state. Stop closes the file only; Reset stops recording without changing pins. Start requires a new file and refuses overwrite. Record failures stop only this observer and retain LastError. Query counters and LastError at finalization; event completeness is claimed only after Start, before Stop/error, with DroppedRows0. Same-level callbacks are not edges. Physical PCB mapping, detector semantics and accepted homing are separate facts.

## Validation

CPU-less test fixture `tests/PassiveGpioEdgeTests.cs`:15 assertions cover actual initial-high snapshot, repeated same level, same-time low/high pulse, existing receiver fan-out, bounded rows/drop accounting, unchanged input/clock, stop/reset and refusal to overwrite.

Two-machine script in evidence/passive-gpio-edge/fanout.resc validates monitor Observe syntax and actual GPIOConnector fan-out. Source and destination each record initial low plus high/low/high/low (four edges), with zero drops. The two edges at source0.001s arrive at destination0.0011s in this test. This is observed delivery behavior, not an invented cable-delay specification. Firmware is not loaded or executed in either test. All GPIO stimulus writes belong solely to the synthetic tests, never the observer.
