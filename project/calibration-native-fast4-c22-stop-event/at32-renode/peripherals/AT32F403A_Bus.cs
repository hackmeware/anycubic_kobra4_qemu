// Functional AT32F403A bus peripherals. Register definitions: Artery RM Rev 2.06,
// chapters 10 (CRC), 13 (SPI), and 11 (I2C); SDK at32f403a_407_{spi,i2c,crc}.h.
// MIT license. Bus operations are synchronous, not wire/baud-cycle accurate.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using Antmicro.Renode.Core;
using Antmicro.Renode.Core.Structure;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.SPI;
using Antmicro.Renode.Peripherals.I2C;

namespace Antmicro.Renode.Peripherals.AT32
{
    // One attached SPI slave, selected by the board's GPIO/CS wiring. 8/16-bit,
    // MSB/LSB first, overrun and polling/interrupt/DMA request flags are modeled.
    // No external-clock slave mode, I2S stream, multimaster collision or CRC frame.
    public class AT32SPI : NullRegistrationPointPeripheralContainer<ISPIPeripheral>, IDoubleWordPeripheral, IWordPeripheral, IBytePeripheral, IKnownSize
    {
        public AT32SPI(IMachine machine) : base(machine)
        {
            passiveMachine = machine;
            IRQ = new GPIO(); DMAReceive = new GPIO(); DMASend = new GPIO(); Reset();
        }
        public GPIO IRQ { get; private set; }
        public GPIO DMAReceive { get; private set; }
        public GPIO DMASend { get; private set; }
        public long Size { get { return 0x400; } }
        public override void Reset()
        {
            ctrl1 = ctrl2 = data = receiveCRC = transmitCRC = i2sctrl = 0;
            status = 2; polynomial = 7; i2sclk = 2; dataRead = false; UpdateInterrupts();
        }
        public uint ReadDoubleWord(long offset)
        {
            switch(offset)
            {
                case 0: return ctrl1;
                case 4: return ctrl2;
                case 8:
                    var result = status;
                    if(dataRead) { status &= ~0x40u; dataRead = false; UpdateInterrupts(); }
                    return result;
                case 12: status &= ~1u; dataRead = true; UpdateInterrupts(); return data;
                case 16: return polynomial;
                case 20: return receiveCRC;
                case 24: return transmitCRC;
                case 28: return i2sctrl;
                case 32: return i2sclk;
                default: this.LogUnhandledRead(offset); return 0;
            }
        }
        public void WriteDoubleWord(long offset, uint value)
        {
            switch(offset)
            {
                case 0:
                    if((ctrl1 & 0x40) != 0 && (value & 0x40) == 0 && RegisteredPeripheral != null) RegisteredPeripheral.FinishTransmission();
                    if((value & 0x2000) != 0 && (ctrl1 & 0x2000) == 0) receiveCRC = transmitCRC = 0;
                    ctrl1 = value & 0xFFFF; break;
                case 4: ctrl2 = value & 0x1E7; break;
                case 8: if((value & 0x10) == 0) status &= ~0x10u; break;
                case 12: Transfer(value); break;
                case 16: polynomial = value & 0xFFFF; break;
                case 28:
                    i2sctrl = value & 0xFBF;
                    if((value & 0x400) != 0) this.Log(LogLevel.Warning, "I2S audio stream is not modeled.");
                    break;
                case 32: i2sclk = value & 0xFFF; break;
                default: this.LogUnhandledWrite(offset, value); break;
            }
            UpdateInterrupts();
        }
        private void Transfer(uint value)
        {
            if((ctrl1 & 0x40) == 0) return;
            if((ctrl1 & 4) == 0) { this.Log(LogLevel.Warning, "External-clock SPI slave transfers are not modeled."); return; }
            var bits = (ctrl1 & 0x800) != 0 ? 16 : 8;
            var lsb = (ctrl1 & 0x80) != 0;
            value &= bits == 16 ? 0xFFFFu : 0xFFu;
            uint response = 0;
            for(var i = 0; i < bits / 8; i++)
            {
                var shift = lsb ? i * 8 : bits - 8 - i * 8;
                var outgoing = (byte)(value >> shift);
                // Renode byte-level SPI peripherals use logical byte values. Bit
                // order changes byte ordering in 16-bit frames, not byte values.
                var incoming = RegisteredPeripheral == null ? (byte)0xFF : RegisteredPeripheral.Transmit(outgoing);
                response |= (uint)incoming << shift;
                RecordPassiveByte(outgoing, incoming, bits, i);
            }
            if((ctrl1 & 0x2000) != 0)
            {
                transmitCRC = FrameCRC(transmitCRC, value, bits, lsb);
                receiveCRC = FrameCRC(receiveCRC, response, bits, lsb);
            }
            if((ctrl1 & 0xC000) != 0xC000)
            {
                if((status & 1) != 0) status |= 0x40;
                else data = response;
                status |= 1;
            }
            status |= 2;
        }
        // Optional passive observation only. Does not register a slave, drive CS,
        // change responses, access guest memory, schedule callbacks or advance time.
        public void StartPassiveByteTrace(string path, int maximumRows = 65536)
        {
            if(passiveWriter != null) throw new InvalidOperationException("Already recording");
            if(maximumRows < 1 || maximumRows > 65536) throw new ArgumentOutOfRangeException("maximumRows");
            var w = new StreamWriter(new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.Read), new UTF8Encoding(false));
            try
            {
                w.WriteLine("# PASSIVE SPI BYTE TRACE v1; logical byte exchange; no chip-select inference; source-local virtual time");
                w.WriteLine("virtual_time_s,sequence,tx_hex,rx_hex,ctrl1_hex,ctrl2_hex,frame_bits,byte_index");
                w.Flush();
            }
            catch { w.Dispose(); throw; }
            passiveMaximum = maximumRows; PassiveRowsWritten = 0; PassiveDroppedRows = 0;
            PassiveLastError = ""; passiveWriter = w;
        }
        public void StopPassiveByteTrace()
        {
            var w = passiveWriter; passiveWriter = null;
            if(w != null) try { w.Dispose(); } catch(Exception e) { PassiveLastError = e.GetType().Name + ": " + e.Message; }
        }
        private void RecordPassiveByte(byte outgoing, byte incoming, int bits, int index)
        {
            if(passiveWriter == null) return;
            if(PassiveRowsWritten >= passiveMaximum) { PassiveDroppedRows++; return; }
            try
            {
                passiveWriter.WriteLine(passiveMachine.ElapsedVirtualTime.TimeElapsed.TotalSeconds.ToString("R", CultureInfo.InvariantCulture)
                    + "," + PassiveRowsWritten + "," + outgoing.ToString("X2") + "," + incoming.ToString("X2")
                    + "," + ctrl1.ToString("X4") + "," + ctrl2.ToString("X4") + "," + bits + "," + index);
                PassiveRowsWritten++; passiveWriter.Flush();
            }
            catch(Exception e) { PassiveLastError = e.GetType().Name + ": " + e.Message; StopPassiveByteTrace(); }
        }
        public bool PassiveTraceEnabled { get { return passiveWriter != null; } }
        public long PassiveRowsWritten { get; private set; }
        public long PassiveDroppedRows { get; private set; }
        public bool PassiveCapacityReached { get { return PassiveRowsWritten >= passiveMaximum && passiveMaximum > 0; } }
        public string PassiveLastError { get; private set; } = "";
        private readonly IMachine passiveMachine;
        private StreamWriter passiveWriter;
        private int passiveMaximum;
        private uint FrameCRC(uint crc, uint value, int bits, bool lsb)
        {
            var mask = bits == 16 ? 0xFFFFu : 0xFFu;
            for(var i = 0; i < bits; i++)
            {
                var bit = (value >> (lsb ? i : bits - i - 1)) & 1;
                var feedback = ((crc >> (bits - 1)) & 1) ^ bit;
                crc = ((crc << 1) ^ (feedback != 0 ? polynomial : 0)) & mask;
            }
            return crc;
        }
        private void UpdateInterrupts()
        {
            IRQ.Set(((ctrl2 & 0x80) != 0 && (status & 2) != 0) || ((ctrl2 & 0x40) != 0 && (status & 1) != 0) || ((ctrl2 & 0x20) != 0 && (status & 0x70) != 0));
            DMAReceive.Set((ctrl2 & 1) != 0 && (status & 1) != 0);
            DMASend.Set((ctrl2 & 2) != 0 && (status & 2) != 0 && (ctrl1 & 0x40) != 0);
        }
        public ushort ReadWord(long offset) { return (ushort)ReadDoubleWord(offset); }
        public byte ReadByte(long offset) { return (byte)ReadDoubleWord(offset); }
        public void WriteWord(long offset, ushort value) { WriteDoubleWord(offset, value); }
        public void WriteByte(long offset, byte value) { WriteDoubleWord(offset, value); }
        private uint ctrl1, ctrl2, status, data, polynomial, receiveCRC, transmitCRC, i2sctrl, i2sclk;
        private bool dataRead;
    }

    // Master-mode, byte-level I2C. START/address/data/STOP and repeated START,
    // 7/10-bit addresses, ACK failure, status-read clearing and IRQs are modeled.
    // No slave mode, SMBus/PEC, arbitration, stretching or real bus timing.
    public class AT32I2C : SimpleContainer<II2CPeripheral>, IDoubleWordPeripheral, IWordPeripheral, IBytePeripheral, IKnownSize
    {
        public AT32I2C(IMachine machine) : base(machine)
        {
            EventIRQ = new GPIO(); ErrorIRQ = new GPIO(); DMAReceive = new GPIO(); DMASend = new GPIO(); Reset();
        }
        public GPIO EventIRQ { get; private set; }
        public GPIO ErrorIRQ { get; private set; }
        public GPIO DMAReceive { get; private set; }
        public GPIO DMASend { get; private set; }
        public long Size { get { return 0x400; } }
        public override void Reset()
        {
            ctrl1 = ctrl2 = own1 = own2 = sts1 = sts2 = clock = lastData = 0; rise = 2;
            statusRead = receiving = waitingAddress = waitingLowAddress = stopped = false;
            tenBitAddress = -1; child = null; tx.Clear(); rx.Clear(); UpdateInterrupts();
        }
        public uint ReadDoubleWord(long offset)
        {
            switch(offset)
            {
                case 0: return ctrl1;
                case 4: return ctrl2;
                case 8: return own1;
                case 12: return own2;
                case 16:
                    if(rx.Count != 0) lastData = rx.Dequeue();
                    if(receiving && !stopped) FillReceive();
                    UpdateDataFlags(); UpdateInterrupts(); return lastData;
                case 20: statusRead = true; return sts1;
                case 24:
                    var result = sts2;
                    if(statusRead)
                    {
                        sts1 &= ~2u; statusRead = false;
                        if(receiving) FillReceive();
                        UpdateDataFlags(); UpdateInterrupts();
                    }
                    return result;
                case 28: return clock;
                case 32: return rise;
                default: this.LogUnhandledRead(offset); return 0;
            }
        }
        public void WriteDoubleWord(long offset, uint value)
        {
            switch(offset)
            {
                case 0:
                    if((value & 0x8000) != 0) { Reset(); ctrl1 = 0x8000; return; }
                    ctrl1 = value & 0x3FFB;
                    if(statusRead) { sts1 &= ~0x10u; statusRead = false; }
                    if((ctrl1 & 1) == 0) { EndTransfer(); sts1 = sts2 = 0; }
                    else
                    {
                        if((value & 0x100) != 0) Start();
                        if((value & 0x200) != 0) Stop();
                    }
                    break;
                case 4: ctrl2 = value & 0x1FFF; break;
                case 8: own1 = value & 0x83FF; break;
                case 12: own2 = value & 0xFF; break;
                case 16: WriteData((byte)value); break;
                case 20: sts1 &= value | ~0xDF00u; break; // error flags clear on writing zero
                case 28: clock = value & 0xCFFF; break;
                case 32: rise = value & 0x3F; break;
                default: this.LogUnhandledWrite(offset, value); break;
            }
            UpdateInterrupts();
        }
        private void Start()
        {
            FlushTransmit(); rx.Clear(); stopped = false; receiving = false;
            waitingAddress = true; waitingLowAddress = false;
            sts1 = (sts1 & 0xDF00) | 1u; sts2 = 3; ctrl1 &= ~0x100u;
        }
        private void WriteData(byte value)
        {
            lastData = value;
            if((ctrl1 & 1) == 0) return;
            if(waitingAddress)
            {
                sts1 &= ~1u; waitingAddress = false; receiving = (value & 1) != 0;
                if((value & 0xF8) == 0xF0)
                {
                    if(receiving && tenBitAddress >= 0) Select(tenBitAddress);
                    else { tenBitAddress = (value & 6) << 7; waitingLowAddress = true; sts1 |= 8; }
                }
                else Select(value >> 1);
            }
            else if(waitingLowAddress)
            {
                waitingLowAddress = false; sts1 &= ~8u; tenBitAddress |= value; Select(tenBitAddress);
            }
            else if(child != null && !receiving && (sts2 & 2) != 0)
            {
                tx.Add(value); sts1 |= 0x84;
            }
            UpdateInterrupts();
        }
        private void Select(int address)
        {
            if(!TryGetByAddress(address, out child))
            {
                sts1 |= 0x400; sts1 &= ~0xC6u; return;
            }
            sts2 = receiving ? 3u : 7u; sts1 |= 2;
            if(!receiving) sts1 |= 0x80;
        }
        private void FillReceive()
        {
            if(child == null || (sts1 & 2) != 0) return;
            var desired = (ctrl1 & 0x400) != 0 || (ctrl1 & 0x800) != 0 ? 2 : 1;
            while(rx.Count < desired)
            {
                var bytes = child.Read(1);
                if(bytes == null || bytes.Length == 0) break;
                foreach(var b in bytes) rx.Enqueue(b);
            }
        }
        private void UpdateDataFlags()
        {
            if(receiving)
            {
                sts1 &= ~0xC4u;
                if(rx.Count > 0) sts1 |= 0x40;
                if(rx.Count > 1) sts1 |= 4;
            }
        }
        private void FlushTransmit()
        {
            if(child != null && tx.Count != 0) child.Write(tx.ToArray());
            tx.Clear();
        }
        private void Stop()
        {
            FlushTransmit();
            if(receiving) FillReceive();
            if(child != null) child.FinishTransmission();
            stopped = true; waitingAddress = waitingLowAddress = false;
            sts2 = 0; sts1 &= ~0x8Fu; ctrl1 &= ~0x200u; UpdateDataFlags();
        }
        private void EndTransfer()
        {
            FlushTransmit(); if(child != null) child.FinishTransmission();
            child = null; rx.Clear(); receiving = false; stopped = true;
        }
        private void UpdateInterrupts()
        {
            var events = (sts1 & 0x1F) != 0 || ((ctrl2 & 0x400) != 0 && (sts1 & 0xC0) != 0);
            EventIRQ.Set((ctrl2 & 0x200) != 0 && events);
            ErrorIRQ.Set((ctrl2 & 0x100) != 0 && (sts1 & 0xDF00) != 0);
            DMAReceive.Set((ctrl2 & 0x800) != 0 && (sts1 & 0x40) != 0);
            DMASend.Set((ctrl2 & 0x800) != 0 && (sts1 & 0x80) != 0);
        }
        public ushort ReadWord(long offset) { return (ushort)ReadDoubleWord(offset); }
        public byte ReadByte(long offset) { return (byte)ReadDoubleWord(offset); }
        public void WriteWord(long offset, ushort value) { WriteDoubleWord(offset, value); }
        public void WriteByte(long offset, byte value) { WriteDoubleWord(offset, value); }
        private uint ctrl1, ctrl2, own1, own2, sts1, sts2, clock, rise, lastData;
        private int tenBitAddress;
        private bool statusRead, receiving, waitingAddress, waitingLowAddress, stopped;
        private II2CPeripheral child;
        private readonly List<byte> tx = new List<byte>();
        private readonly Queue<byte> rx = new Queue<byte>();
    }

    // Programmable 32/16/8/7-bit polynomial CRC, with byte/halfword/word input
    // accesses, input reflection groups, output reflection and programmable seed.
    public class AT32CRC : IDoubleWordPeripheral, IWordPeripheral, IBytePeripheral, IKnownSize
    {
        public AT32CRC() { Reset(); }
        public long Size { get { return 0x400; } }
        public void Reset() { crc = initial = 0xFFFFFFFF; polynomial = 0x04C11DB7; control = common = 0; }
        public uint ReadDoubleWord(long offset)
        {
            switch(offset)
            {
                case 0: return (control & 0x80) != 0 ? Reverse(crc, 32) : crc;
                case 4: return common;
                case 8: return control;
                case 16: return initial;
                case 20: return polynomial;
                default: this.LogUnhandledRead(offset); return 0;
            }
        }
        public void WriteDoubleWord(long offset, uint value)
        {
            switch(offset)
            {
                case 0: Feed(value, 32); break;
                case 4: common = value & 0xFF; break;
                case 8: control = value & 0xF8; if((value & 1) != 0) crc = initial; break;
                case 16: initial = value; break;
                case 20: polynomial = value; break;
                default: this.LogUnhandledWrite(offset, value); break;
            }
        }
        public ushort ReadWord(long offset) { return (ushort)ReadDoubleWord(offset); }
        public byte ReadByte(long offset) { return (byte)ReadDoubleWord(offset); }
        public void WriteWord(long offset, ushort value) { if(offset == 0) Feed(value, 16); else WriteDoubleWord(offset, value); }
        public void WriteByte(long offset, byte value) { if(offset == 0) Feed(value, 8); else WriteDoubleWord(offset, value); }
        private void Feed(uint value, int bits)
        {
            var mode = (control >> 5) & 3;
            if(mode != 0)
            {
                var group = Math.Min(bits, mode == 1 ? 8 : mode == 2 ? 16 : 32);
                uint reversed = 0;
                for(var i = 0; i < bits; i += group) reversed |= Reverse(value >> i, group) << i;
                value = reversed;
            }
            var size = (control >> 3) & 3;
            var width = size == 0 ? 32 : size == 1 ? 16 : size == 2 ? 8 : 7;
            var mask = width == 32 ? uint.MaxValue : (1u << width) - 1;
            for(var i = bits - 1; i >= 0; i--)
            {
                var feedback = ((crc >> (width - 1)) ^ (value >> i)) & 1;
                crc = ((crc << 1) ^ (feedback != 0 ? polynomial : 0)) & mask;
            }
        }
        private static uint Reverse(uint value, int bits)
        {
            uint result = 0;
            for(var i = 0; i < bits; i++) { result = (result << 1) | (value & 1); value >>= 1; }
            return result;
        }
        private uint crc, initial, polynomial, control, common;
    }
}
