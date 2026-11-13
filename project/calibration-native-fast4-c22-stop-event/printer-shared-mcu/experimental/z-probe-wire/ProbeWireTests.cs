// SPDX-License-Identifier: MIT
// CPU-free electrical test observer. Stimulus belongs to run_tests.py, not a probe model.
using System;
using System.Globalization;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.GPIOPort;
namespace Antmicro.Renode.Peripherals.PrinterExperimental
{
    public sealed class ProbeWireTests : IPeripheral, IGPIOReceiver
    {
        public ProbeWireTests(IMachine machine, BaseGPIOPort gpio, int pin)
        {
            this.machine=machine; this.gpio=gpio; this.pin=pin;
            gpio.Connections[pin].Connect(this,0);
            last=gpio.Connections[pin].IsSet;
        }
        public void Reset() { } // Preserve observations while the GPIO under test resets.
        public void OnGPIO(int number, bool value)
        {
            calls++;
            if(last!=value) { edges++; last=value; }
        }
        public string Check(bool expected, string label)
        {
            var actual= gpio.Connections[pin].IsSet;
            if(actual!=expected)throw new Exception(label+": resolved pad="+actual+", expected="+expected);
            checks++; return "WIRE CHECK PASS: "+label;
        }
        public string CheckEdges(int expected, string label)
        {
            if(edges!=expected)throw new Exception(label+": edges="+edges+", expected="+expected);
            checks++; return "WIRE CHECK PASS: "+label;
        }
        public string Status(string label)
        {
            return "WIRE STATUS: "+label+" pad="+gpio.Connections[pin].IsSet+" calls="+calls+" edges="+edges+
                " ns="+(machine.ElapsedVirtualTime.TimeElapsed.TotalSeconds*1000000000).ToString("R",CultureInfo.InvariantCulture);
        }
        public string Result() { return "PROBE WIRE TESTS PASS: "+checks; }
        private readonly IMachine machine;
        private readonly BaseGPIOPort gpio;
        private readonly int pin;
        private bool last;
        private int calls,edges,checks;
    }
}
