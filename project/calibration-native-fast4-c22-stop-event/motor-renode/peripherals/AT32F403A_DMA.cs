// SPDX-License-Identifier: MIT
// Functional AT32F403A DMA. Element-count semantics, independent bus widths.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.GPIOPort;
namespace Antmicro.Renode.Peripherals.AT32
{
    [AllowedTranslations(AllowedTranslation.ByteToDoubleWord | AllowedTranslation.WordToDoubleWord)]
    public class AT32DMA : BaseGPIOPort, IDoubleWordPeripheral, IKnownSize
    {
        public AT32DMA(IMachine machine, bool secondController = false) : base(machine, 7)
        {
            bus = machine.GetSystemBus(this);
            fixedSources = secondController ? dma2Sources : dma1Sources;
            for(var i = 0; i < 7; ++i) channels[i] = new Channel();
            Reset();
        }
        public long Size { get { return 0x400; } }
        public override void Reset()
        {
            base.Reset(); status = select0 = select1 = 0;
            for(var i = 0; i < 7; ++i) channels[i] = new Channel();
            Array.Clear(requests, 0, requests.Length);
            Array.Clear(directRequests, 0, directRequests.Length);
            Array.Clear(sourceRequests, 0, sourceRequests.Length);
        }
        // Explicit channel override inputs 1..7; source inputs 100 + RM source ID.
        // Each source has its own state, so fixed-mode request OR cannot lose a peer's assertion.
        public override void OnGPIO(int number, bool value)
        {
            if(number >= 1 && number <= 7)
            {
                directRequests[number - 1] = value; RefreshRequests();
                if(value) Transfer(number - 1);
                return;
            }
            var source = number - 100;
            if(source <= 0 || source >= sourceRequests.Length)
            { this.Log(LogLevel.Warning, "Invalid DMA request input {0}", number); return; }
            sourceRequests[source] = value;
            RefreshRequests();
            if(value) for(var i = 0; i < 7; ++i) if(IsSourceMapped(i, source)) Transfer(i);
        }
        private bool IsSourceMapped(int channel, int source)
        {
            if((select1 & 0x1000000) != 0)
            {
                var selected = channel < 4 ? (select0 >> (channel * 8)) & 255 : (select1 >> ((channel - 4) * 8)) & 255;
                return selected != 0 && selected == source;
            }
            return Array.IndexOf(fixedSources[channel], source) >= 0;
        }
        private void RefreshRequests()
        {
            for(var channel = 0; channel < 7; ++channel)
            {
                requests[channel] = directRequests[channel];
                if((select1 & 0x1000000) != 0)
                {
                    var source = channel < 4 ? (select0 >> (channel * 8)) & 255 : (select1 >> ((channel - 4) * 8)) & 255;
                    requests[channel] |= source != 0 && sourceRequests[source];
                }
                else foreach(var source in fixedSources[channel]) requests[channel] |= sourceRequests[source];
            }
        }
        public uint ReadDoubleWord(long offset)
        {
            if(offset == 0) return status;
            if(offset == 4) return 0;
            if(offset == 0xA0) return select0;
            if(offset == 0xA4) return select1;
            int index, reg;
            if(!Decode(offset, out index, out reg)) { this.LogUnhandledRead(offset); return 0; }
            var ch = channels[index];
            switch(reg) { case 0: return ch.Control; case 4: return ch.Count; case 8: return ch.Peripheral; default: return ch.Memory; }
        }
        public void WriteDoubleWord(long offset, uint value)
        {
            if(offset == 0) { this.Log(LogLevel.Warning, "Write to DMA read-only status"); return; }
            if(offset == 4)
            {
                for(var i = 0; i < 7; ++i)
                {
                    var mask = (value >> (i * 4)) & 15;
                    if((mask & 1) != 0) mask = 15;
                    status &= ~(mask << (i * 4));
                    var flags = (status >> (i * 4)) & 14;
                    if(flags == 0) status &= ~(1u << (i * 4));
                    UpdateIRQ(i);
                }
                return;
            }
            if(offset == 0xA0 || offset == 0xA4)
            {
                if(offset == 0xA0) select0 = value; else select1 = value & 0x1FFFFFF;
                RefreshRequests();
                for(var i = 0; i < 7; ++i) if(requests[i]) Transfer(i);
                return;
            }
            int index, reg;
            if(!Decode(offset, out index, out reg)) { this.LogUnhandledWrite(offset, value); return; }
            var ch = channels[index];
            if(reg == 0)
            {
                var wasEnabled = (ch.Control & 1) != 0;
                // Hardware requires disable before changing direction, widths, addresses or count.
                ch.Control = wasEnabled ? (ch.Control & ~15u) | (value & 15) : value & 0x7FFF;
                if(!wasEnabled && (ch.Control & 1) != 0)
                {
                    ch.InitialCount = ch.Count; ch.CurrentPeripheral = ch.Peripheral; ch.CurrentMemory = ch.Memory;
                    if((ch.Control & 0x4020) == 0x4020)
                    { this.Log(LogLevel.Warning, "DMA memory-to-memory circular mode is unsupported by hardware; ignoring circular bit"); ch.Control &= ~0x20u; }
                }
                UpdateIRQ(index);
                if((ch.Control & 1) != 0) Transfer(index);
                return;
            }
            if((ch.Control & 1) != 0) { this.Log(LogLevel.Warning, "DMA channel {0}: configuration write ignored while enabled", index + 1); return; }
            switch(reg) { case 4: ch.Count = value & 0xFFFF; break; case 8: ch.Peripheral = value; break; case 12: ch.Memory = value; break; }
        }
        private void Transfer(int index)
        {
            var ch = channels[index];
            if(ch.Busy || (ch.Control & 1) == 0 || ch.Count == 0) return;
            var memoryToMemory = (ch.Control & 0x4000) != 0;
            if(!memoryToMemory && !requests[index]) return;
            var peripheralWidth = (int)((ch.Control >> 8) & 3);
            var memoryWidth = (int)((ch.Control >> 10) & 3);
            if(peripheralWidth == 3 || memoryWidth == 3) { Error(index, "reserved transfer width"); return; }
            var pbytes = 1 << peripheralWidth; var mbytes = 1 << memoryWidth;
            ch.Busy = true;
            try
            {
                while((ch.Control & 1) != 0 && ch.Count > 0 && (memoryToMemory || requests[index]))
                {
                    if((ch.CurrentPeripheral & (uint)(pbytes - 1)) != 0 || (ch.CurrentMemory & (uint)(mbytes - 1)) != 0)
                    { Error(index, "unaligned transfer address"); break; }
                    var memorySource = (ch.Control & 0x10) != 0;
                    uint value = memorySource ? Read(ch.CurrentMemory, mbytes) : Read(ch.CurrentPeripheral, pbytes);
                    if(memorySource) Write(ch.CurrentPeripheral, pbytes, value); else Write(ch.CurrentMemory, mbytes, value);
                    if((ch.Control & 0x40) != 0) ch.CurrentPeripheral += (uint)pbytes;
                    if((ch.Control & 0x80) != 0) ch.CurrentMemory += (uint)mbytes;
                    ch.Count--;
                    if(ch.InitialCount > 1 && ch.Count == ch.InitialCount / 2) SetFlag(index, 4);
                    if(ch.Count == 0)
                    {
                        SetFlag(index, 2);
                        if((ch.Control & 0x20) != 0)
                        { ch.Count = ch.InitialCount; ch.CurrentPeripheral = ch.Peripheral; ch.CurrentMemory = ch.Memory; }
                        // Keep EN latched like hardware. Circular resumes on next asserted request.
                        break;
                    }
                }
            }
            catch(Exception e) { Error(index, e.Message); }
            finally { ch.Busy = false; }
        }
        private uint Read(uint address, int width)
        { switch(width) { case 1: return bus.ReadByte(address); case 2: return bus.ReadWord(address); default: return bus.ReadDoubleWord(address); } }
        private void Write(uint address, int width, uint value)
        { switch(width) { case 1: bus.WriteByte(address, (byte)value); break; case 2: bus.WriteWord(address, (ushort)value); break; default: bus.WriteDoubleWord(address, value); break; } }
        private void Error(int index, string reason)
        { this.Log(LogLevel.Warning, "DMA channel {0} transfer error: {1}", index + 1, reason); channels[index].Control &= ~1u; SetFlag(index, 8); }
        private void SetFlag(int index, uint flag)
        { status |= (flag | 1u) << (index * 4); UpdateIRQ(index); }
        private void UpdateIRQ(int index)
        { Connections[index].Set((((status >> (index * 4)) & channels[index].Control) & 14) != 0); }
        private bool Decode(long offset, out int index, out int reg)
        {
            index = (int)((offset - 8) / 20); reg = (int)((offset - 8) % 20);
            return offset >= 8 && index < 7 && reg >= 0 && reg <= 12 && (reg & 3) == 0;
        }
        private class Channel
        { public uint Control, Count, InitialCount, Peripheral, Memory, CurrentPeripheral, CurrentMemory; public bool Busy; }
        private readonly IBusController bus;
        private readonly Channel[] channels = new Channel[7];
        private readonly bool[] requests = new bool[7];
        private readonly bool[] directRequests = new bool[7];
        private readonly bool[] sourceRequests = new bool[256];
        private readonly int[][] fixedSources;
        // RM rev 2.06 tables 9-3, 9-4. Values are table 9-5 source IDs.
        private static readonly int[][] dma1Sources = {
            new[] {1, 66, 80},
            new[] {9, 30, 46, 56, 63, 74},
            new[] {10, 29, 45, 57, 75, 71},
            new[] {11, 26, 44, 59, 53, 54, 81},
            new[] {12, 25, 43, 55, 64, 82},
            new[] {27, 42, 58, 72, 69},
            new[] {28, 41, 65, 67, 79}
        };
        private static readonly int[][] dma2Sources = {
            new[] {13, 91, 85, 114, 111},
            new[] {14, 90, 87, 115, 109, 110},
            new[] {15, 31, 95, 5, 112},
            new[] {16, 49, 89, 103, 6},
            new[] {3, 32, 50, 88, 113},
            new int[0], new int[0]
        };
        private uint status, select0, select1;
    }
}
