// SPDX-License-Identifier: MIT
// AT32F403A RTC, watchdog and DAC functional subset; see docs/EXTRAS.md.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.AT32
{
    public class AT32RTC : IDoubleWordPeripheral, IKnownSize
    {
        public AT32RTC(IMachine machine)
        {
            timer = new LimitTimer(machine.ClockSource, 32768, this, "RTC divider", 0x8001,
                direction: Direction.Ascending, workMode: WorkMode.Periodic, enabled: false, eventEnabled: true);
            timer.LimitReached += Tick;
            BackupReset();
        }
        public GPIO IRQ { get; } = new GPIO();
        public GPIO AlarmIRQ { get; } = new GPIO();
        public long Size => 0x400;
        public uint Counter => counter;
        public void ConfigureClock(ulong frequency, bool enabled)
        {
            timer.Frequency = Math.Max(1ul, frequency); clockEnabled = enabled;
            timer.Enabled = enabled; if(enabled) flags |= 8; UpdateInterrupts();
        }
        // Ordinary reset preserves battery-backed divider, counter and alarm.
        public void Reset() { control = 0; config = false; flags &= 7; IRQ.Unset(); AlarmIRQ.Unset(); }
        public void BackupReset()
        {
            timer.Reset(); divider = 0x8000; counter = 0; alarm = 0xFFFFFFFF;
            control = flags = 0; config = clockEnabled = false;
            timer.Limit = divider + 1; timer.Value = 0; timer.Enabled = false;
            IRQ.Unset(); AlarmIRQ.Unset();
        }
        public uint ReadDoubleWord(long offset)
        {
            switch(offset)
            {
                case 0: return control;
                case 4: if(clockEnabled) flags |= 8; return flags | 0x20u | (config ? 0x10u : 0);
                case 8: case 12: case 32: case 36: return 0; // write-only registers
                case 16: return ((uint)(divider - Math.Min((ulong)divider, timer.Value)) >> 16) & 15;
                case 20: return (uint)(divider - Math.Min((ulong)divider, timer.Value)) & 0xFFFF;
                case 24: return counter >> 16;
                case 28: return counter & 0xFFFF;
                default: this.LogUnhandledRead(offset); return 0;
            }
        }
        public void WriteDoubleWord(long offset, uint value)
        {
            if(offset == 0) { control = value & 7; UpdateInterrupts(); return; }
            if(offset == 4)
            {
                flags &= value & 15; config = (value & 16) != 0;
                UpdateInterrupts(); return;
            }
            if(!config) { this.Log(LogLevel.Warning, "RTC write at 0x{0:X} ignored outside configuration mode", offset); return; }
            switch(offset)
            {
                case 8: divider = (divider & 0xFFFF) | ((value & 15) << 16); UpdateDivider(); break;
                case 12: divider = (divider & 0xF0000) | (value & 0xFFFF); UpdateDivider(); break;
                case 24: counter = (counter & 0xFFFF) | ((value & 0xFFFF) << 16); break;
                case 28: counter = (counter & 0xFFFF0000) | (value & 0xFFFF); break;
                case 32: alarm = (alarm & 0xFFFF) | ((value & 0xFFFF) << 16); break;
                case 36: alarm = (alarm & 0xFFFF0000) | (value & 0xFFFF); break;
                default: this.LogUnhandledWrite(offset, value); break;
            }
        }
        private void UpdateDivider() { timer.Limit = divider + 1; timer.Value = 0; }
        private void Tick()
        {
            counter = unchecked(counter + 1); flags |= 9;
            if(counter == 0) flags |= 4;
            if(counter == alarm) flags |= 2;
            UpdateInterrupts();
        }
        private void UpdateInterrupts() { IRQ.Set((control & flags & 7) != 0); AlarmIRQ.Set((flags & control & 2) != 0); }
        private readonly LimitTimer timer;
        private uint divider, counter, alarm, control, flags;
        private bool config, clockEnabled;
    }

    public class AT32Watchdog : IDoubleWordPeripheral, IKnownSize
    {
        public AT32Watchdog(IMachine machine, bool windowed = false)
        {
            this.machine = machine; this.windowed = windowed;
            timer = new LimitTimer(machine.ClockSource, windowed ? 8000000ul : 40000ul, this,
                windowed ? "WWDT tick" : "WDT tick", 1, direction: Direction.Ascending,
                workMode: WorkMode.Periodic, enabled: false, eventEnabled: true);
            timer.LimitReached += Tick; Reset();
        }
        public GPIO IRQ { get; } = new GPIO();
        public event Action ResetRequested;
        public long Size => 0x400;
        public ulong Frequency { get => timer.Frequency; set => timer.Frequency = Math.Max(1ul, value); }
        public uint Counter => counter;
        public bool Enabled => active;
        public void Reset()
        {
            timer.Reset(); active = unlocked = false; prescaler = status = 0;
            reload = 0xFFF; counter = windowed ? 0x7Fu : 0xFFFu; configuration = 0x7F;
            timer.Value = 0; timer.Limit = 1; timer.Enabled = false; UpdateDivider(); IRQ.Unset();
        }
        public uint ReadDoubleWord(long offset)
        {
            if(windowed)
            {
                switch(offset) { case 0: return counter | (active ? 0x80u : 0); case 4: return configuration; case 8: return status; }
            }
            else
            {
                switch(offset) { case 0: return 0; case 4: return prescaler; case 8: return reload; case 12: return 0; }
            }
            this.LogUnhandledRead(offset); return 0;
        }
        public void WriteDoubleWord(long offset, uint value)
        {
            if(windowed)
            {
                switch(offset)
                {
                    case 0:
                        if(active && counter > (configuration & 127)) { FireReset(); return; }
                        counter = value & 127; active |= (value & 128) != 0;
                        timer.Enabled = active;
                        if(active && counter < 64) FireReset();
                        break;
                    case 4: configuration = value & 0x3FF; UpdateDivider(); break;
                    case 8: status &= value & 1; break;
                    default: this.LogUnhandledWrite(offset, value); break;
                }
                IRQ.Set((configuration & 0x200) != 0 && (status & 1) != 0); return;
            }
            switch(offset)
            {
                case 0:
                    unlocked = (value & 0xFFFF) == 0x5555;
                    if((value & 0xFFFF) == 0xCCCC) { if(!active) { active = true; timer.Enabled = true; } }
                    else if((value & 0xFFFF) == 0xAAAA) { counter = reload; timer.Value = 0; }
                    break;
                case 4:
                    if(unlocked) { prescaler = value & 7; UpdateDivider(); }
                    else this.Log(LogLevel.Warning, "WDT divider write ignored while locked");
                    break;
                case 8:
                    if(unlocked) reload = value & 0xFFF;
                    else this.Log(LogLevel.Warning, "WDT reload write ignored while locked");
                    break;
                default: this.LogUnhandledWrite(offset, value); break;
            }
        }
        private void UpdateDivider() { timer.Divider = windowed ? (4096ul << (int)((configuration >> 7) & 3)) : (4ul << (int)Math.Min(prescaler, 6u)); }
        private void Tick()
        {
            if(!active) return;
            if(windowed)
            {
                if(counter > 0) counter--;
                if(counter == 64) { status |= 1; IRQ.Set((configuration & 0x200) != 0); }
                if(counter < 64) FireReset();
            }
            else if(counter == 0) FireReset(); else counter--;
        }
        private void FireReset()
        {
            timer.Enabled = false; this.Log(LogLevel.Warning, "{0} expired/window violation: requesting machine reset", windowed ? "WWDT" : "WDT");
            ResetRequested?.Invoke(); machine.RequestReset();
        }
        private readonly IMachine machine;
        private readonly bool windowed;
        private readonly LimitTimer timer;
        private bool active, unlocked;
        private uint counter, reload, prescaler, configuration, status;
    }

    public class AT32DAC : IDoubleWordPeripheral, IKnownSize
    {
        public AT32DAC() { Reset(); }
        public long Size => 0x400;
        public uint Channel1Output => output[0];
        public uint Channel2Output => output[1];
        public event Action<int, uint> OutputChanged;
        public void Reset() { control = 0; Array.Clear(holding, 0, 2); Array.Clear(output, 0, 2); }
        public uint ReadDoubleWord(long offset)
        {
            switch(offset)
            {
                case 0: return control; case 4: return 0;
                case 8: return holding[0]; case 12: return holding[0] << 4; case 16: return holding[0] >> 4;
                case 20: return holding[1]; case 24: return holding[1] << 4; case 28: return holding[1] >> 4;
                case 32: return holding[0] | (holding[1] << 16);
                case 36: return (holding[0] << 4) | (holding[1] << 20);
                case 40: return (holding[0] >> 4) | ((holding[1] >> 4) << 8);
                case 44: return output[0]; case 48: return output[1];
                default: this.LogUnhandledRead(offset); return 0;
            }
        }
        public void WriteDoubleWord(long offset, uint value)
        {
            switch(offset)
            {
                case 0:
                    control = value & 0x1FFF1FFF;
                    if((control & 0x10C010C0) != 0) this.Log(LogLevel.Warning, "DAC waveform generation/DMA requests are not implemented");
                    for(int i = 0; i < 2; i++) if((ChannelControl(i) & 5) == 1) Transfer(i);
                    return;
                case 4:
                    for(int i = 0; i < 2; i++) if((value & (1u << i)) != 0 && ((ChannelControl(i) >> 3) & 7) == 7 && (ChannelControl(i) & 5) == 5) Transfer(i);
                    return;
                case 8: SetHolding(0, value); return;
                case 12: SetHolding(0, value >> 4); return;
                case 16: SetHolding(0, (value & 255) << 4); return;
                case 20: SetHolding(1, value); return;
                case 24: SetHolding(1, value >> 4); return;
                case 28: SetHolding(1, (value & 255) << 4); return;
                case 32: SetHolding(0, value); SetHolding(1, value >> 16); return;
                case 36: SetHolding(0, value >> 4); SetHolding(1, value >> 20); return;
                case 40: SetHolding(0, (value & 255) << 4); SetHolding(1, ((value >> 8) & 255) << 4); return;
                case 44: case 48: return; // read only
                default: this.LogUnhandledWrite(offset, value); return;
            }
        }
        public void Trigger(int source)
        {
            if(source < 0 || source > 6) throw new ArgumentOutOfRangeException("source");
            for(int i = 0; i < 2; i++) if((ChannelControl(i) & 5) == 5 && ((ChannelControl(i) >> 3) & 7) == (uint)source) Transfer(i);
        }
        private uint ChannelControl(int channel) => (control >> (16 * channel)) & 0xFFFF;
        private void SetHolding(int channel, uint value) { holding[channel] = value & 0xFFF; if((ChannelControl(channel) & 5) == 1) Transfer(channel); }
        private void Transfer(int channel) { output[channel] = holding[channel]; OutputChanged?.Invoke(channel + 1, output[channel]); }
        private uint control;
        private readonly uint[] holding = new uint[2], output = new uint[2];
    }
}
