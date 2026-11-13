// SPDX-License-Identifier: MIT
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    public class IOTests : IDoubleWordPeripheral, IKnownSize
    {
        public IOTests(IMachine machine) { this.machine = machine; }
        public void Reset() { }
        public long Size { get { return 4; } }
        public uint ReadDoubleWord(long offset) { return 0; }
        public void WriteDoubleWord(long offset, uint value) { }
        private void Equal(uint actual, uint expected, string label)
        {
            if(actual != expected) throw new Exception(label + ": expected 0x" + expected.ToString("X") + ", got 0x" + actual.ToString("X"));
            checks++;
        }
        private void Assert(bool actual, string label) { Equal(actual ? 1u : 0u, 1, label); }
        public string Run()
        {
            checks = 0;
            var mux = new AT32IOMUX(machine);
            var gpio = new AT32GPIO(machine, mux, 1);
            var exint = new AT32EXINT(machine);
            var uart = new AT32UART(machine);
            mux.Connections[0].Connect(exint, 0);
            Equal(gpio.ReadDoubleWord(0), 0x44444444, "GPIO reset low");
            Equal(gpio.ReadDoubleWord(4), 0x44444444, "GPIO reset high");
            gpio.WriteDoubleWord(0, 0x44444443); gpio.WriteDoubleWord(0x10, 1);
            Equal(gpio.ReadDoubleWord(8), 1, "GPIO output feedback");
            gpio.WriteDoubleWord(0x10, 0x10001); Equal(gpio.ReadDoubleWord(0xC), 1, "GPIO set wins over clear");
            gpio.WriteDoubleWord(0x14, 1); Equal(gpio.ReadDoubleWord(8), 0, "GPIO clear output");
            gpio.WriteDoubleWord(0, 0x44444448); gpio.WriteDoubleWord(0xC, 1);
            Equal(gpio.ReadDoubleWord(8), 1, "GPIO pull-up");
            gpio.OnGPIO(0, false); Equal(gpio.ReadDoubleWord(8), 0, "GPIO external overrides pull");
            gpio.ReleasePin(0); Equal(gpio.ReadDoubleWord(8), 1, "GPIO release restores pull");
            gpio.WriteDoubleWord(0x18, 0x10001); gpio.WriteDoubleWord(0x18, 1); gpio.WriteDoubleWord(0x18, 0x10001);
            Equal(gpio.ReadDoubleWord(0x18), 0x10001, "GPIO lock sequence");
            gpio.WriteDoubleWord(0, 0x44444443); Equal(gpio.ReadDoubleWord(0) & 15, 8, "GPIO configuration locked");
            gpio.Reset(); gpio.WriteDoubleWord(0, 0x44444443); Equal(gpio.ReadDoubleWord(0) & 15, 3, "GPIO reset unlocks");
            gpio.Reset();
            exint.WriteDoubleWord(0, 1); exint.WriteDoubleWord(8, 1);
            gpio.OnGPIO(0, true); Equal(exint.ReadDoubleWord(0x14), 0, "IOMUX default selects port A");
            mux.WriteDoubleWord(8, 1); Equal(exint.ReadDoubleWord(0x14), 1, "IOMUX selects port B");
            Assert(exint.Connections[0].IsSet, "EXINT individual IRQ");
            exint.WriteDoubleWord(0x14, 1); Assert(!exint.Connections[0].IsSet, "EXINT W1C deasserts");
            exint.WriteDoubleWord(0xC, 1); gpio.OnGPIO(0, false);
            Equal(exint.ReadDoubleWord(0x14), 1, "EXINT falling edge");
            exint.Reset(); exint.WriteDoubleWord(0, (1u << 5) | (1u << 6) | (1u << 10));
            exint.WriteDoubleWord(0x10, (1u << 5) | (1u << 6) | (1u << 10));
            Assert(exint.IRQ5_9.IsSet && exint.IRQ10_15.IsSet, "EXINT grouped outputs");
            exint.WriteDoubleWord(0x14, 1u << 5); Assert(exint.IRQ5_9.IsSet, "EXINT group retains second source");
            exint.WriteDoubleWord(0x14, 1u << 6); Assert(!exint.IRQ5_9.IsSet, "EXINT group clears last source");
            exint.WriteDoubleWord(0, 0xFFFFFFFF); Equal(exint.ReadDoubleWord(0), 0x7FFFF, "EXINT reserved line19");
            exint.Reset(); exint.WriteDoubleWord(0x10, 1); Equal(exint.ReadDoubleWord(0x14), 0, "EXINT disabled interrupt does not pend");
            Equal(uart.ReadDoubleWord(0), 0xC0, "UART reset status");
            uart.WriteChar(65); Equal(uart.ReadDoubleWord(0), 0xC0, "UART disabled RX drops");
            uart.WriteDoubleWord(0xC, 0x202C); uart.WriteChar(65); Assert(uart.IRQ.IsSet, "UART RX IRQ");
            uart.WriteChar(66); Equal(uart.ReadDoubleWord(0), 0xE8, "UART overrun");
            Equal(uart.ReadDoubleWord(4), 65, "UART preserves unread byte");
            Equal(uart.ReadDoubleWord(0), 0xC0, "UART clears RX and overrun after status/data");
            Assert(!uart.IRQ.IsSet, "UART RX IRQ clears");
            uart.InjectReceiveError(3); uart.ReadDoubleWord(0); uart.ReadDoubleWord(4);
            Equal(uart.ReadDoubleWord(0), 0xC0, "UART error clear sequence");
            uart.WriteDoubleWord(0xC, 0x201C); uart.SignalIdle(); Assert(uart.IRQ.IsSet, "UART idle IRQ");
            uart.ReadDoubleWord(0); uart.ReadDoubleWord(4); Assert(!uart.IRQ.IsSet, "UART idle clear");
            uart.WriteDoubleWord(8, 800); Equal(uart.BaudRate, 10000, "UART baud divisor");
            uart.Frequency = 48000000; Equal(uart.BaudRate, 60000, "UART updated APB frequency");
            uint transmitted = 0; uart.CharReceived += b => transmitted = b;
            uart.WriteDoubleWord(4, 90); Equal(transmitted, 90, "UART transmitted byte");
            uart.WriteDoubleWord(0x14, 0xC0); Assert(uart.TxDMA.IsSet, "UART TX DMA request");
            uart.WriteChar(70); Assert(uart.RxDMA.IsSet, "UART RX DMA request");
            uart.ReadDoubleWord(4); Assert(!uart.RxDMA.IsSet, "UART RX DMA clears");
            uart.Reset(); Equal(uart.ReadDoubleWord(0), 0xC0, "UART reset after activity");
            Assert(!uart.IRQ.IsSet && !uart.RxDMA.IsSet && !uart.TxDMA.IsSet, "UART reset outputs");
            return "IO TESTS PASS: " + checks;
        }
        private readonly IMachine machine;
        private int checks;
    }
}
