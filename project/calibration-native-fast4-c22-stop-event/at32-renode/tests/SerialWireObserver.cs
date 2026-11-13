// SPDX-License-Identifier: MIT
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    public class SerialWireObserver : IPeripheral
    {
        public SerialWireObserver(AT32VirtualSerialWire wire) { wire.CharReceived += Receive; }
        public uint Count { get; private set; }
        public uint Signature { get; private set; }
        public void Reset() { Count = Signature = 0; }
        private void Receive(byte value) { Count++; Signature = (Signature << 8) | value; }
    }
}
