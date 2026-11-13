# Proven nozzle ADC connection, illustrative thermistor environment

The original native host configures ADC object OID10 at 0x20000730 in original nozzle v1.2.9. The post-configuration SRAM snapshot proves ADC1 channel0, equivalent to PA0 according to the firmware's pin table at 0x0800C524. Eight samples are accumulated, with permitted raw sum 962..32593. For a steady 12-bit input, valid integers are 121..4074. Actual captured sum was zero, explaining shutdown25. The original UI separately labels this event “Extruder NTC error detected” (10124). Thus the input role is supported jointly by runtime configuration, static code and UI, rather than guessed from a generic ADC-capable pin.

`tools/inspect_adc_objects.py` reads a 20KiB dump taken with `dump_file 0x20000000 0x5000 @/path/file.bin`. It is specific to this firmware layout. The dump itself is not distributed; extracted non-sensitive configuration is in `verified-adc-configuration.json`.

## Optional virtual environment

After loading the nozzle platform and before starting the firmware, include `scripts/virtual-nozzle-ntc.resc`. This adds a virtual NTC only to proven ADC0. The illustrative circuit is 100kΩ NTC at25°C, beta3950K,4.7kΩ pullup, NTC to ground. It produces raw3911 at its25°C default ambient. These curve/circuit values are configurable assumptions, NOT recovered calibration or a claim about the actual PCB. The original host may interpret that voltage as a different temperature.

No heater or fan GPIO is connected, because their exact output mapping is not yet proven. The environment therefore remains unpowered at ambient unless explicitly driven through simulation controls. It must not be advertised as a complete closed-loop heater simulation.

The firmware's range/error checks are unchanged. `sysbus.virtualNozzleNTC SetSensorFault "short"` produces0; `"open"` produces4095; both are outside the observed steady-input range. `"none"` restores the modeled sensor. This is a simulator-only component and has no physical device/control connection.

## Adjacent timer coverage

Native configuration also accesses 0x40000800 (F1 TIM4 register layout). The provisional platform now maps Renode's standard STM32_Timer there, with APB timer clock tracking and IRQ30. Observed writes include prescaler17 and period254. This is register/timer coverage, not proof of exact chip identity or routing of timer PWM to a heater/fan GPIO. No thermal drive has been inferred from these writes.
