# Virtual-time observation and replay

`VirtualPrinterObserver.cs` samples **existing** axis/thermal peripherals. It never generates steps, changes heater duty, writes ADC data, sends printer commands, or accesses a hardware device. Each sample is derived from the actual referenced Renode objects, not from a G-code preview or a prewritten animation.

The observer does not create the missing bridge between firmware GPIO outputs and virtual mechanics. Until that bridge is independently verified, use `sourceLabel` to say `unverified bindings` or `SYNTHETIC TEST`. A trace label is provenance supplied by the scenario author, not automatic attestation that firmware controls the model.

Load after the thermal/mechanics sources and instantiate an addressless object:

```repl
observer: AT32.VirtualPrinterObserver @ sysbus
    axisA: virtualX
    axisB: virtualY
    axisZ: virtualZ
    hotend: virtualHotend
    bed: virtualBed
    sampleMicroseconds: 100000
    maximumSamples: 100000
    sourceLabel: "SYNTHETIC SANDBOX, not a product-firmware print"
```

All component references are optional; missing components emit empty fields, never fake zero values. A/B are motor-space coordinates. They must not be presented as nozzle X/Y without independently verified kinematics, directions, steps/mm, origin and transforms. Extruder position does not itself prove deposition. This viewer deliberately omits a reconstructed 3D object rather than inventing one.

The timer samples every 100 ms of **Renode virtual time** by default. The first sample is at zero. `Reset` clears the trace and timer only; `Stop` ends recording. At `maximumSamples`, recording stops with `CapacityReached=true`; there is no silent ring-buffer overwrite. A 100000-sample trace covers approximately 2.78 virtual hours. Samples can miss motion between samples, although cumulative step/collision counts remain available. Timer callbacks at the same timestamp may sample immediately before or after a thermal update.

Export while the machine is paused for a consistent snapshot:

```text
pause
sysbus.observer WriteCsv "/absolute/path/trace.csv"
```

Then render offline:

```sh
python3 tools/render_virtual_print.py trace.csv trace.html
```

The standalone HTML has no CDN, remote requests or printer-control actions. It plots temperature and axis-position traces, includes ADC, PWM duty, faults, enable and collision states, and provides a playback slider. Playback advances one recorded sample per 100 ms of browser wall time; this is not a live synchronization mechanism. Models in separate Renode processes have independent epochs and clocks; never merge them as synchronized without an explicit synchronization policy.

Validation: `tests/run-observer.sh` executes the actual C# observer and components in Renode. A deliberately synthetic test sends 80 virtual GPIO pulses, applies 50% heater duty, and checks initial state, 11 samples over 1 second, rising temperature, raw step count, CSV width, stop behavior and bounded capacity. `tests/test_observer_render.py` checks missing values, escaping, malformed/non-finite input and strict time order. Generated `tests/results/observer.html` is an illustrative component-test replay, **not an original-firmware print**.
