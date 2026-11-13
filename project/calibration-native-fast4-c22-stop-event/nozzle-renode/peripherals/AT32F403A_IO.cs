// SPDX-License-Identifier: MIT
// AT32F403A functional GPIO, IOMUX, EXINT and USART models.
// Register layout: Artery AT32F403A/407 Firmware Library and RM rev 2.06.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.GPIOPort;
using Antmicro.Renode.Peripherals.UART;

namespace Antmicro.Renode.Peripherals.AT32
{
    public class AT32GPIO : BaseGPIOPort, IDoubleWordPeripheral, IKnownSize
    {
        public AT32GPIO(IMachine machine, AT32IOMUX iomux = null, int portIndex = 0,
            uint configurationLowReset = 0x44444444, uint configurationHighReset = 0x44444444) : base(machine, 16)
        {
            if(portIndex < 0 || portIndex > 4) throw new ArgumentOutOfRangeException("portIndex");
            this.iomux = iomux; this.portIndex = portIndex;
            lowReset = configurationLowReset; highReset = configurationHighReset;
            Reset();
        }
        public long Size { get { return 0x400; } }
        public override void Reset()
        {
            base.Reset();
            low = lowReset; high = highReset; output = drive = 0;
            lockBits = lockCandidate = 0; lockStage = 0; locked = false;
            Array.Clear(externalSet, 0, 16); Array.Clear(externalValue, 0, 16);
            Refresh();
        }
        public override void OnGPIO(int number, bool value)
        {
            if(!CheckPinNumber(number)) return;
            externalSet[number] = true; externalValue[number] = value; Refresh();
        }
        // Release an externally driven input, restoring the configured internal pull.
        public void ReleasePin(int number)
        {
            if(!CheckPinNumber(number)) return;
            externalSet[number] = false; Refresh();
        }
        public uint ReadDoubleWord(long offset)
        {
            switch(offset)
            {
            case 0: return low;
            case 4: return high;
            case 8:
                uint value = 0;
                for(var i = 0; i < 16; ++i) if(State[i]) value |= 1u << i;
                return value;
            case 0xC: return output;
            case 0x10: case 0x14: return 0;
            case 0x18:
                if(lockStage == 3) { locked = true; lockBits = lockCandidate; lockStage = 0; }
                return lockCandidate | (locked ? 0x10000u : 0u);
            case 0x3C: return drive;
            default: this.LogUnhandledRead(offset); return 0;
            }
        }
        public void WriteDoubleWord(long offset, uint value)
        {
            switch(offset)
            {
            case 0: low = ApplyConfiguration(low, value, 0); break;
            case 4: high = ApplyConfiguration(high, value, 8); break;
            case 8: this.Log(LogLevel.Warning, "Write to read-only GPIO IDT"); return;
            case 0xC: output = value & 0xFFFF; break;
            case 0x10: output = ((output & ~(value >> 16)) | value) & 0xFFFF; break;
            case 0x14: output &= ~(value & 0xFFFF); break;
            case 0x18: WriteLock(value); return;
            case 0x3C: drive = value & 0xFFFF; break;
            default: this.LogUnhandledWrite(offset, value); return;
            }
            Refresh();
        }
        private uint ApplyConfiguration(uint oldValue, uint newValue, int firstPin)
        {
            for(var i = 0; i < 8; ++i)
            {
                if(locked && (lockBits & (1u << (firstPin + i))) != 0)
                    newValue = (newValue & ~(0xFu << (4 * i))) | (oldValue & (0xFu << (4 * i)));
            }
            return newValue;
        }
        private void WriteLock(uint value)
        {
            if(locked) return;
            var pins = value & 0xFFFF;
            var key = (value & 0x10000) != 0;
            if(lockStage == 0 && key) { lockCandidate = pins; lockStage = 1; }
            else if(lockStage == 1 && !key && pins == lockCandidate) lockStage = 2;
            else if(lockStage == 2 && key && pins == lockCandidate) lockStage = 3;
            else { lockCandidate = pins; lockStage = 0; }
        }
        private void Refresh()
        {
            for(var i = 0; i < 16; ++i)
            {
                var config = ((i < 8 ? low : high) >> ((i % 8) * 4)) & 0xF;
                var isOutput = (config & 3) != 0;
                var function = config >> 2;
                var latch = (output & (1u << i)) != 0;
                bool level;
                if(!isOutput)
                    level = function == 0 ? false : externalSet[i] ? externalValue[i] : function == 2 && latch;
                else if(function >= 2)
                    // Alternate-function electrical drivers are not connected in this model.
                    level = externalSet[i] && externalValue[i];
                else if(function == 1 && latch)
                    // Open drain high is released, not actively driven high.
                    level = externalSet[i] && externalValue[i];
                else level = latch;
                State[i] = level;
                Connections[i].Set(level);
                if(iomux != null) iomux.OnGPIO(portIndex * 16 + i, level);
            }
        }
        private readonly AT32IOMUX iomux;
        private readonly int portIndex;
        private readonly uint lowReset, highReset;
        private readonly bool[] externalSet = new bool[16], externalValue = new bool[16];
        private uint low, high, output, drive, lockBits, lockCandidate;
        private int lockStage;
        private bool locked;
    }

    // The numbered outputs feed EXINT lines 0..15. Input number = port * 16 + pin.
    public class AT32IOMUX : BaseGPIOPort, IDoubleWordPeripheral, IKnownSize
    {
        public AT32IOMUX(IMachine machine) : base(machine, 16) { Reset(); }
        public long Size { get { return 0x400; } }
        public override void Reset()
        {
            base.Reset(); Array.Clear(registers, 0, registers.Length);
            Array.Clear(inputs, 0, inputs.Length); Refresh();
        }
        public override void OnGPIO(int number, bool value)
        {
            if(number < 0 || number >= 80) { this.Log(LogLevel.Warning, "Invalid IOMUX input {0}", number); return; }
            inputs[number] = value; Refresh();
        }
        public uint ReadDoubleWord(long offset)
        {
            if(Valid(offset)) return registers[offset / 4];
            this.LogUnhandledRead(offset); return 0;
        }
        public void WriteDoubleWord(long offset, uint value)
        {
            if(!Valid(offset)) { this.LogUnhandledWrite(offset, value); return; }
            if(offset >= 8 && offset <= 0x14)
            {
                registers[offset / 4] = value & 0xFFFF; Refresh(); return;
            }
            registers[offset / 4] = offset == 0 ? value & 0xFF : value;
            if(value != 0) this.Log(LogLevel.Warning, "IOMUX offset 0x{0:X}: configuration retained; alternate-function/event-output routing is not modeled", offset);
        }
        private bool Valid(long offset) { return offset >= 0 && offset <= 0x34 && offset != 0x18 && (offset & 3) == 0; }
        private void Refresh()
        {
            for(var pin = 0; pin < 16; ++pin)
            {
                var port = (int)((registers[2 + pin / 4] >> ((pin % 4) * 4)) & 0xF);
                var level = port < 5 && inputs[port * 16 + pin];
                State[pin] = level; Connections[pin].Set(level);
            }
        }
        private readonly uint[] registers = new uint[14];
        private readonly bool[] inputs = new bool[80];
    }

    public class AT32EXINT : BaseGPIOPort, IDoubleWordPeripheral, IKnownSize
    {
        public AT32EXINT(IMachine machine, bool hasEthernetWakeup = false) : base(machine, 20)
        { validLines = hasEthernetWakeup ? 0xFFFFFu : 0x7FFFFu; Reset(); }
        public long Size { get { return 0x400; } }
        public GPIO IRQ5_9 { get; } = new GPIO();
        public GPIO IRQ10_15 { get; } = new GPIO();
        // Event pulses are distinct from latched, masked interrupts.
        public GPIO Event { get; } = new GPIO();
        public override void Reset()
        {
            base.Reset(); interruptMask = eventMask = rising = falling = pending = software = 0;
            UpdateInterrupts(); Event.Unset();
        }
        public override void OnGPIO(int number, bool value)
        {
            if(!CheckPinNumber(number) || (validLines & (1u << number)) == 0) return;
            var old = State[number]; State[number] = value;
            var bit = 1u << number;
            if((!old && value && (rising & bit) != 0) || (old && !value && (falling & bit) != 0)) Trigger(bit);
        }
        public uint ReadDoubleWord(long offset)
        {
            switch(offset)
            {
            case 0: return interruptMask; case 4: return eventMask;
            case 8: return rising; case 0xC: return falling;
            case 0x10: return software; case 0x14: return pending;
            default: this.LogUnhandledRead(offset); return 0;
            }
        }
        public void WriteDoubleWord(long offset, uint value)
        {
            value &= validLines;
            switch(offset)
            {
            case 0: interruptMask = value; break;
            case 4: eventMask = value; break;
            case 8: rising = value; break;
            case 0xC: falling = value; break;
            case 0x10:
                var newlySet = value & ~software;
                software |= value; Trigger(newlySet); return;
            case 0x14: pending &= ~value; software &= ~value; break;
            default: this.LogUnhandledWrite(offset, value); return;
            }
            UpdateInterrupts();
        }
        private void Trigger(uint bits)
        {
            pending |= bits & interruptMask;
            if((eventMask & bits) != 0) { Event.Set(true); Event.Set(false); }
            UpdateInterrupts();
        }
        private void UpdateInterrupts()
        {
            var active = pending & interruptMask;
            for(var i = 0; i < 20; ++i) Connections[i].Set((active & (1u << i)) != 0);
            IRQ5_9.Set((active & 0x3E0) != 0); IRQ10_15.Set((active & 0xFC00) != 0);
        }
        private readonly uint validLines;
        private uint interruptMask, eventMask, rising, falling, pending, software;
    }

    [AllowedTranslations(AllowedTranslation.ByteToDoubleWord | AllowedTranslation.WordToDoubleWord)]
    public class AT32UART : UARTBase, IDoubleWordPeripheral, IKnownSize
    {
        public AT32UART(IMachine machine, uint frequency = 8000000, int receiveFifoDepth = 1) : base(machine)
        {
            if(receiveFifoDepth < 1) throw new ArgumentOutOfRangeException("receiveFifoDepth");
            Frequency = frequency; this.receiveFifoDepth = receiveFifoDepth; Reset();
        }
        public GPIO IRQ { get; } = new GPIO();
        public GPIO RxDMA { get; } = new GPIO();
        public GPIO TxDMA { get; } = new GPIO();
        public long Size { get { return 0x400; } }
        public uint Frequency { get; set; }
        public override uint BaudRate { get { return baud == 0 ? 0 : Frequency / baud; } }
        public override Parity ParityBit { get { return (control1 & 0x400) == 0 ? Parity.None : (control1 & 0x200) == 0 ? Parity.Even : Parity.Odd; } }
        public override Bits StopBits
        {
            get
            {
                switch((control2 >> 12) & 3)
                { case 0: return Bits.One; case 1: return Bits.Half; case 2: return Bits.Two; default: return Bits.OneAndAHalf; }
            }
        }
        public override void Reset()
        {
            control1 = control2 = control3 = baud = guard = 0;
            flags = 0xC0; statusRead = false;
            base.Reset(); UpdateInterrupts();
        }
        public override void WriteChar(byte value)
        {
            lock(innerLock)
            {
                if((control1 & 0x2004) != 0x2004) return;
                if(Count >= receiveFifoDepth) { flags |= 8; UpdateInterrupts(); return; }
                base.WriteChar(value);
            }
        }
        // Explicit testbench stimuli. No uncalibrated wall-clock idle timer is used.
        public void SignalIdle() { flags |= 0x10; UpdateInterrupts(); }
        public void InjectReceiveError(uint errorMask) { flags |= errorMask & 0xF; UpdateInterrupts(); }
        public uint ReadDoubleWord(long offset)
        {
            lock(innerLock)
            {
                switch(offset)
                {
                case 0: statusRead = true; return flags | (Count != 0 ? 0x20u : 0u);
                case 4:
                    byte value;
                    TryGetCharacter(out value);
                    if(statusRead) { flags &= ~0x1Fu; statusRead = false; }
                    UpdateInterrupts(); return value;
                case 8: return baud; case 0xC: return control1;
                case 0x10: return control2; case 0x14: return control3; case 0x18: return guard;
                default: this.LogUnhandledRead(offset); return 0;
                }
            }
        }
        public void WriteDoubleWord(long offset, uint value)
        {
            lock(innerLock)
            {
                switch(offset)
                {
                case 0:
                    // STS uses write-zero-to-clear for CTS/BREAK/TC/RDBF.
                    flags &= value | ~0x340u;
                    if((value & 0x20) == 0) ClearBuffer();
                    break;
                case 4:
                    if((control1 & 0x2008) == 0x2008)
                    {
                        flags &= ~0x40u;
                        if(statusRead) statusRead = false;
                        TransmitCharacter((byte)value);
                        // Functional model: transmitter completes synchronously, no baud timing.
                        flags |= 0xC0;
                    }
                    else this.Log(LogLevel.Warning, "USART DT write with transmitter disabled");
                    break;
                case 8: baud = value & 0xFFFF; break;
                case 0xC:
                    control1 = value & 0x3FFF;
                    if((value & 1) != 0) this.Log(LogLevel.Warning, "USART break generation not modeled");
                    if((value & 0x1002) != 0) this.Log(LogLevel.Warning, "USART 9-bit data/silent receiver behavior is not modeled; UART backend transfers bytes");
                    break;
                case 0x10:
                    control2 = value & 0x7F6F;
                    if((value & 0x4800) != 0) this.Log(LogLevel.Warning, "USART LIN/synchronous mode is not modeled");
                    break;
                case 0x14:
                    control3 = value & 0x7FF;
                    if((value & 0x33E) != 0) this.Log(LogLevel.Warning, "USART IRDA/smartcard/half-duplex/flow-control electrical behavior is not modeled");
                    break;
                case 0x18: guard = value & 0xFFFF; break;
                default: this.LogUnhandledWrite(offset, value); return;
                }
                UpdateInterrupts();
            }
        }
        protected override void CharWritten() { UpdateInterrupts(); }
        protected override void QueueEmptied() { UpdateInterrupts(); }
        private void UpdateInterrupts()
        {
            var status = flags | (Count != 0 ? 0x20u : 0u);
            var enabled = (control1 & 0x2000) != 0;
            IRQ.Set(enabled && (((status & control1 & 0xF0) != 0)
                || ((status & 8) != 0 && (control1 & 0x20) != 0)
                || ((status & 1) != 0 && (control1 & 0x100) != 0)
                || ((status & 0xE) != 0 && (control3 & 1) != 0)
                || ((status & 0x100) != 0 && (control2 & 0x40) != 0)
                || ((status & 0x200) != 0 && (control3 & 0x400) != 0)));
            RxDMA.Set(enabled && (control1 & 4) != 0 && (control3 & 0x40) != 0 && Count != 0);
            TxDMA.Set(enabled && (control1 & 8) != 0 && (control3 & 0x80) != 0 && (flags & 0x80) != 0);
        }
        private readonly int receiveFifoDepth;
        private uint control1, control2, control3, baud, guard, flags;
        private bool statusRead;
    }
}
