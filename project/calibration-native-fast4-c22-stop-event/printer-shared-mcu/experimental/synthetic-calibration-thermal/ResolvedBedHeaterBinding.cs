// SPDX-License-Identifier: MIT
// Explicit hypothetical fixture only; actual PA0 pad level drives input 0.
using System;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.ThermalExperimental
{
    public class ResolvedBedHeaterBinding : IPeripheral, IGPIOReceiver
    {
        public ResolvedBedHeaterBinding(AT32GPIO portA, VirtualPrinterThermal thermal)
        {
            if(portA == null) throw new ArgumentNullException("portA");
            if(thermal == null) throw new ArgumentNullException("thermal");
            if(!thermal.AutomaticUpdates) throw new ArgumentException("Automatic thermal updates are required");
            this.portA = portA; this.thermal = thermal;
            // Setup is paused. Connecting preserves other receivers and does not drive PA0.
            portA.Connections[0].Connect(this, 0);
            InitialLevel = (portA.ReadDoubleWord(8) & 1) != 0;
            Level = InitialLevel;
            thermal.OnGPIO(0, InitialLevel);
            initialized = true;
        }
        public bool InitialLevel { get; private set; }
        public bool Level { get; private set; }
        public ulong ForwardedEdges { get; private set; }
        public ulong ResetObservations { get; private set; }
        public void OnGPIO(int number, bool value)
        {
            if(number != 0) throw new ArgumentOutOfRangeException("number");
            if(!initialized || value == Level) return;
            Level = value; ForwardedEdges++; thermal.OnGPIO(0, value);
        }
        // Do not reassert the old level after the thermal model clears command duty.
        public void Reset() { ResetObservations++; }
        public void WriteStatus(string path)
        {
            File.WriteAllText(path, "{\n  \"binding\": \"resolved main PA0 to thermal input 0, active high\",\n"
                + "  \"hypothetical_fixture\": true,\n  \"initial_level\": " + Flag(InitialLevel) + ",\n"
                + "  \"current_resolved_level\": " + Flag((portA.ReadDoubleWord(8) & 1) != 0) + ",\n"
                + "  \"forwarded_edges\": " + ForwardedEdges + ",\n"
                + "  \"reset_observations\": " + ResetObservations + ",\n"
                + "  \"direct_duty_override_used\": false,\n  \"temperature_override_used\": false\n}\n");
        }
        private static string Flag(bool v) { return v ? "true" : "false"; }
        private readonly AT32GPIO portA;
        private readonly VirtualPrinterThermal thermal;
        private bool initialized;
    }
}
