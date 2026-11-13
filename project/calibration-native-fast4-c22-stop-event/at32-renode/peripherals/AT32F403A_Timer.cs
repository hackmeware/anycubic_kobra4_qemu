// SPDX-License-Identifier: MIT
// AT32-specific period reset and TMR2/TMR5 plus-mode adapter around Renode STM32_Timer.
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;

namespace Antmicro.Renode.Peripherals.AT32
{
    [AllowedTranslations(AllowedTranslation.ByteToDoubleWord | AllowedTranslation.WordToDoubleWord)]
    public class AT32Timer : STM32_Timer, IDoubleWordPeripheral
    {
        public AT32Timer(IMachine machine, ulong frequency = 8000000, bool supports32Bits = false)
            : base(machine, frequency, supports32Bits ? 0xFFFFFFFFu : 0xFFFFu)
        {
            this.supports32Bits = supports32Bits;
            // Renode 1.17 keeps compare timers private and does not propagate the
            // inherited LimitTimer.Frequency setter to them. Bind once, fail visibly
            // on an incompatible runtime rather than silently running mixed clocks.
            var channelsField = typeof(STM32_Timer).GetField("channels", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
            var channels = channelsField == null ? null : channelsField.GetValue(this) as System.Array;
            if(channels == null || channels.Length != 4)
                throw new System.NotSupportedException("AT32Timer requires the Renode 1.17 four-channel timer layout");
            compareTimers = new LimitTimer[channels.Length];
            for(int i = 0; i < channels.Length; i++)
            {
                var channel = channels.GetValue(i);
                var timerField = channel.GetType().GetField("Timer");
                compareTimers[i] = timerField == null ? null : timerField.GetValue(channel) as LimitTimer;
                if(compareTimers[i] == null)
                    throw new System.NotSupportedException("AT32Timer cannot bind the Renode compare timer");
            }
            Reset();
        }
        public new ulong Frequency
        {
            get => base.Frequency;
            set
            {
                base.Frequency = value;
                SynchronizeCompareFrequencies();
            }
        }
        private void SynchronizeCompareFrequencies()
        {
            // Reset can run during base construction, before binding.
            if(compareTimers == null) return;
            foreach(var timer in compareTimers) timer.Frequency = base.Frequency;
        }
        public override void Reset()
        {
            base.Reset(); plusMode = false;
            // AT32 PR reset is zero. Base timer remains disabled until a nonzero PR is programmed.
            base.WriteDoubleWord(0x2C, 0);
            SynchronizeCompareFrequencies();
        }
        public new uint ReadDoubleWord(long offset)
        {
            uint value = base.ReadDoubleWord(offset);
            if(offset == 0) return (value & ~0x400u) | (plusMode ? 0x400u : 0);
            return IsExtendedRegister(offset) && !plusMode ? value & 0xFFFF : value;
        }
        public new void WriteDoubleWord(long offset, uint value)
        {
            if(offset == 0)
            {
                bool nextMode = supports32Bits && (value & 0x400) != 0;
                if(plusMode && !nextMode)
                {
                    // Mode change is deterministic: discard upper halves rather than preserve hidden state.
                    foreach(long register in extendedRegisters)
                        base.WriteDoubleWord(register, base.ReadDoubleWord(register) & 0xFFFF);
                }
                plusMode = nextMode;
                base.WriteDoubleWord(offset, value & ~0x400u); return;
            }
            if(IsExtendedRegister(offset) && !plusMode) value &= 0xFFFF;
            base.WriteDoubleWord(offset, value);
        }
        uint IDoubleWordPeripheral.ReadDoubleWord(long offset) => ReadDoubleWord(offset);
        void IDoubleWordPeripheral.WriteDoubleWord(long offset, uint value) => WriteDoubleWord(offset, value);
        private static bool IsExtendedRegister(long offset) => offset == 0x24 || offset == 0x2C || (offset >= 0x34 && offset <= 0x40 && (offset & 3) == 0);
        private static readonly long[] extendedRegisters = { 0x24, 0x2C, 0x34, 0x38, 0x3C, 0x40 };
        private readonly LimitTimer[] compareTimers;
        private readonly bool supports32Bits;
        private bool plusMode;
    }
}
