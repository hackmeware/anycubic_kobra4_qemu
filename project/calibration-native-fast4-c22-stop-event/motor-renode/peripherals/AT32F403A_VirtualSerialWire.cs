// SPDX-License-Identifier: MIT
// External virtual serial-wire adapter, NOT a larger MCU UART receive FIFO.
using System;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Peripherals.UART;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.AT32
{
    public class AT32VirtualSerialWire : UARTBase, IDoubleWordPeripheral, IKnownSize
    {
        public AT32VirtualSerialWire(IMachine machine, AT32UART uart, uint baud = 576000,
            uint bitsPerFrame = 10, int capacity = 1048576) : base(machine)
        {
            if(baud == 0 || bitsPerFrame < 2 || capacity < 1) throw new ArgumentOutOfRangeException("Invalid virtual serial framing or capacity");
            this.uart = uart; this.baud = baud; this.bitsPerFrame = bitsPerFrame; this.capacity = capacity;
            timer = new LimitTimer(machine.ClockSource, baud, this, "external serial RX frame", bitsPerFrame,
                direction: Direction.Ascending, workMode: WorkMode.Periodic, enabled: false, eventEnabled: true);
            timer.LimitReached += DeliverFrame;
            uart.CharReceived += ForwardToHost;
            Reset();
        }
        public override uint BaudRate { get { return baud; } }
        public override Bits StopBits { get { return Bits.One; } }
        public override Parity ParityBit { get { return Parity.None; } }
        public uint BitsPerFrame { get { return bitsPerFrame; } }
        public int PendingBytes { get { lock(sync) return pending.Count; } }
        public ulong DeliveredBytes { get { lock(sync) return delivered; } }
        public ulong RejectedBytes { get { lock(sync) return rejected; } }
        // Optional monitor registration aperture. Not part of the real AT32 address map.
        public long Size { get { return 0x10; } }
        public uint ReadDoubleWord(long offset)
        {
            switch(offset) { case 0: return (uint)PendingBytes; case 4: return (uint)DeliveredBytes; case 8: return (uint)RejectedBytes; case 12: return baud; default: this.LogUnhandledRead(offset); return 0; }
        }
        public void WriteDoubleWord(long offset, uint value) { this.LogUnhandledWrite(offset, value); }
        public override void WriteChar(byte value)
        {
            lock(sync)
            {
                if(pending.Count >= capacity)
                {
                    rejected++;
                    this.Log(LogLevel.Error, "External serial-wire host queue full; rejected byte (total {0}). Increase adapter capacity or apply host backpressure.", rejected);
                    return;
                }
                pending.Enqueue(value);
                if(!timer.Enabled) { timer.Value = 0; timer.Enabled = true; }
            }
        }
        public override void Reset()
        {
            lock(sync)
            {
                pending.Clear(); delivered = rejected = 0;
                timer.Reset(); timer.Frequency = baud; timer.Limit = bitsPerFrame; timer.Value = 0; timer.Enabled = false;
            }
            base.Reset();
        }
        private void DeliverFrame()
        {
            lock(sync)
            {
                if(pending.Count == 0) { timer.Enabled = false; return; }
                var value = pending.Dequeue();
                if(pending.Count == 0) timer.Enabled = false;
                // Call the real UART. Disabled RX, unread-data overrun and IRQ behavior remain real.
                uart.WriteChar(value);
                delivered++;
            }
        }
        private void ForwardToHost(byte value) { TransmitCharacter(value); }
        protected override void CharWritten() { }
        protected override void QueueEmptied() { }
        private readonly object sync = new object();
        private readonly Queue<byte> pending = new Queue<byte>();
        private readonly AT32UART uart;
        private readonly LimitTimer timer;
        private readonly uint baud, bitsPerFrame;
        private readonly int capacity;
        private ulong delivered, rejected;
    }
}
