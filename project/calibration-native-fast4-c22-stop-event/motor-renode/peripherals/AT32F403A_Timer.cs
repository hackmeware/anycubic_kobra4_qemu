// SPDX-License-Identifier: MIT
// AT32-specific period reset and TMR2/TMR5 plus-mode adapter around Renode STM32_Timer.
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;

namespace Antmicro.Renode.Peripherals.AT32
{
    [AllowedTranslations(AllowedTranslation.ByteToDoubleWord | AllowedTranslation.WordToDoubleWord)]
    public class AT32Timer : STM32_Timer, IDoubleWordPeripheral, IGPIOReceiver
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
            LimitReached += HandleUpdateTrigger;
        }
        public new ulong Frequency
        {
            get => base.Frequency;
            set
            {
                ConfigurationChanging?.Invoke();
                base.Frequency = value;
                SynchronizeCompareFrequencies();
                ConfigurationChanged?.Invoke();
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
            ConfigurationChanging?.Invoke();
            base.Reset(); plusMode = false; repetitionPhase = 0; masterMode = 0; breakConfiguration = 0; compareConfiguration1 = 0; compareConfiguration2 = 0;
            if(TriggerOutput != null) TriggerOutput.Unset();
            System.Array.Clear(internalInputs, 0, internalInputs.Length);
            // AT32 PR reset is zero. Base timer remains disabled until a nonzero PR is programmed.
            base.WriteDoubleWord(0x2C, 0);
            SynchronizeCompareFrequencies();
            ConfigurationChanged?.Invoke();
        }
        public new uint ReadDoubleWord(long offset)
        {
            uint value = base.ReadDoubleWord(offset);
            if(offset == 0x44) return breakConfiguration;
            if(offset == 0x18) return value | (compareConfiguration1 & OutputTagMask(value));
            if(offset == 0x1C) return value | (compareConfiguration2 & OutputTagMask(value));
            if(offset == 4) return (value & ~0x70u) | (masterMode << 4);
            if(offset == 0) return (value & ~0x400u) | (plusMode ? 0x400u : 0);
            return IsExtendedRegister(offset) && !plusMode ? value & 0xFFFF : value;
        }
        public new void WriteDoubleWord(long offset, uint value)
        {
            bool notify = offset == 0 || offset == 0x18 || offset == 0x1C || offset == 0x20 || offset == 0x2C || (offset >= 0x34 && offset <= 0x44);
            if(notify) ConfigurationChanging?.Invoke();
            try
            {
            // Retain native tagged configuration for diagnostics and future electrical models.
            // These fields do not implement dead-time, break gating or compare shadow latches.
            if(offset == 0x44) { breakConfiguration = value & 0xFFFF; return; }
            if(offset == 0x18) { compareConfiguration1 = value; value &= ~OutputTagMask(value); }
            if(offset == 0x1C) { compareConfiguration2 = value; value &= ~OutputTagMask(value); }
            if(offset == 4) masterMode = (value >> 4) & 7;
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
                base.WriteDoubleWord(offset, value & ~0x400u);
                if((value & 1) == 0) Enabled = false;
                UpdateEnableTrigger(); return;
            }
            if(IsExtendedRegister(offset) && !plusMode) value &= 0xFFFF;
            base.WriteDoubleWord(offset, offset == 4 ? value & ~0x70u : value);
            if(offset == 0x30 || (offset == 0x14 && (value & 1) != 0)) repetitionPhase = 0;
            if(offset == 0x14 && (value & 1) != 0 && masterMode == 2 && (base.ReadDoubleWord(0) & 2) == 0) TriggerOutput.Blink();
            if(offset == 4) UpdateEnableTrigger();
            }
            finally { if(notify) ConfigurationChanged?.Invoke(); }
        }
        // Motor testbench extension: IS0..IS3 arrive on input pins16..19.
        // Only trigger mode6 is added; channel capture pins retain base behavior.
        public GPIO TriggerOutput { get; } = new GPIO();
        // Electrical observers integrate old output before mutation, then sample new output.
        public event System.Action ConfigurationChanging;
        public event System.Action ConfigurationChanged;
        public new void OnGPIO(int number, bool value)
        {
            if(number < 16 || number > 19) { base.OnGPIO(number, value); return; }
            int input = number - 16;
            bool rising = value && !internalInputs[input]; internalInputs[input] = value;
            uint slave = base.ReadDoubleWord(8);
            if(!rising || (slave & 7) != 6 || ((slave >> 4) & 7) != input || Enabled) return;
            if(base.ReadDoubleWord(0x2C) == 0) return;
            ConfigurationChanging?.Invoke();
            // Hardware sets CEN on an accepted trigger, including one-pulse rearm.
            base.WriteDoubleWord(0, base.ReadDoubleWord(0) | 1);
            Value = 0; Enabled = true; repetitionPhase = 0;
            ConfigurationChanged?.Invoke();
            UpdateEnableTrigger();
        }
        void IGPIOReceiver.OnGPIO(int number, bool value) => OnGPIO(number, value);
        private void HandleUpdateTrigger()
        {
            uint control = base.ReadDoubleWord(0);
            // Native OPM may already have cleared Enabled. Observers retain the old drive.
            if((control & 8) != 0) { ConfigurationChanging?.Invoke(); ConfigurationChanged?.Invoke(); }
            if((control & 2) == 0)
            {
                // Native counter events represent overflow/underflow boundaries.
                // RCR=1 in center-aligned mode emits one update per full up/down cycle.
                uint repetitions = base.ReadDoubleWord(0x30) & 0xFF;
                if(repetitionPhase++ >= repetitions)
                {
                    repetitionPhase = 0;
                    if(masterMode == 2) TriggerOutput.Blink();
                }
            }
            UpdateEnableTrigger();
        }
        private void UpdateEnableTrigger()
        {
            if(masterMode == 1) TriggerOutput.Set(Enabled);
            else TriggerOutput.Unset();
        }
        uint IDoubleWordPeripheral.ReadDoubleWord(long offset) => ReadDoubleWord(offset);
        void IDoubleWordPeripheral.WriteDoubleWord(long offset, uint value) => WriteDoubleWord(offset, value);
        private static bool IsExtendedRegister(long offset) => offset == 0x24 || offset == 0x2C || (offset >= 0x34 && offset <= 0x40 && (offset & 3) == 0);
        private static readonly long[] extendedRegisters = { 0x24, 0x2C, 0x34, 0x38, 0x3C, 0x40 };
        private readonly LimitTimer[] compareTimers;
        private readonly bool supports32Bits;
        private bool plusMode;
        private static uint OutputTagMask(uint value)
        {
            return ((value & 3) == 0 ? 0x8Cu : 0) | ((value & 0x300) == 0 ? 0x8C00u : 0);
        }
        private uint breakConfiguration, compareConfiguration1, compareConfiguration2;
        private uint repetitionPhase, masterMode;
        private readonly bool[] internalInputs = new bool[4];
    }
}
