// SPDX-License-Identifier: MIT
using System;
using System.Reflection;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.AT32;
using Antmicro.Renode.Peripherals.Timers;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    public class TimerFrequencyTests : IPeripheral
    {
        public TimerFrequencyTests(AT32Timer timer, AT32CRM crm) { this.timer = timer; this.crm = crm; }
        public void Reset() { checks = 0; }
        private void Check(bool condition, string label)
        {
            if(!condition) throw new Exception(label);
            checks++;
        }
        private void CheckClocks(ulong expected)
        {
            Check(timer.Frequency == expected, "parent clock");
            var channels = (Array)typeof(STM32_Timer).GetField("channels", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(timer);
            Check(channels.Length == 4, "four compare channels");
            foreach(var channel in channels)
            {
                var child = (LimitTimer)channel.GetType().GetField("Timer").GetValue(channel);
                Check(child.Frequency == expected, "compare clock must match parent: " + child.Frequency + " vs " + expected);
            }
        }
        public string Prepare()
        {
            checks = 0; timer.Reset(); CheckClocks(8000000);
            // Exercise the CRM's STM32_Timer-typed attachment, not only direct writes.
            crm.Reset(); crm.AttachTimer(timer, false);
            crm.HextFrequency = 120000000;
            crm.WriteDoubleWord(0, 0x10001); crm.WriteDoubleWord(4, 1);
            CheckClocks(120000000);
            timer.WriteDoubleWord(0x2C, 12000);
            timer.WriteDoubleWord(0x18, 0x6060); timer.WriteDoubleWord(0x1C, 0x6060);
            for(long offset = 0x34; offset <= 0x40; offset += 4) timer.WriteDoubleWord(offset, 6000);
            timer.WriteDoubleWord(0x20, 0x1111);
            timer.WriteDoubleWord(0x0C, 0x1E);
            timer.WriteDoubleWord(0x14, 1); timer.WriteDoubleWord(0x10, 0);
            timer.WriteDoubleWord(0, 1);
            return "TIMER FREQUENCY PREPARED";
        }
        public string BeforeCompare()
        {
            Check((timer.ReadDoubleWord(0x10) & 0x1E) == 0, "compare must not arrive before 50us");
            return "TIMER BEFORE COMPARE PASS";
        }
        public string AfterCompare()
        {
            Check((timer.ReadDoubleWord(0x10) & 0x1E) == 0x1E, "all compare events arrive by 75us at 120MHz, status=" + timer.ReadDoubleWord(0x10).ToString("X") + " counter=" + timer.Value);
            var before = timer.Value;
            timer.Frequency = 60000000; CheckClocks(60000000);
            Check(timer.Enabled && timer.Value == before, "live clock change preserves enable and counter");
            timer.WriteDoubleWord(0, 0);
            timer.WriteDoubleWord(0x24, 0);
            for(long offset = 0x34; offset <= 0x40; offset += 4) timer.WriteDoubleWord(offset, 6000);
            timer.WriteDoubleWord(0x14, 1); timer.WriteDoubleWord(0x10, 0);
            timer.WriteDoubleWord(0, 1);
            return "TIMER CLOCK CHANGE PREPARED";
        }
        public string BeforeChangedCompare()
        {
            Check((timer.ReadDoubleWord(0x10) & 0x1E) == 0, "changed compare must not arrive before 100us");
            return "TIMER CHANGED BEFORE COMPARE PASS";
        }
        public string Finish()
        {
            Check((timer.ReadDoubleWord(0x10) & 0x1E) == 0x1E, "all compare events arrive by 125us at 60MHz");
            timer.Reset(); CheckClocks(8000000);
            Check(!timer.Enabled, "reset remains disabled");
            return "TIMER FREQUENCY TESTS PASS: " + checks;
        }
        private readonly AT32CRM crm;
        private readonly AT32Timer timer;
        private int checks;
    }
}
