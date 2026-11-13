// SPDX-License-Identifier: MIT
// Original nozzle.robot boot/clock assertions, runnable without Robot dependencies.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.CPU;
using Antmicro.Renode.Peripherals.AT32;
using Antmicro.Renode.Peripherals.Nozzle;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    public class NozzleFirmwareClockTests : IBusPeripheral
    {
        public NozzleFirmwareClockTests(IMachine machine, CortexM cpu, AT32CRM crm, AT32UART uart, ClockedSTM32Timer timer)
        { this.bus=machine.GetSystemBus(this);this.cpu=cpu;this.crm=crm;this.uart=uart;this.timer=timer; }
        public void Reset() { checks=0; }
        private void Check(bool ok,string label) { if(!ok) throw new Exception(label); checks++; }
        public string Boot()
        {
            Check(cpu.PC.RawValue==0x08005088,"idle PC");
            Check(bus.ReadDoubleWord(0xE000ED28)==0,"CFSR clear");
            Check(bus.ReadDoubleWord(0xE000ED2C)==0,"HFSR clear");
            Check(bus.ReadDoubleWord(0xE000ED08)==0x08004000,"vector table");
            Check(uart.BaudRate==571428,"UART baud");
            Check(crm.SystemFrequency==72000000,"system clock");
            before=bus.ReadDoubleWord(0xE0001004);
            return "NOZZLE FIRMWARE BOOT CHECKED";
        }
        public string PrepareTimer()
        {
            Check(unchecked(bus.ReadDoubleWord(0xE0001004)-before)==7200000,"DWT 0.1 second delta");
            Check(timer.Frequency==72000000,"APB doubled timer clock");
            timer.WriteDoubleWord(0x28,71); timer.WriteDoubleWord(0x2C,99);
            timer.WriteDoubleWord(0x14,1); timer.WriteDoubleWord(0x10,0);timer.WriteDoubleWord(0,1);
            return "NOZZLE FIRMWARE TIMER PREPARED";
        }
        public string Finish()
        {
            Check((timer.ReadDoubleWord(0x10)&1)==1,"timer update after 0.2ms");
            return "NOZZLE FIRMWARE CLOCK TESTS PASS: "+checks;
        }
        private readonly IBusController bus;
        private readonly CortexM cpu;
        private readonly AT32CRM crm;
        private readonly AT32UART uart;
        private readonly ClockedSTM32Timer timer;
        private uint before; private int checks;
    }
}
