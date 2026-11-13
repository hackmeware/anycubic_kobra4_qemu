// SPDX-License-Identifier: MIT
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.AT32
{
    // Functional CYCCNT only: no trace packets, watchpoint comparators or profiling counters.
    public class AT32DWT : IDoubleWordPeripheral, IKnownSize
    {
        public AT32DWT(IMachine machine, ulong frequency = 8000000)
        {
            this.machine=machine;
            counter=new LimitTimer(machine.ClockSource, frequency, this, "CYCCNT", limit:0xFFFFFFFF, direction:Direction.Ascending, enabled:false, eventEnabled:false);
        }
        public ulong Frequency { get => counter.Frequency; set => counter.Frequency=Math.Max(1ul,value); }
        public long Size => 0x1000;
        public void Reset() { control=0; counter.Reset(); }
        public uint ReadDoubleWord(long offset)
        {
            if(offset==0) return control;
            if(offset==4)
            {
                if(machine.GetSystemBus(this).TryGetCurrentCPU(out var cpu)) cpu.SyncTime();
                return (uint)counter.Value;
            }
            this.LogUnhandledRead(offset); return 0;
        }
        public void WriteDoubleWord(long offset,uint value)
        {
            if(offset==0) { control=value&1; counter.Enabled=(control&1)!=0; if((value&~1u)!=0) this.Log(LogLevel.Warning,"DWT trace/profiling bits are not modelled"); }
            else if(offset==4) counter.Value=value;
            else this.LogUnhandledWrite(offset,value);
        }
        private uint control;
        private readonly IMachine machine;
        private readonly LimitTimer counter;
    }
}
