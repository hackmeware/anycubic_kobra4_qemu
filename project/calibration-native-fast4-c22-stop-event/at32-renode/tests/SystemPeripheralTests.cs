// Independent register/clock tests running in Renode, not a host-side reimplementation.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.AT32;
using Antmicro.Renode.Peripherals.IRQControllers;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    public class SystemTests : IDoubleWordPeripheral, IKnownSize
    {
        public SystemTests(AT32CRM crm, AT32ADC adc, NVIC nvic) { this.crm = crm; this.adc = adc; this.nvic = nvic; }
        public long Size { get { return 4; } }
        public void Reset() { }
        public uint ReadDoubleWord(long offset) { return 0; }
        public void WriteDoubleWord(long offset, uint value) { }
        private void Equal(ulong actual, ulong expected, string label)
        { if(actual != expected) throw new Exception(label + ": expected " + expected.ToString("X") + ", got " + actual.ToString("X")); checks++; }
        public string Run()
        {
            checks = 0; crm.Reset(); adc.Reset();
            Equal(crm.SystemFrequency, 8000000, "CRM reset HICK"); Equal(crm.ReadDoubleWord(0), 0x83, "CRM CTRL reset");
            Equal(crm.ReadDoubleWord(8), 0, "CRM flags reset");
            crm.WriteDoubleWord(0, 0); Equal(crm.ReadDoubleWord(0) & 3, 3, "Active HICK cannot disable");
            crm.WriteDoubleWord(4, 1); Equal(crm.ReadDoubleWord(4) & 12, 0, "HEXT switch waits ready");
            crm.WriteDoubleWord(8, 0x800); crm.WriteDoubleWord(0, 0x10001);
            Equal(crm.ReadDoubleWord(4) & 12, 4, "HEXT source ready"); Equal(crm.SystemFrequency, 12000000, "HEXT frequency");
            Equal(crm.IRQ.IsSet ? 1u : 0u, 1, "HEXT stable IRQ");
            crm.WriteDoubleWord(8, 0x80800); Equal(crm.ReadDoubleWord(8) & 8, 0, "HEXT flag W1C");
            Equal(crm.IRQ.IsSet ? 1u : 0u, 0, "HEXT stable IRQ clear");
            crm.WriteDoubleWord(0, 1); Equal(crm.ReadDoubleWord(0) & 0x30000, 0x30000, "Active HEXT cannot disable");
            crm.WriteDoubleWord(4, 0); crm.WriteDoubleWord(0, 1);
            // PLL external input is disabled: PLL enable alone must not imply lock.
            crm.WriteDoubleWord(4, 0x10002); crm.WriteDoubleWord(0, 0x1000001);
            Equal(crm.ReadDoubleWord(0) & 0x2000000, 0, "PLL needs input clock");
            Equal(crm.ReadDoubleWord(4) & 12, 0, "PLL switch waits lock");
            // Official SDK enum PLL_MULT_40 = 39: high=2, low=7. HEXT/2 = 6MHz.
            uint pll40 = 0xC01F0002;
            crm.WriteDoubleWord(4, pll40); crm.WriteDoubleWord(0, 0x1010001);
            Equal(crm.ReadDoubleWord(0) & 0x2020000, 0x2020000, "PLL and HEXT stable");
            Equal(crm.SystemFrequency, 240000000, "PLL40 240MHz"); Equal(crm.AHBFrequency, 240000000, "AHB 240MHz");
            Equal((ulong)nvic.Frequency, 240000000, "NVIC clock follows AHB");
            crm.WriteDoubleWord(4, pll40 | 0x80 | 0x400 | 0x2800);
            Equal(crm.AHBFrequency, 120000000, "AHB divide2"); Equal(crm.APB1Frequency, 60000000, "APB1 divide2"); Equal(crm.APB2Frequency, 30000000, "APB2 divide4");
            crm.WriteDoubleWord(0, 1); Equal(crm.ReadDoubleWord(0) & 0x3030000, 0x3030000, "Active PLL and source cannot disable");
            crm.AttachReset(adc, 0xC, 9); adc.WriteDoubleWord(4, 0x20); crm.WriteDoubleWord(0xC, 0x200);
            Equal(adc.ReadDoubleWord(4), 0, "Peripheral reset rising edge");
            adc.WriteDoubleWord(4, 0x20); crm.WriteDoubleWord(0xC, 0x200); Equal(adc.ReadDoubleWord(4), 0x20, "Reset callback edge only");
            crm.WriteDoubleWord(0xC, 0); crm.WriteDoubleWord(0xC, 0x200); Equal(adc.ReadDoubleWord(4), 0, "Reset callback subsequent assertion");
            crm.WriteDoubleWord(8, 0x1F00); crm.WriteDoubleWord(0x20, 1); crm.WriteDoubleWord(0x24, 1);
            Equal(crm.ReadDoubleWord(8) & 0x13, 0x13, "PLL LEXT LICK ready flags");
            Equal(crm.IRQ.IsSet ? 1u : 0u, 1, "Combined oscillator IRQ");
            crm.WriteDoubleWord(8, 0x1F1F00); Equal(crm.ReadDoubleWord(8) & 31, 0, "All oscillator flags W1C");
            Equal(crm.IRQ.IsSet ? 1u : 0u, 0, "Combined oscillator IRQ clear");
            crm.WriteDoubleWord(0x20, 0); crm.WriteDoubleWord(0x24, 0);
            Equal(crm.ReadDoubleWord(0x20) & 3, 0, "LEXT disable clears stable");
            Equal(crm.ReadDoubleWord(0x24) & 3, 0, "LICK disable clears stable");
            // ADC calibration, gated triggers, ordinary sequence and completion clear.
            adc.WriteDoubleWord(8, 0x5E0000); Equal(adc.ReadDoubleWord(0), 0, "Disabled ADC does not convert");
            adc.SetChannelValue(3, 1234); adc.SetChannelValue(4, 2345);
            adc.WriteDoubleWord(0x34, 3); adc.WriteDoubleWord(4, 0x20); adc.WriteDoubleWord(8, 0xD);
            Equal(adc.ReadDoubleWord(8) & 0xC, 0, "ADC calibration complete");
            adc.WriteDoubleWord(8, 0x400001); Equal(adc.ReadDoubleWord(0) & 2, 0, "ADC trigger requires selection and enable");
            adc.WriteDoubleWord(8, 0x5E0001); Equal(adc.ReadDoubleWord(0) & 0x12, 0x12, "ADC start and conversion flags");
            Equal(adc.ReadDoubleWord(8) & 0x400000, 0, "ADC software trigger self-clear");
            Equal(adc.IRQ.IsSet ? 1u : 0u, 1, "ADC conversion IRQ"); Equal(adc.ReadDoubleWord(0x4C), 1234, "ADC channel value");
            Equal(adc.ReadDoubleWord(0) & 2, 0, "ADC data read clears CCE"); Equal(adc.IRQ.IsSet ? 1u : 0u, 0, "ADC data read clears IRQ");
            adc.WriteDoubleWord(8, 0x5E0801); Equal(adc.ReadDoubleWord(0x4C), 1234 << 4, "ADC left alignment");
            adc.WriteDoubleWord(8, 1); adc.WriteDoubleWord(0, 0); adc.WriteDoubleWord(8, 1);
            Equal(adc.ReadDoubleWord(0x4C), 1234, "ADC repeated enable trigger");
            adc.WriteDoubleWord(4, 0x120); adc.WriteDoubleWord(0x2C, 1 << 20); adc.WriteDoubleWord(0x34, 3 | (4 << 5));
            adc.WriteDoubleWord(8, 0x5E0001); Equal(adc.ReadDoubleWord(0x4C), 2345, "ADC sequence last channel");
            // Single-channel watchdog must ignore an unselected channel.
            adc.WriteDoubleWord(0, 0); adc.WriteDoubleWord(4, 0x800243); adc.WriteDoubleWord(0x24, 1000); adc.WriteDoubleWord(0x34, 4);
            adc.WriteDoubleWord(8, 0x5E0001); Equal(adc.ReadDoubleWord(0) & 1, 0, "ADC watchdog channel selection");
            adc.WriteDoubleWord(0x34, 3); adc.WriteDoubleWord(8, 0x5E0001); Equal(adc.ReadDoubleWord(0) & 1, 1, "ADC watchdog violation");
            adc.ReadDoubleWord(0x4C); Equal(adc.IRQ.IsSet ? 1u : 0u, 1, "ADC watchdog IRQ persists data read");
            adc.WriteDoubleWord(0, 0x1E); Equal(adc.IRQ.IsSet ? 1u : 0u, 0, "ADC watchdog W0C");
            adc.WriteDoubleWord(4, 0x80); adc.WriteDoubleWord(0x38, 3 << 15); adc.WriteDoubleWord(0x14, 1500);
            adc.WriteDoubleWord(0, 0); adc.WriteDoubleWord(8, 0x20F001);
            Equal(adc.ReadDoubleWord(0) & 0xE, 0xE, "ADC preempt sets PCCS PCCE CCE");
            Equal(adc.ReadDoubleWord(0x3C), (uint)(65536 + 1234 - 1500), "ADC signed preempt offset");
            Equal(adc.IRQ.IsSet ? 1u : 0u, 1, "ADC preempt IRQ"); adc.ReadDoubleWord(0x4C);
            Equal(adc.IRQ.IsSet ? 1u : 0u, 1, "ADC ordinary data read leaves preempt IRQ");
            adc.WriteDoubleWord(0, 0x1B); Equal(adc.IRQ.IsSet ? 1u : 0u, 0, "ADC preempt W0C");
            return "SYSTEM TESTS PASS: " + checks;
        }
        private readonly AT32CRM crm; private readonly AT32ADC adc; private readonly NVIC nvic; private int checks;
    }
}
