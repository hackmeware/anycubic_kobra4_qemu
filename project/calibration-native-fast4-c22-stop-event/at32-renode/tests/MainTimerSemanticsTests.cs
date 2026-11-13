// SPDX-License-Identifier: MIT
// Mirrors the existing timer-adapter.robot assertions without Robot dependencies.
using System;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.AT32;
using Antmicro.Renode.Peripherals.Bus;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    public class MainTimerSemanticsTests : IPeripheral
    {
        public MainTimerSemanticsTests(AT32Timer tmr2, AT32Timer tmr3, AT32Timer tmr5)
        { this.tmr2 = tmr2; this.tmr3 = tmr3; this.tmr5 = tmr5; }
        public void Reset() { checks = 0; }
        private void Read(IDoubleWordPeripheral timer, long offset, uint expected)
        { if(timer.ReadDoubleWord(offset) != expected) throw new Exception("timer semantics offset " + offset + " expected " + expected); checks++; }
        public string Prepare()
        {
            checks = 0;
            foreach(var timer in new[]{tmr2,tmr3,tmr5}) { timer.Reset(); Read(timer, 0x2C, 0); }
            tmr2.WriteDoubleWord(0x2C, 0x1234); tmr2.Reset(); Read(tmr2, 0x2C, 0);
            tmr2.WriteDoubleWord(0x2C, 0x12345); Read(tmr2, 0x2C, 0x2345);
            tmr2.WriteDoubleWord(0x34, 0x12345); Read(tmr2, 0x34, 0x2345);
            tmr2.WriteDoubleWord(0, 0x400);
            tmr2.WriteDoubleWord(0x2C, 0x12345); Read(tmr2, 0x2C, 0x12345);
            tmr2.WriteDoubleWord(0x34, 0x12345); Read(tmr2, 0x34, 0x12345);
            tmr2.WriteDoubleWord(0x24, 0xFFFE); tmr2.WriteDoubleWord(0, 0x401);
            return "MAIN TIMER SEMANTICS PREPARED";
        }
        public string Finish()
        {
            Read(tmr2, 0x24, 0x10003);
            tmr2.WriteDoubleWord(0, 0); Read(tmr2, 0x24, 3); Read(tmr2, 0x2C, 0x2345); Read(tmr2, 0x34, 0x2345);
            tmr5.WriteDoubleWord(0, 0x400); tmr5.WriteDoubleWord(0x2C, 0x12345);
            Read(tmr5, 0, 0x400); Read(tmr5, 0x2C, 0x12345);
            tmr3.WriteDoubleWord(0, 0x400); tmr3.WriteDoubleWord(0x2C, 0x12345);
            Read(tmr3, 0, 0); Read(tmr3, 0x2C, 0x2345);
            return "MAIN TIMER SEMANTICS TESTS PASS: " + checks;
        }
        private readonly AT32Timer tmr2,tmr3,tmr5;
        private int checks;
    }
}
