// SPDX-License-Identifier: MIT
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    public class DMATests : IDoubleWordPeripheral, IKnownSize
    {
        public DMATests(IMachine machine, AT32DMA dma, AT32DMA dma2) { bus = machine.GetSystemBus(this); this.dma = dma; this.dma2 = dma2; }
        public void Reset() { }
        public long Size { get { return 4; } }
        public uint ReadDoubleWord(long offset) { return 0; }
        public void WriteDoubleWord(long offset, uint value) { }
        private void Equal(uint value, uint expected, string label)
        { if(value != expected) throw new Exception(label + ": expected " + expected.ToString("X") + ", got " + value.ToString("X")); checks++; }
        private void Configure(uint count, uint source, uint destination, uint control)
        { dma.WriteDoubleWord(8, 0); dma.WriteDoubleWord(4, 15); dma.WriteDoubleWord(12, count); dma.WriteDoubleWord(16, source); dma.WriteDoubleWord(20, destination); dma.WriteDoubleWord(8, control); }
        public string Run()
        {
            checks = 0; dma.Reset();
            bus.WriteDoubleWord(0x20000000, 0x12345678); bus.WriteDoubleWord(0x20000004, 0xABCDEF01);
            Configure(2, 0x20000000, 0x20000100, 0x4ACF);
            Equal(bus.ReadDoubleWord(0x20000100), 0x12345678, "DMA word1");
            Equal(bus.ReadDoubleWord(0x20000104), 0xABCDEF01, "DMA word2");
            Equal(dma.ReadDoubleWord(12), 0, "DMA element count"); Equal(dma.ReadDoubleWord(8), 0x4ACF, "DMA EN stays set");
            Equal(dma.ReadDoubleWord(0), 7, "DMA HT/TC flags"); Equal(dma.Connections[0].IsSet ? 1u : 0u, 1, "DMA IRQ");
            dma.WriteDoubleWord(4, 2); Equal(dma.ReadDoubleWord(0), 5, "DMA clear TC retains HT/global");
            dma.WriteDoubleWord(4, 1); Equal(dma.ReadDoubleWord(0), 0, "DMA clear global clears all");
            Equal(dma.Connections[0].IsSet ? 1u : 0u, 0, "DMA IRQ clears");
            Configure(2, 0x20000000, 0x20000100, 0x48C1);
            Equal(bus.ReadDoubleWord(0x20000100), 0x78, "DMA byte->word zero extend1");
            Equal(bus.ReadDoubleWord(0x20000104), 0x56, "DMA byte->word source stride");
            Configure(2, 0x20000000, 0x20000100, 0x42C1);
            Equal(bus.ReadByte(0x20000100), 0x78, "DMA word->byte truncate1");
            Equal(bus.ReadByte(0x20000101), 1, "DMA word->byte source stride");
            Configure(2, 0x20000000, 0x20000100, 0x5C1);
            Equal(dma.ReadDoubleWord(12), 2, "DMA waits for peripheral request");
            dma.OnGPIO(1, true); Equal(dma.ReadDoubleWord(12), 0, "DMA asserted request drains block"); dma.OnGPIO(1, false);
            Configure(2, 0x20000000, 0x20000100, 0x5E1);
            dma.OnGPIO(1, true); Equal(dma.ReadDoubleWord(12), 2, "DMA circular reload count");
            Equal(dma.ReadDoubleWord(0), 7, "DMA circular completion flags"); dma.OnGPIO(1, false);
            bus.WriteWord(0x20000000, 0xBBCC); dma.WriteDoubleWord(4, 1); dma.OnGPIO(1, true);
            Equal(bus.ReadWord(0x20000100), 0xBBCC, "DMA circular resets address"); dma.OnGPIO(1, false);
            Configure(1, 0x20000001, 0x20000100, 0x4AC9);
            Equal(dma.ReadDoubleWord(0), 9, "DMA unaligned TE/global"); Equal(dma.ReadDoubleWord(8) & 1, 0, "DMA error disables");
            Equal(dma.Connections[0].IsSet ? 1u : 0u, 1, "DMA TE IRQ");
            Configure(1, 0x20000000, 0x20000100, 0x43C9); Equal(dma.ReadDoubleWord(0), 9, "DMA reserved width TE");
            dma.Reset(); Equal(dma.ReadDoubleWord(0), 0, "DMA reset flags"); Equal(dma.ReadDoubleWord(8), 0, "DMA reset control");
            dma.Reset(); Configure(1, 0x20000000, 0x20000100, 0x5C1);
            dma.OnGPIO(125, true); Equal(dma.ReadDoubleWord(12), 1, "DMA fixed unrelated source ignored");
            dma.OnGPIO(101, true); Equal(dma.ReadDoubleWord(12), 0, "DMA fixed ADC1 channel1");
            dma.Reset(); dma.OnGPIO(109, true); dma.OnGPIO(130, true); dma.OnGPIO(109, false);
            dma.WriteDoubleWord(0x20, 1); dma.WriteDoubleWord(0x24, 0x20000000); dma.WriteDoubleWord(0x28, 0x20000100);
            dma.WriteDoubleWord(0x1C, 0x5C1); Equal(dma.ReadDoubleWord(0x20), 0, "DMA fixed source OR survives peer deassert");
            dma.Reset(); dma.WriteDoubleWord(0xA0, 30); dma.WriteDoubleWord(0xA4, 0x1000000);
            Configure(1, 0x20000000, 0x20000100, 0x5C1);
            dma.OnGPIO(101, true); Equal(dma.ReadDoubleWord(12), 1, "DMA flexible disables fixed map");
            dma.OnGPIO(125, true); Equal(dma.ReadDoubleWord(12), 1, "DMA flexible unrelated source ignored");
            dma.OnGPIO(130, true); Equal(dma.ReadDoubleWord(12), 0, "DMA flexible USART3 TX assigned channel1");
            dma.OnGPIO(130, false); Configure(1, 0x20000000, 0x20000100, 0x5C1);
            Equal(dma.ReadDoubleWord(12), 1, "DMA flexible waits selected source");
            dma.WriteDoubleWord(0xA0, 25); Equal(dma.ReadDoubleWord(12), 0, "DMA flexible reassignment sees asserted source");
            dma2.Reset(); dma2.WriteDoubleWord(12, 1); dma2.WriteDoubleWord(16, 0x20000000); dma2.WriteDoubleWord(20, 0x20000100);
            dma2.WriteDoubleWord(8, 0x5C1); dma2.OnGPIO(109, true); Equal(dma2.ReadDoubleWord(12), 1, "DMA2 fixed ignores SPI1 RX");
            dma2.OnGPIO(113, true); Equal(dma2.ReadDoubleWord(12), 0, "DMA2 fixed SPI3 RX channel1");
            dma2.Reset(); dma2.WriteDoubleWord(0xA4, 0x1230000);
            dma2.WriteDoubleWord(0x84, 1); dma2.WriteDoubleWord(0x88, 0x20000000); dma2.WriteDoubleWord(0x8C, 0x20000100);
            dma2.WriteDoubleWord(0x80, 0x5C1); dma2.OnGPIO(135, true);
            Equal(dma2.ReadDoubleWord(0x84), 0, "DMA2 flexible channel7 USART6 RX");
            return "DMA TESTS PASS: " + checks;
        }
        private readonly IBusController bus; private readonly AT32DMA dma, dma2; private int checks;
    }
}
