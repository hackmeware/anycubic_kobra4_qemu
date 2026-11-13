// SPDX-License-Identifier: MIT
// Diagnostic USART2 downstream gateway. This is NOT the original motor MCU.
// Observed TMC register transport and explicit optional metadata; never motion or homing.
using System;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.AT32
{
    public class VirtualMotorTmcGateway : IDoubleWordPeripheral, IKnownSize
    {
        public VirtualMotorTmcGateway(IMachine machine, AT32UART uart, uint baud = 576000)
        {
            this.uart = uart;
            timer = new LimitTimer(machine.ClockSource, baud, this, "diagnostic gateway RX", 10,
                direction: Direction.Ascending, workMode: WorkMode.Periodic, enabled: false, eventEnabled: true);
            timer.LimitReached += Deliver;
            uart.CharReceived += ReceiveByte;
            Reset();
        }
        public long Size { get { return 0x20; } }
        public bool Disconnected { get; set; }
        // Explicit synthetic blank persistence state; never inferred from real hardware.
        public bool BlankPowerDownRecord { get; set; }
        public uint PowerDownQueries { get; private set; }
        public bool EmulateFirmwareVersion { get; set; }
        public uint VersionQueries { get; private set; }
        public bool CorruptTmcReplyCrc { get; set; }
        public uint DriverFaultStatus { get; set; }
        public uint ValidFrames { get; private set; }
        public uint RejectedFrames { get; private set; }
        public uint UnsupportedFrames { get; private set; }
        public uint Reads { get; private set; }
        public uint Writes { get; private set; }
        public string LastReply { get; private set; }
        public int PendingBytes { get { return pending.Count; } }
        public void Reset()
        {
            input.Clear(); pending.Clear(); registers.Clear();
            timer.Reset(); timer.Enabled = false; timer.Value = 0;
            ValidFrames = RejectedFrames = UnsupportedFrames = Reads = Writes = PowerDownQueries = VersionQueries = 0;
            // External disconnect/driver/CRC fault settings survive a device reset.
            LastReply = "";
        }
        public uint ReadDoubleWord(long offset)
        {
            switch(offset) { case 0:return ValidFrames; case 4:return RejectedFrames; case 8:return UnsupportedFrames;
            case 12:return Reads; case 16:return Writes; case 20:return (uint)PendingBytes; default:return 0; }
        }
        public void WriteDoubleWord(long offset, uint value) { this.LogUnhandledWrite(offset, value); }
        public void ReceiveByte(byte value)
        {
            if(input.Count == 0 && value != 0x7e) return;
            input.Add(value);
            if(input.Count < 4) return;
            if(input[3] > 58) { RejectedFrames++; input.Clear(); return; }
            if(input.Count < input[3] + 6) return;
            var frame = input.ToArray(); input.Clear();
            if(Crc16(frame, frame.Length - 2) != (frame[frame.Length-2] | frame[frame.Length-1]<<8))
            { RejectedFrames++; return; }
            ValidFrames++;
            if(Disconnected) return;
            if(frame[2] == 0x10 && frame[3] == 4)
            {
                // Observed periodic clock update. Accept transport only, no invented time/motion reply.
                Ack(frame[1]); return;
            }
            if(frame[2] == 0x17 && EmulateFirmwareVersion)
            {
                if(frame[3] != 1) { RejectedFrames++; return; }
                // Original motor v1.6.01 handler 0x0800e198 returns these literal
                // version bytes. This diagnostic model is not executing that MCU.
                VersionQueries++; Ack(frame[1]); Send(0x18, new byte[]{frame[4],1,6,1}); return;
            }
            if(frame[2] == 0x22 && BlankPowerDownRecord)
            {
                // Original handler 0x0800e3a8 ignores request payload and returns
                // PowerDown_data saved-position words. This explicit blank virtual
                // record is not current position, calibration or homing success.
                PowerDownQueries++; Ack(frame[1]); Send(0x23, new byte[12]); return;
            }
            if(frame[2] != 8 || (frame[3] != 5 && frame[3] != 9))
            { UnsupportedFrames++; this.Log(LogLevel.Warning, "Unsupported diagnostic motor command 0x{0:X2}; no response", frame[2]); return; }
            var oid = frame[4]; var count = frame[3]-1;
            var tmc = new byte[count]; Array.Copy(frame,5,tmc,0,count);
            if((tmc[0]&15) != 5 || tmc[1] < 1 || tmc[1] > 3 || Crc8(tmc,count-1) != tmc[count-1])
            { RejectedFrames++; return; }
            var address=tmc[1]; var reg=(byte)(tmc[2]&127); var writing=(tmc[2]&128)!=0;
            if(writing != (count == 8)) { RejectedFrames++; return; }
            if(!registers.ContainsKey(address)) registers[address] = NewBank();
            var bank=registers[address];
            if(writing && Writable(reg))
            {
                var val=(uint)tmc[3]<<24 | (uint)tmc[4]<<16 | (uint)tmc[5]<<8 | tmc[6];
                if(reg == 1) bank[1] &= ~val; else bank[reg]=val;
                bank[2]=(bank[2]+1)&255; Writes++; Ack(frame[1]);
                // Original motor handler 0x0800e15e echoes the entire write payload.
                // This is a controller completion echo, NOT a TMC silicon UART reply.
                var echo=new byte[count+1]; echo[0]=oid; Array.Copy(tmc,0,echo,1,count); Send(9,echo);
                return;
            }
            uint result;
            if(!bank.TryGetValue(reg,out result))
            { UnsupportedFrames++; this.Log(LogLevel.Warning,"Unsupported TMC register 0x{0:X2}; no response",reg); return; }
            if(reg==0x6f) result |= DriverFaultStatus; // never conceal injected status faults
            Reads++;
            var reply=new byte[]{oid,0x05,0xff,reg,(byte)(result>>24),(byte)(result>>16),(byte)(result>>8),(byte)result,0};
            var raw=new byte[8]; Array.Copy(reply,1,raw,0,8); reply[8]=Crc8(raw,7);
            if(CorruptTmcReplyCrc) reply[8]^=1;
            Ack(frame[1]); Send(9,reply);
        }
        private static Dictionary<byte,uint> NewBank()
        {
            // Values extracted from original motor MCU initialized table 0x20000340.
            var bank=new Dictionary<byte,uint>();
            foreach(byte reg in new byte[]{0,1,2,3,4,5,6,7,0x10,0x11,0x12,0x13,0x22,0x14,0x40,0x41,0x42,0x6a,0x6b,0x6c,0x6f,0x70,0x71,0x72,0x30}) bank[reg]=0;
            bank[0]=0x101; bank[0x10]=0x1f00; bank[0x11]=0x14; bank[0x6c]=0x10000053; bank[0x70]=0xc10d0024;
            return bank;
        }
        public void InjectGeneralStatus(byte address, uint bits)
        {
            if(address<1 || address>3 || (bits&~7u)!=0) throw new ArgumentOutOfRangeException();
            if(!registers.ContainsKey(address)) registers[address]=NewBank();
            registers[address][1] |= bits;
        }
        private static bool Writable(byte reg)
        {
            switch(reg) { case 0:case 1:case 3:case 4:case 7:case 0x10:case 0x11:case 0x13:case 0x14:
            case 0x22:case 0x30:case 0x40:case 0x42:case 0x6c:case 0x70:return true; default:return false; }
        }
        private void Ack(byte seq) { Send(0x12,new byte[]{seq,0}); }
        private void Send(byte command, byte[] payload)
        {
            // Motor-to-main framing is asymmetric: no transport sequence byte.
            var frame=new byte[payload.Length+5]; frame[0]=0x7e; frame[1]=command; frame[2]=(byte)payload.Length;
            Array.Copy(payload,0,frame,3,payload.Length); var crc=Crc16(frame,frame.Length-2);
            frame[frame.Length-2]=(byte)crc; frame[frame.Length-1]=(byte)(crc>>8);
            LastReply=BitConverter.ToString(frame).Replace("-","").ToLowerInvariant();
            foreach(var b in frame) pending.Enqueue(b);
            if(!timer.Enabled) { timer.Value=0; timer.Enabled=true; }
        }
        private void Deliver()
        {
            if(pending.Count==0) {timer.Enabled=false;return;}
            uart.WriteChar(pending.Dequeue()); if(pending.Count==0) timer.Enabled=false;
        }
        public static byte Crc8(byte[] bytes, int count)
        {
            byte crc=0;
            for(var i=0;i<count;i++) {var b=bytes[i]; for(var bit=0;bit<8;bit++) { crc=(byte)(((crc>>7)^(b&1))!=0 ? (crc<<1)^7 : crc<<1); b>>=1; }}
            return crc;
        }
        public static ushort Crc16(byte[] bytes, int count)
        {
            uint crc=0xffff;
            for(var i=0;i<count;i++) {uint b=bytes[i]^(crc&255);b^=(b&15)<<4;crc=(((b<<8)|(crc>>8))^(b>>4)^(b<<3))&65535;}
            return (ushort)crc;
        }
        private readonly AT32UART uart;
        private readonly LimitTimer timer;
        private readonly List<byte> input=new List<byte>();
        private readonly Queue<byte> pending=new Queue<byte>();
        private readonly Dictionary<byte,Dictionary<byte,uint>> registers=new Dictionary<byte,Dictionary<byte,uint>>();
    }
}
