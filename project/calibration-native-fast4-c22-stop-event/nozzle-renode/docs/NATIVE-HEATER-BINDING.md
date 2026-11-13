# Optional native PB8 heater binding

This is an explicit opt-in for a later run. No default profile, existing thermal model, launcher, firmware or live run is changed. The normal native 35°C → 0°C passive trace establishes real PB8 PWM and return to low; see `evidence/native-nozzle-control-trace/README.md`. This optional wiring does not by itself prove native heating success or physical-printer accuracy.

## Use only in a new, paused setup

Load the ordinary nozzle platform, then:

```text
include @scripts/virtual-nozzle-recovered-ntc.resc
include @scripts/passive-nozzle-thermal-observer.resc
include @scripts/native-nozzle-heater-binding.resc
```

Use the recovered fixture instead of the legacy fixture, not both. The binding is for a fresh GPIO-controlled fixture with its standard active-high heater polarity and automatic updates. Do not combine it with direct-duty experiments. Load while paused, before firmware starts. It rejects a legacy sensor curve or disabled thermal timer.

The binding adds a sink to PB8 without replacing the observer. It reads the initial **resolved pad level**, not the output latch, and forwards that real level to thermal input 0. Each subsequent PB8 transition forwards only its actual boolean level. The existing timer integrates PWM high time into heat input. It never drives a GPIO, sets a temperature, sets duty directly, edits firmware, advances time, or changes a guard.

`sysbus.nativeNozzleHeaterBinding WriteStatus @binding.json` records explicit heater-bound/fan-unbound status and the actual forwarded-edge count. Record this alongside observer output. The passive observer's existing `actuator_connection_created: false` describes what that observer did; it does **not** mean that no separate binding is loaded.

## PB9 remains observed and unbound

PB9 is the configured extruder heater fan, and the native trace shows it active even at 25°C while target demand is nonzero. It is not a generic nozzle part-cooling fan. Its effect on the heat break/hot end has not been recovered or calibrated. Therefore this profile does not connect PB9 to thermal fan input 1. Modeled fan duty stays zero even if observed PB9 is high.

The existing generic `fanConductanceWattsPerKelvin = 0.3` is not an established heat-break-fan coupling and is inactive in this profile. This missing coupling limits interpretation of temperature transients. Do not label later synthetic thermal behavior as real-printer calibration until appropriate thermal parameters and coupling are supported.

## Existing generic model constants and guards

Nothing in `VirtualPrinterThermal.cs` changes:

- Heater power 40 W; heat capacity 20 J/K; passive conductance 0.2 W/K.
- Ambient 25°C; automatic integration every 10,000 µs.
- Generic model maximum 400°C; stop-at-maximum latch enabled. This is not the native configured temperature limit or a hardware safety model.
- Recovered full sensor curve, 4700 Ω pullup, 12-bit ADC maximum 4095; ground-connected NTC. ADC at physical 25°C is 4023.
- Open/short publish their fault rails; they do not silently repair the sensor or replace physical heat. Original native host/MCU guards still decide whether to stop demand.
- Out-of-table temperature remains visibly invalid rather than clamped to a plausible sensor reading.
- Thermal Reset retains temperature, injected sensor fault and overtemperature latch, clears accumulated duty, and continues the thermal timer. Binding Reset does not reassert a stale high level; subsequent actual GPIO transitions drive the input normally. It never calls ColdReset or UseGPIOInputs.

The generic heat constants above are illustrative. The recovered NTC conversion and verified control pin do not establish heater wattage, heat capacity, heat loss or real cycle accuracy.

## Tests

Run `bash nozzle-renode/tests/run-native-nozzle-heater-binding.sh` for CPU-free tests of the actual C# peripherals. No original firmware or full native emulator is run, no direct duty override is used, and no temperature is injected. Only synthetic GPIO register writes drive the heater; sensor-fault injection is confined to the explicit fault tests.

40 assertions and CSV checks cover:

- Initial low, already-high resolved pad, and high output latch while the pin remains input-low.
- Actual 25% GPIO PWM: one second heats 25°C to about 25.497508°C and changes ADC 4023 to 4021 using the unchanged generic constants.
- Ten seconds of low GPIO cools to about 25.450164°C.
- PB9 high remains visible to the observer while modeled fan duty stays zero.
- Open/short fault rails remain visible independently of physical heating.
- Reset retains physical heat and faults; it does not resurrect a pre-reset high input.
- A deliberately low synthetic test ceiling trips the existing overtemperature latch, which survives reset, cooling and renewed GPIO transitions.

Logs/status/CSV: `nozzle-renode/tests/results/native-nozzle-heater-binding/`.

A future native test must independently verify target acceptance, actual PWM, resulting physical/ADC evolution, accepted normal target-zero clearing, and preserved guards. The gRPC client timeout alone does not clear heater demand.
