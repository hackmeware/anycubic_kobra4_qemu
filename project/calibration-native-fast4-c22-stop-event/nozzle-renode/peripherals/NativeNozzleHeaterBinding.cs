// SPDX-License-Identifier: MIT
// Explicit opt-in virtual PB8 heater wiring. Never connects PB9 or drives GPIO.
using System;
using System.IO;
using Antmicro.Renode.Core;
namespace Antmicro.Renode.Peripherals.AT32
{
    public class NativeNozzleHeaterBinding : IPeripheral, IGPIOReceiver
    {
        public NativeNozzleHeaterBinding(AT32GPIO portB, VirtualPrinterThermal thermal)
        {
            if(portB == null) throw new ArgumentNullException("portB");
            if(thermal == null) throw new ArgumentNullException("thermal");
            if(!thermal.AutomaticUpdates || thermal.SensorCurve != "NTC ZM3863 HNS112HC4570G0")
                throw new ArgumentException("Use the automatically updated recovered-nozzle fixture before attaching PB8");
            this.portB = portB; this.thermal = thermal;
            // Load while the machine is paused. Connect preserves other GPIO sinks.
            // Synchronize from the resolved pad, not the output latch or a made-up low.
            portB.Connections[8].Connect(this, 8);
            InitialPB8Level = (portB.ReadDoubleWord(8) & (1u << 8)) != 0;
            PB8Level = InitialPB8Level;
            thermal.OnGPIO(0, InitialPB8Level);
            initialized = true;
        }
        public bool InitialPB8Level { get; private set; }
        public bool PB8Level { get; private set; }
        public ulong ForwardedEdges { get; private set; }
        public ulong ResetObservations { get; private set; }
        public void OnGPIO(int number, bool value)
        {
            if(number != 8) throw new ArgumentOutOfRangeException("number");
            if(!initialized || value == PB8Level) return;
            PB8Level = value;
            ForwardedEdges++;
            thermal.OnGPIO(0, value);
        }
        // The thermal peripheral owns reset behavior: retain heat/fault/latch and
        // drop its accumulated duty. Do not reassert a pre-reset high input here.
        public void Reset() { ResetObservations++; }
        public void WriteStatus(string path)
        {
            File.WriteAllText(path, "{\n"
                + "  \"binding\": \"resolved nozzle PB8 to virtual thermal heater input 0, active high\",\n"
                + "  \"heater_connected\": true,\n  \"pb9_fan_connected\": false,\n"
                + "  \"initial_resolved_pb8_level\": " + Flag(InitialPB8Level) + ",\n"
                + "  \"current_resolved_pb8_level\": " + Flag((portB.ReadDoubleWord(8) & (1u << 8)) != 0) + ",\n"
                + "  \"forwarded_gpio_edges\": " + ForwardedEdges + ",\n"
                + "  \"reset_observations\": " + ResetObservations + ",\n"
                + "  \"direct_duty_override_used\": false,\n  \"temperature_override_used\": false,\n"
                + "  \"fan_thermal_coupling_modeled\": false,\n  \"physical_printer_accuracy_claimed\": false\n}\n");
        }
        private static string Flag(bool value) { return value ? "true" : "false"; }
        private readonly AT32GPIO portB;
        private readonly VirtualPrinterThermal thermal;
        private bool initialized;
    }
}
