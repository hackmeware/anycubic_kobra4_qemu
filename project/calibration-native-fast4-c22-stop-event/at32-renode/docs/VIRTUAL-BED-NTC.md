# Proven bed ADC connection

The original native host configured main MCU v1.3.3 ADC object OID18 at0x20002A58, with ADC1 channel8. The firmware capability table maps this to PB0. The original UI separately identified shutdown25 as “Hotbed NTC error detected” (10123). This proves the bed temperature input role for this firmware/configuration combination.

The runtime object accumulates8 samples, accepts raw sums15205..32309, and has consecutive error limit4. A steady integer ADC sample must therefore be1901..4038. The previous unconnected input returnedzero. `verified-adc-configuration.json` records the extracted fields; `tools/inspect_adc_objects.py --main` can reproduce this extraction from a96KiB SRAM dump. Dumps themselves are not bundled.

After main platform loading, `include @scripts/virtual-bed-ntc.resc` adds an explicit virtual sensor to ADC1/channel8. It uses the existing analytic thermal environment with illustrative100kΩ at25°C, beta3950K and4.7kΩ pullup. Default25°C gives raw3911. Those circuit/curve parameters are not recovered PCB calibration; the host's interpreted temperature may differ. The corresponding nozzle profile uses its independently proven ADC0.

The virtualbed has illustrative200W heater power,600J/K heat capacity,1.5W/K conductance and150°C simulation cap. Its heater/fan inputs are not connected because their actual board output roles have not yet been proven. Therefore this profile presently provides an unpowered ambient sensor, not a complete printer heating loop.

Open/short injections remain available: `sysbus.virtualBedNTC SetSensorFault "open"` yields4095, `"short"` yields0, `"none"` restores the model. Neither firmware nor host safety checks are disabled. This profile has no connection to physical heaters.
