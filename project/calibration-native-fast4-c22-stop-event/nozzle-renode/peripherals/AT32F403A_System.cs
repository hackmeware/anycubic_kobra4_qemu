// SPDX-License-Identifier: MIT
// AT32F403A functional model. See docs/COVERAGE.md for deliberately unmodelled behavior.
using System;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Peripherals.IRQControllers;

namespace Antmicro.Renode.Peripherals.AT32
{
    [AllowedTranslations(AllowedTranslation.ByteToDoubleWord | AllowedTranslation.WordToDoubleWord)]
    public class AT32CRM : IDoubleWordPeripheral, IKnownSize
    {
        public AT32CRM(IMachine machine, NVIC nvic, uint hextFrequency = 8000000)
        {
            this.nvic = nvic; HextFrequency = hextFrequency; Reset();
        }
        public GPIO IRQ { get; } = new GPIO();
        public long Size => 0x400;
        public uint HextFrequency { get; set; }
        public uint SystemFrequency { get; private set; }
        public uint AHBFrequency { get; private set; }
        public uint APB1Frequency { get; private set; }
        public uint APB2Frequency { get; private set; }
        public void AttachTimer(STM32_Timer timer, bool apb2)
        {
            timers.Add(Tuple.Create(timer, apb2)); UpdateClocks();
        }
        public void AttachCoreClock(IPeripheral peripheral)
        {
            coreClocks.Add(peripheral); UpdateClocks();
        }
        public void AttachRTC(IPeripheral peripheral) { rtc = peripheral; UpdateClocks(); }
        public void AttachBackup(IPeripheral peripheral) { backup = peripheral; }
        public void AttachClock(IPeripheral peripheral, bool apb2)
        {
            var property = peripheral.GetType().GetProperty("Frequency");
            if(property == null || !property.CanWrite) throw new ArgumentException("Peripheral must expose a writable Frequency property");
            clocks.Add(Tuple.Create(peripheral, apb2)); UpdateClocks();
        }
        public void AttachReset(IPeripheral peripheral, long register, int bit)
        {
            resets.Add(Tuple.Create(peripheral, register, bit));
        }
        public void Reset()
        {
            Array.Clear(r, 0, r.Length); r[0] = 0x83; r[0x14 / 4] = 0x14;
            r[0x24 / 4] = 0x0C000000; r[0x54 / 4] = 0xD; IRQ.Unset(); UpdateClocks();
        }
        public uint ReadDoubleWord(long offset)
        {
            if(!Valid(offset)) { this.LogUnhandledRead(offset); return 0; }
            return r[offset / 4];
        }
        public void WriteDoubleWord(long offset, uint value)
        {
            if(!Valid(offset)) { this.LogUnhandledWrite(offset, value); return; }
            var old = r[offset / 4];
            switch(offset)
            {
                case 0:
                    // Active system sources cannot be disabled by software (RM 4.3.1).
                    uint source = (r[1] >> 2) & 3;
                    if(source == 0) value |= 1;
                    if(source == 1) value |= 1u << 16;
                    if(source == 2) value |= 1u << 24;
                    // Keep a PLL input running while its output supplies the core.
                    if(source == 2) value |= (r[1] & 0x10000) != 0 ? 1u << 16 : 1u;
                    r[0] = (value & 0x010D00FD) | (old & 0xFF00) | (old & 0x02020002);
                    break;
                case 4: r[1] = (value & ~12u) | (old & 12u); break;
                case 8:
                    r[2] = (old & 0x9F) & ~((value >> 16) & 0x9F);
                    r[2] |= value & 0x1F00; break;
                case 0x54: r[0x54 / 4] = (value & ~15u) | 0xD; break;
                case 0x20:
                    r[8] = (value & ~2u) | ((value & 1) << 1);
                    if((value & 1) != 0 && (old & 1) == 0) r[2] |= 2;
                    if((value & 0x10000) != 0 && (old & 0x10000) == 0)
                    {
                        if(backup != null) backup.GetType().GetMethod("BackupReset").Invoke(backup, null);
                        if(rtc != null) rtc.GetType().GetMethod("BackupReset").Invoke(rtc, null);
                    }
                    break;
                case 0x24:
                    r[9] = (old & 0xFC000000) | (value & 1) | ((value & 1) << 1);
                    if((value & (1u << 24)) != 0) r[9] &= 3;
                    if((value & 1) != 0 && (old & 1) == 0) r[2] |= 1;
                    break;
                default: r[offset / 4] = value; break;
            }
            foreach(var item in resets)
                if(item.Item2 == offset && (value & ~old & (1u << item.Item3)) != 0) item.Item1.Reset();
            UpdateClocks();
            IRQ.Set((r[2] & (r[2] >> 8) & 0x1F) != 0);
        }
        private void UpdateClocks()
        {
            // Readiness follows enabled sources, with no analog settling delay.
            uint previousReady = r[0] & 0x02020002;
            r[0] &= ~0x02020002u;
            if((r[0] & 1) != 0) r[0] |= 2;
            if((r[0] & 0x10000) != 0) r[0] |= 0x20000;
            bool pllInputReady = (r[1] & 0x10000) != 0 ? (r[0] & 0x20000) != 0 : (r[0] & 2) != 0;
            if((r[0] & 0x1000000) != 0 && pllInputReady) r[0] |= 0x2000000;
            uint edges = (r[0] & 0x02020002) & ~previousReady;
            if((edges & 2) != 0) r[2] |= 4;
            if((edges & 0x20000) != 0) r[2] |= 8;
            if((edges & 0x2000000) != 0) r[2] |= 16;
            uint requested = r[1] & 3;
            bool ready = requested == 0 ? (r[0] & 2) != 0 : requested == 1 ? (r[0] & 0x20000) != 0 : requested == 2 && (r[0] & 0x2000000) != 0;
            if(ready) r[1] = (r[1] & ~12u) | (requested << 2);
            uint source = (r[1] >> 2) & 3;
            SystemFrequency = 8000000;
            if(source == 0 && (r[0x54 / 4] & 0x200) != 0 && (r[0x30 / 4] & 0x2000000) != 0) SystemFrequency = 48000000;
            if(source == 1) SystemFrequency = HextFrequency;
            if(source == 2)
            {
                uint lo = (r[1] >> 18) & 15, hi = (r[1] >> 29) & 3;
                uint mult = hi != 0 || lo == 15 ? lo + 16 * hi + 1 : lo + 2;
                uint input = (r[1] & 0x10000) == 0 ? 4000000 : HextFrequency;
                if((r[1] & 0x30000) == 0x30000) input /= ((r[0x54 / 4] >> 12) & 3) + 2;
                SystemFrequency = input * mult;
            }
            AHBFrequency = SystemFrequency >> ahbShifts[(r[1] >> 4) & 15];
            int apb1 = apbShifts[(r[1] >> 8) & 7], apb2 = apbShifts[(r[1] >> 11) & 7];
            APB1Frequency = AHBFrequency >> apb1; APB2Frequency = AHBFrequency >> apb2;
            nvic.Frequency = AHBFrequency;
            foreach(var item in coreClocks)
            {
                var property = item.GetType().GetProperty("Frequency");
                property.SetValue(item, Convert.ChangeType(AHBFrequency, property.PropertyType), null);
            }
            if(rtc != null)
            {
                uint selection = (r[8] >> 8) & 3;
                ulong frequency = selection == 1 ? 32768u : selection == 2 ? 40000u : Math.Max(1u,HextFrequency/128u);
                bool enabled = (r[8]&0x8000)!=0 && (selection==1 ? (r[8]&2)!=0 : selection==2 ? (r[9]&2)!=0 : selection==3 && (r[0]&0x20000)!=0);
                rtc.GetType().GetMethod("ConfigureClock").Invoke(rtc,new object[] { frequency, enabled });
            }
            foreach(var item in clocks)
            {
                var property = item.Item1.GetType().GetProperty("Frequency");
                property.SetValue(item.Item1, Convert.ChangeType(item.Item2 ? APB2Frequency : APB1Frequency, property.PropertyType), null);
            }
            foreach(var item in timers)
            {
                uint frequency = item.Item2 ? APB2Frequency : APB1Frequency;
                int shift = item.Item2 ? apb2 : apb1;
                // Dispatch to the concrete adapter: LimitTimer.Frequency cannot be
                // overridden and otherwise leaves STM32 compare clocks unchanged.
                var property = item.Item1.GetType().GetProperty("Frequency");
                property.SetValue(item.Item1, Convert.ChangeType(frequency * (shift == 0 ? 1u : 2u), property.PropertyType), null);
            }
        }
        private bool Valid(long o) => o >= 0 && o <= 0x5C && (o & 3) == 0 && (o <= 0x28 || o == 0x30 || o >= 0x50);
        private readonly uint[] r = new uint[24];
        private readonly NVIC nvic;
        private IPeripheral rtc, backup;
        private readonly List<IPeripheral> coreClocks = new List<IPeripheral>();
        private readonly List<Tuple<IPeripheral, bool>> clocks = new List<Tuple<IPeripheral, bool>>();
        private readonly List<Tuple<STM32_Timer, bool>> timers = new List<Tuple<STM32_Timer, bool>>();
        private readonly List<Tuple<IPeripheral, long, int>> resets = new List<Tuple<IPeripheral, long, int>>();
        private static readonly int[] ahbShifts = {0,0,0,0,0,0,0,0,1,2,3,4,6,7,8,9};
        private static readonly int[] apbShifts = {0,0,0,0,1,2,3,4};
    }

    // Startup-facing flash controller. Erase/program/protection operations intentionally fail,
    // rather than pretending to implement flash integrity with writable mapped memory.
    [AllowedTranslations(AllowedTranslation.ByteToDoubleWord | AllowedTranslation.WordToDoubleWord)]
    public class AT32FlashController : IDoubleWordPeripheral, IKnownSize
    {
        public AT32FlashController() { Reset(); }
        public GPIO IRQ { get; } = new GPIO();
        public long Size => 0x400;
        public void Reset()
        {
            Array.Clear(r, 0, r.Length); r[4] = r[20] = r[36] = 0x80;
            r[0] = 0x30; r[7] = 0x03FFFFFC; r[8] = 0xFFFFFFFF; r[0xD8 / 4] = 0x01000000; Array.Clear(keyStage, 0, 3); IRQ.Unset();
        }
        public uint ReadDoubleWord(long offset)
        {
            if(offset >= 0 && offset < 0x100 && (offset & 3) == 0) return r[offset / 4];
            this.LogUnhandledRead(offset); return 0;
        }
        public void WriteDoubleWord(long offset, uint value)
        {
            if(offset < 0 || offset >= 0x100 || (offset & 3) != 0) { this.LogUnhandledWrite(offset, value); return; }
            int bank = (int)(offset / 0x40), local = (int)(offset % 0x40);
            if(bank < 3 && local == 4)
            {
                if(keyStage[bank] == 1 && value == 0xCDEF89AB) { r[(bank * 0x40 + 0x10) / 4] &= ~0x80u; keyStage[bank] = 0; }
                else keyStage[bank] = value == 0x45670123 ? 1 : 0;
            }
            else if(bank < 3 && local == 0xC) r[offset / 4] &= ~(value & 0x34);
            else if(bank < 3 && local == 0x10)
            {
                uint old = r[offset / 4]; r[offset / 4] = value | (old & 0x80);
                if((value & 0x41) != 0)
                {
                    r[(offset - 4) / 4] |= 4; r[offset / 4] &= ~0x40u;
                    this.Log(LogLevel.Warning, "Flash programming/erase is not modelled; operation rejected with PRGMERR");
                }
            }
            else if(offset == 0) { /* Reserved FLASH_PSR writes ignored, reset value remains 0x30. */ }
            else if(local == 0x14) r[offset / 4] = value;
            else this.LogUnhandledWrite(offset, value);
            bool pending = false;
            for(int b = 0; b < 3; b++) pending |= ((r[b * 16 + 3] & 0x14) != 0 && (r[b * 16 + 4] & 0x400) != 0);
            IRQ.Set(pending);
        }
        private readonly uint[] r = new uint[64];
        private readonly int[] keyStage = new int[3];
    }

    [AllowedTranslations(AllowedTranslation.ByteToDoubleWord | AllowedTranslation.WordToDoubleWord)]
    public class AT32ADC : IDoubleWordPeripheral, IKnownSize
    {
        public AT32ADC() { Reset(); }
        public GPIO IRQ { get; } = new GPIO();
        public GPIO DMARequest { get; } = new GPIO();
        public long Size => 0x400;
        public void SetChannelValue(int channel, uint value)
        {
            if(channel < 0 || channel > 17 || value > 4095) throw new ArgumentOutOfRangeException();
            samples[channel] = value;
        }
        public void Reset() { Array.Clear(r,0,r.Length); r[9]=4095; IRQ.Unset(); DMARequest.Unset(); }
        public uint ReadDoubleWord(long offset)
        {
            if(offset < 0 || offset > 0x4C || (offset & 3) != 0) { this.LogUnhandledRead(offset); return 0; }
            uint result = r[offset/4];
            if(offset == 0x4C) { r[0] &= ~2u; UpdateIRQ(); }
            return result;
        }
        public void WriteDoubleWord(long offset, uint value)
        {
            if(offset < 0 || offset > 0x38 || (offset & 3) != 0) { this.LogUnhandledWrite(offset,value); return; }
            if(offset == 0) r[0] &= value & 0x1F;
            else if(offset == 8)
            {
                uint previous = r[2];
                r[2] = value & 0x03FEF903u; // calibration completes immediately; reserved bits read zero
                if((value & 1) != 0)
                {
                    bool ordinarySoftware = (value & 0x025E0000) == 0x005E0000;
                    bool preemptSoftware = (value & 0x0120F000) == 0x0020F000;
                    bool repeatedEnable = (previous & 1) != 0 && value == previous;
                    if(ordinarySoftware || repeatedEnable) { r[2] &= ~0x400000u; ConvertRegular(); }
                    if(preemptSoftware) { r[2] &= ~0x200000u; ConvertInjected(); }
                }
            }
            else r[offset/4] = value;
            UpdateIRQ();
        }
        private uint Sample(int channel, bool preempt = false)
        {
            uint value = channel < samples.Length ? samples[channel] : 0;
            bool monitor = (r[1] & (preempt ? 0x400000u : 0x800000u)) != 0;
            bool selected = (r[1] & 0x200) == 0 || (r[1] & 31) == channel;
            if(monitor && selected && (value > (r[9] & 4095) || value < (r[10] & 4095))) r[0] |= 1;
            return value;
        }
        private void ConvertRegular()
        {
            int count = (r[1] & 0x100) == 0 ? 1 : (int)((r[11] >> 20) & 15) + 1;
            for(int i=0;i<count;i++)
            {
                int reg = i < 6 ? 13 : i < 12 ? 12 : 11;
                int shift = (i < 6 ? i : i < 12 ? i-6 : i-12) * 5;
                r[19] = Sample((int)((r[reg] >> shift) & 31));
                if((r[2] & 0x800) != 0) r[19] <<= 4;
                r[0] |= 0x12;
                if((r[2] & 0x100) != 0) DMARequest.Blink();
            }
            if((r[1] & 0x400) != 0) ConvertInjected();
        }
        private void ConvertInjected()
        {
            int count = (int)((r[14] >> 20) & 3) + 1;
            for(int i=0;i<count;i++)
            {
                int sample = (int)Sample((int)((r[14] >> ((4-count+i)*5)) & 31), true) - (int)(r[5+i] & 4095);
                r[15+i] = (uint)((r[2] & 0x800) != 0 ? sample << 4 : sample) & 0xFFFF;
            }
            r[0] |= 0xE;
        }
        private void UpdateIRQ() => IRQ.Set(((r[0]&2)!=0 && (r[1]&0x20)!=0) || ((r[0]&1)!=0 && (r[1]&0x40)!=0) || ((r[0]&4)!=0 && (r[1]&0x80)!=0));
        private readonly uint[] r = new uint[20];
        private readonly uint[] samples = new uint[18];
    }

    // PWC and battery-backed registers. Retained data survives ordinary machine resets.
    [AllowedTranslations(AllowedTranslation.ByteToDoubleWord | AllowedTranslation.WordToDoubleWord)]
    public class AT32BackupPower : IDoubleWordPeripheral, IKnownSize
    {
        public AT32BackupPower(bool power = false, AT32BackupPower powerControl = null)
        { this.power=power; this.powerControl=powerControl; BackupReset(); }
        public GPIO IRQ { get; } = new GPIO();
        public long Size => 0x400;
        public void Reset() { if(power) Array.Clear(r,0,r.Length); }
        public void BackupReset() { Array.Clear(r,0,r.Length); IRQ.Unset(); }
        public uint ReadDoubleWord(long offset)
        {
            if(!Valid(offset)) { this.LogUnhandledRead(offset); return 0; }
            return r[offset/4];
        }
        public void WriteDoubleWord(long offset, uint value)
        {
            if(!Valid(offset)) { this.LogUnhandledWrite(offset,value); return; }
            if(power && offset == 0) { r[0]=value & 0x1F3; r[1] &= ~((value>>2)&3); }
            else if(power && offset == 4) r[1]=(r[1]&7)|(value&0x100);
            else if(powerControl != null && (powerControl.ReadDoubleWord(0) & 0x100)==0) return;
            else if(offset == 0x34)
            {
                r[13]=(r[13]&0x300)|(value&4);
                if((value&1)!=0) r[13]&=~0x100u;
                if((value&2)!=0) r[13]&=~0x200u;
                IRQ.Set((r[13]&0x204)==0x204);
            }
            else r[offset/4] = value & (offset==0x30 ? 3u : offset==0x2C ? 0x3FFu : 0xFFFFu);
        }
        private bool Valid(long o) => (o&3)==0 && (power ? o==0 || o==4 : (o>=4 && o<=0x34) || (o>=0x40 && o<=0xBC));
        private readonly bool power;
        private readonly AT32BackupPower powerControl;
        private readonly uint[] r = new uint[48];
    }
}
