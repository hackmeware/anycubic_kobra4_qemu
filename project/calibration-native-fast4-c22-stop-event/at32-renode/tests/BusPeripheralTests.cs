// Renode-executed behavioral tests; synthetic slaves are test fixtures only.
using System;
using System.Collections.Generic;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.AT32;
using Antmicro.Renode.Peripherals.I2C;
using Antmicro.Renode.Peripherals.SPI;
using Antmicro.Renode.Peripherals.Bus;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    public class SPIEcho : ISPIPeripheral
    {
        public byte Transmit(byte value) { return (byte)(value ^ 0xA5); }
        public void FinishTransmission() { }
        public void Reset() { }
    }
    public class I2CMemory : II2CPeripheral
    {
        public void Write(byte[] bytes) { Written.AddRange(bytes); }
        public byte[] Read(int count = 1)
        {
            var result = new byte[count];
            for(var i = 0; i < count; i++) result[i] = next++;
            return result;
        }
        public void FinishTransmission() { Finishes++; }
        public void Reset() { Written.Clear(); next = 0x30; Finishes = 0; }
        public readonly List<byte> Written = new List<byte>();
        public int Finishes;
        private byte next = 0x30;
    }
    public class BusTests : IDoubleWordPeripheral, IKnownSize
    {
        public BusTests(AT32SPI spi, AT32I2C i2c, AT32CRC crc, I2CMemory memory)
        { this.spi = spi; this.i2c = i2c; this.crc = crc; this.memory = memory; }
        public void Reset() { }
        public long Size { get { return 4; } }
        public uint ReadDoubleWord(long offset) { return 0; }
        public void WriteDoubleWord(long offset, uint value) { }
        private void Equal(uint actual, uint expected, string label)
        { if(actual != expected) throw new Exception(label + ": expected " + expected.ToString("X") + ", got " + actual.ToString("X")); checks++; }
        public string Run()
        {
            checks = 0; spi.Reset(); i2c.Reset(); crc.Reset(); memory.Reset();
            Equal(crc.ReadDoubleWord(0), 0xFFFFFFFF, "CRC reset");
            crc.WriteDoubleWord(0, 0x12345678);
            Equal(crc.ReadDoubleWord(0), 0xDF8A8A2B, "CRC32 word");
            crc.Reset(); foreach(var b in System.Text.Encoding.ASCII.GetBytes("123456789")) crc.WriteByte(0, b);
            Equal(crc.ReadDoubleWord(0), 0x0376E6E7, "CRC32 MPEG2 check vector");
            crc.WriteDoubleWord(20, 0x1021); crc.WriteDoubleWord(16, 0xFFFF); crc.WriteDoubleWord(8, 9);
            foreach(var b in System.Text.Encoding.ASCII.GetBytes("123456789")) crc.WriteByte(0, b);
            Equal(crc.ReadDoubleWord(0), 0x29B1, "CRC16 CCITT check vector");
            crc.WriteDoubleWord(20, 7); crc.WriteDoubleWord(16, 0); crc.WriteDoubleWord(8, 17);
            foreach(var b in System.Text.Encoding.ASCII.GetBytes("123456789")) crc.WriteByte(0, b);
            Equal(crc.ReadDoubleWord(0), 0xF4, "CRC8 check vector");
            crc.WriteDoubleWord(20, 9); crc.WriteDoubleWord(16, 0); crc.WriteDoubleWord(8, 25);
            foreach(var b in System.Text.Encoding.ASCII.GetBytes("123456789")) crc.WriteByte(0, b);
            Equal(crc.ReadDoubleWord(0), 0x75, "CRC7 MMC check vector");
            crc.Reset(); crc.WriteDoubleWord(8, 0xE1);
            foreach(var b in System.Text.Encoding.ASCII.GetBytes("123456789")) crc.WriteByte(0, b);
            Equal(crc.ReadDoubleWord(0) ^ 0xFFFFFFFF, 0xCBF43926, "CRC reflected check vector");
            spi.WriteDoubleWord(0, 0x44); spi.WriteDoubleWord(4, 0x40);
            spi.WriteByte(12, 0x12); Equal(spi.ReadDoubleWord(8), 3, "SPI ready");
            Equal(spi.IRQ.IsSet ? 1u : 0u, 1, "SPI RX IRQ");
            Equal(spi.ReadByte(12), 0xB7, "SPI child exchange"); Equal(spi.IRQ.IsSet ? 1u : 0u, 0, "SPI clear IRQ");
            spi.WriteDoubleWord(0, 0x844); spi.WriteWord(12, 0x1234); Equal(spi.ReadWord(12), 0xB791, "SPI16");
            spi.WriteWord(12, 1); spi.WriteWord(12, 2); Equal(spi.ReadDoubleWord(8) & 0x40, 0x40, "SPI overrun");
            spi.ReadWord(12); spi.ReadDoubleWord(8); Equal(spi.ReadDoubleWord(8) & 0x40, 0, "SPI overrun clear");
            i2c.WriteDoubleWord(4, 0x700); i2c.WriteDoubleWord(0, 0x101);
            Equal(i2c.ReadDoubleWord(20), 1, "I2C START");
            Equal(i2c.EventIRQ.IsSet ? 1u : 0u, 1, "I2C START IRQ");
            i2c.WriteByte(16, 0xA0); Equal(i2c.ReadDoubleWord(20), 0x82, "I2C address");
            Equal(i2c.ReadDoubleWord(24), 7, "I2C master transmitter");
            Equal(i2c.ReadDoubleWord(20), 0x80, "I2C address clear");
            i2c.WriteByte(16, 0x11); i2c.WriteByte(16, 0x22); Equal(i2c.ReadDoubleWord(20), 0x84, "I2C transfer done");
            i2c.WriteDoubleWord(0, 0x101); Equal((uint)memory.Written.Count, 2, "I2C repeated START flush");
            Equal(memory.Written[0], 0x11, "I2C first write"); Equal(memory.Written[1], 0x22, "I2C second write");
            i2c.ReadDoubleWord(20); i2c.WriteByte(16, 0xA1); i2c.ReadDoubleWord(20); i2c.ReadDoubleWord(24);
            Equal(i2c.ReadDoubleWord(20) & 0x40, 0x40, "I2C receive ready");
            i2c.WriteDoubleWord(0, 0x201); Equal(i2c.ReadByte(16), 0x30, "I2C final receive after stop");
            Equal(i2c.ReadDoubleWord(24), 0, "I2C stopped"); Equal((uint)memory.Finishes, 1, "I2C child stop");
            i2c.WriteDoubleWord(0, 0x101); i2c.ReadDoubleWord(20); i2c.WriteByte(16, 0x90);
            Equal(i2c.ReadDoubleWord(20) & 0x400, 0x400, "I2C missing slave NACK");
            Equal(i2c.ErrorIRQ.IsSet ? 1u : 0u, 1, "I2C error IRQ");
            i2c.WriteDoubleWord(20, 0xFBFF); Equal(i2c.ErrorIRQ.IsSet ? 1u : 0u, 0, "I2C clear NACK IRQ");
            i2c.Reset(); i2c.WriteDoubleWord(0, 0x101); i2c.ReadDoubleWord(20);
            i2c.WriteByte(16, 0xF4); Equal(i2c.ReadDoubleWord(20), 8, "I2C10 header");
            i2c.WriteByte(16, 0x50); Equal(i2c.ReadDoubleWord(20), 0x82, "I2C10 low address");
            i2c.ReadDoubleWord(24); i2c.WriteByte(16, 0x66);
            i2c.WriteDoubleWord(0, 0x501); i2c.ReadDoubleWord(20); i2c.WriteByte(16, 0xF5);
            Equal(i2c.ReadDoubleWord(20), 2, "I2C10 repeated read header"); i2c.ReadDoubleWord(24);
            Equal(i2c.ReadDoubleWord(20), 0x44, "I2C receive two buffer flags");
            i2c.WriteDoubleWord(0, 0x201);
            Equal(i2c.ReadByte(16), 0x30, "I2C10 receive first"); Equal(i2c.ReadByte(16), 0x31, "I2C10 receive second");
            Equal(i2c.ReadDoubleWord(20), 0, "I2C receive drained");
            return "BUS TESTS PASS: " + checks;
        }
        private AT32SPI spi; private AT32I2C i2c; private AT32CRC crc; private I2CMemory memory; private int checks;
    }
}
