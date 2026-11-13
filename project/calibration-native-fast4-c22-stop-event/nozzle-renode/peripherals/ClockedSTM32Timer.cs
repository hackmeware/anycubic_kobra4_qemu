// SPDX-License-Identifier: MIT
// Frequency propagation only; all register/reset values remain stock STM32_Timer.
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Timers;
namespace Antmicro.Renode.Peripherals.Nozzle
{
    public class ClockedSTM32Timer : STM32_Timer
    {
        public ClockedSTM32Timer(IMachine machine, ulong frequency = 8000000, uint initialLimit = 0xFFFF)
            : base(machine, frequency, initialLimit)
        {
            // Renode 1.17 keeps compare timers private and does not propagate the
            // inherited LimitTimer.Frequency setter to them. Bind once, fail visibly
            // on an incompatible runtime rather than silently running mixed clocks.
            var channelsField = typeof(STM32_Timer).GetField("channels", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
            var channels = channelsField == null ? null : channelsField.GetValue(this) as System.Array;
            if(channels == null || channels.Length != 4)
                throw new System.NotSupportedException("ClockedSTM32Timer requires the Renode 1.17 four-channel timer layout");
            compareTimers = new LimitTimer[channels.Length];
            for(int i = 0; i < channels.Length; i++)
            {
                var channel = channels.GetValue(i);
                var timerField = channel.GetType().GetField("Timer");
                compareTimers[i] = timerField == null ? null : timerField.GetValue(channel) as LimitTimer;
                if(compareTimers[i] == null)
                    throw new System.NotSupportedException("ClockedSTM32Timer cannot bind the Renode compare timer");
            }
            SynchronizeCompareFrequencies();
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
            base.Reset();
            SynchronizeCompareFrequencies();
        }
        private readonly LimitTimer[] compareTimers;
    }
}
