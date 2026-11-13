// SPDX-License-Identifier: MIT
// Explicit stationary zero-current testbench, not a motor dynamics simulator.
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
namespace Antmicro.Renode.Peripherals.AT32
{
    public class VirtualMotorCurrentCalibration : IPeripheral
    {
        public VirtualMotorCurrentCalibration(AT32Timer tmr2, AT32Timer tmr1, AT32Timer tmr8, AT32ADC adc1, AT32ADC adc2, AT32ADC adc3)
        {
            // RM14-12: TMR1 IS1=TMR2, TMR8 IS0=TMR1. ADC PCTESEL15=TMR8 TRGO.
            tmr2.TriggerOutput.Connect(tmr1, 17);
            tmr1.TriggerOutput.Connect(tmr8, 16);
            tmr8.TriggerOutput.Connect(adc1, 15);
            tmr8.TriggerOutput.Connect(adc2, 15);
            tmr8.TriggerOutput.Connect(adc3, 15);
            this.adc1 = adc1; this.adc2 = adc2; this.adc3 = adc3; Reset();
        }
        public void Reset()
        {
            // Mid-supply current sense at zero current, supported by firmware's
            // 2048 reset offsets and accepted calibration window1675..2420.
            adc1.SetChannelValue(0, 2048); adc1.SetChannelValue(4, 2048);
            adc2.SetChannelValue(5, 2048); adc2.SetChannelValue(6, 2048);
            adc3.SetChannelValue(12, 2048); adc3.SetChannelValue(10, 2048);
        }
        private readonly AT32ADC adc1, adc2, adc3;
    }
}
