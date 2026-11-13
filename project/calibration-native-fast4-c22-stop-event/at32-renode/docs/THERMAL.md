# Virtual thermal board environment

`peripherals/VirtualPrinterThermal.cs` is a **purely virtual** heater/NTC environment for firmware experiments. It never controls external hardware. Its values are illustrative defaults, not identified characteristics of any printer, heater, thermistor, or board. It is not a thermal-runaway protection or hardware-safety validation model.

## Attach an environment

Load `AT32F403A_System.cs` before `VirtualPrinterThermal.cs`. Create one environment for each independent heater/sensor pair. Every environment must have a different ADC channel unless intentionally testing competing writers. Addressless `@ sysbus` registration makes the object available to the Renode monitor; `@ none` alone does not instantiate an unreferenced peripheral.

```repl
adc: AT32.AT32ADC @ sysbus 0x40012400
virtualThermal: AT32.VirtualPrinterThermal @ sysbus
    adc: adc
    channel: 1
    heaterPowerWatts: 40.0
    heatCapacityJoulesPerKelvin: 20.0
    conductanceWattsPerKelvin: 0.2
    ambientCelsius: 25.0
    nominalResistanceOhms: 100000.0
    betaKelvin: 3950.0
    nominalCelsius: 25.0
    pullResistanceOhms: 4700.0
    thermistorToGround: true
    fanConductanceWattsPerKelvin: 0.3
```

Channel 1 here is an **example**, not a printer pin assignment. Route a verified GPIO output to `virtualThermal@0` for the heater and optionally `virtualThermal@1` for the fan. Both are active-high by default; `heaterActiveHigh` and `fanActiveHigh` allow inverted wiring. No GPIO, ADC channel, or timer alternate-function mapping is inferred by this model. A source must actually deliver GPIO edges; a register-only PWM peripheral does not generate them automatically.

## Dynamics and units

The environment advances from a Renode `LimitTimer`, using emulated time, not host sleep or wall time. The default update window is 10 ms (`updateMicroseconds: 10000`). GPIO edges accumulate active time at 1 microsecond timer resolution. The completed window's mean heater/fan duties feed:

```
C dT/dt = P duty - (G + Gfan fanDuty) (T - Tambient)
```

The implementation uses the exact first-order exponential solution for **constant window-average** duty and conductance, with a linear solution when total conductance is zero. It does not integrate the detailed heating trajectory inside a PWM window. Shorter update windows reduce this approximation for slow PWM and rapidly varying fan signals.

Defaults: P = 40 W, C = 20 J/K, G = 0.2 W/K, ambient = 25 C. These yield a 100 s time constant and a 225 C full-duty equilibrium without fan. Fan duty 1 adds 0.3 W/K loss. Ambient is constant and is also the lower temperature bound. Thermal coupling between models, airflow dynamics, sensor lag, noise, radiation, changing material properties, and power-supply sag are not represented.

## Sensor conversion and faults

The NTC uses `R = Rnom exp(B(1/Tkelvin - 1/TnomKelvin))`. With `thermistorToGround: true`, the ADC divider fraction is `R / (Rpull + R)`; false uses the complementary fraction for a thermistor connected to the high rail with a resistor to ground. The result is rounded to the nearest ADC code and supplied to `AT32ADC.SetChannelValue`. `adcMaximum` defaults to 4095 and may be 1–4095, reflecting the attached AT32 ADC's 12-bit limit.

Monitor examples:

```text
sysbus.virtualThermal TemperatureCelsius
sysbus.virtualThermal ADCValue
sysbus.virtualThermal SetSensorFault "open"
sysbus.virtualThermal SetSensorFault "short"
sysbus.virtualThermal SetSensorFault "none"
```

An open sensor gives full-scale ADC for the ground-connected thermistor and zero for the high-side thermistor. A short gives the opposite rail. Fault injection changes sensing only; the physical temperature continues evolving. These are ideal divider faults, not a model of every possible wiring failure.

## Synthetic input and observability

`SetDutyCycle 0.5` and `SetFanDutyCycle 0.5` select direct duty input independently and ignore subsequent GPIO callbacks for that input. `UseGPIOInputs` exits direct mode and sets both inputs inactive until their next GPIO callback. `Reset` represents an MCU reset: it disables heater/fan commands, returns GPIO mode with inactive inputs and enables automatic updates, but retains temperature, sensor faults, and overtemperature/latch history. `ColdReset` explicitly starts a new scenario at ambient, clears faults and trip history, and resets the update count.

`LastHeaterDuty`, `LastFanDuty`, `Updates`, `AutomaticUpdates`, `SensorFault`, `Overtemperature`, and `HeaterLatchedOff` are visible in the monitor. For deterministic synthetic experiments, `SetAutomaticUpdates false` then `Advance 100` advances 100 seconds at the current direct/GPIO input levels. `Advance` refuses to run while the automatic timer is enabled. Changing update mode discards an incomplete PWM window.

The default environmental maximum is 400 C (`maximumCelsius`). Reaching it clamps temperature, logs a warning, records `Overtemperature`, and, by default, latches heater power off until ColdReset. Setting `stopHeaterAtMaximum: false` retains heater input while clamping. The trip is an environment bound, **not modeled firmware protection**. Trip state remains observable and injected sensor faults remain at their fault rail, so a clamp never masks an open or short sensor. Do not interpret failure to exceed this bound as evidence of safe firmware. No automatic latch reset is provided other than explicit ColdReset.

## Validation

Run `tests/run-thermal.sh` using the same Renode runtime as the main suite. This loads and exercises the actual C# peripheral, not a host-language reproduction:

- 29 independent checks cover the analytic time constant, full/half-duty equilibrium, fan cooling, passive cooldown, ADC conversion including a hand-calculated 100 C reference, high/low-side open/short faults, ADC-register delivery, invalid input rejection, trip visibility and latching, warm/cold reset behavior, and zero-loss heating.
- A 100 ms Renode virtual-time run checks the actual LimitTimer's update count and temperature.
- A 2.5 ms high / 7.5 ms low GPIO cycle checks measured 25% duty and resulting temperature at the 10 ms boundary.

No user firmware heater control loop or real board routing is established by these standalone tests.
