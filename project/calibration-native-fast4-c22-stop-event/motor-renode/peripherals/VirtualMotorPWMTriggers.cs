// SPDX-License-Identifier: MIT
using Antmicro.Renode.Core;
namespace Antmicro.Renode.Peripherals.AT32
{
    // Digital clock/trigger wiring only. No current or rotor simulation.
    public class VirtualMotorPWMTriggers : IPeripheral
    {
        public VirtualMotorPWMTriggers(AT32Timer tmr2, AT32Timer tmr3, AT32Timer tmr4)
        {
            // Firmware SMCR0x16; RM14-12: TMR3/TMR4 IS1 = TMR2.
            tmr2.TriggerOutput.Connect(tmr3, 17);
            tmr2.TriggerOutput.Connect(tmr4, 17);
        }
        public bool Connected => true;
        public void Reset() { }
    }
}
