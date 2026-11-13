// SPDX-License-Identifier: MIT
// Independent, deliberately limited LIS2DW12 model. No bundled-core queue access.
// DS11811 Rev 9: registers, 1600 Hz high-performance format and FIFO modes.
// AN5038 Rev 6: FIFO overrun clears after a complete sample set is read.
using System;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.SPI;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.SensorCrossBoard
{
    public sealed class AccelerationVector
    {
        public AccelerationVector(decimal x, decimal y, decimal z) { X=x; Y=y; Z=z; }
        public decimal X { get; private set; }
        public decimal Y { get; private set; }
        public decimal Z { get; private set; }
    }

    // Destination-machine acquisition contract; the source may consume a verified shared-domain mailbox.
    public interface ICausalAccelerationSource
    {
        IMachine AcquisitionMachine { get; }
        bool HasValue { get; }
        AccelerationVector SampleAt(ulong nanoseconds);
    }

    // Explicit zero-order-hold input in sensor-coordinate g. A plant must update
    // it AT the relevant virtual instant, after doing its own causal dynamics.
    // There is no future queue, interpolation, noise, gravity or resonance here.
    public sealed class CausalAccelerationInput : IPeripheral, ICausalAccelerationSource
    {
        public CausalAccelerationInput(IMachine machine)
        { if(machine==null) throw new ArgumentNullException("machine"); this.machine=machine; Reset(); }
        public IMachine AcquisitionMachine { get { return machine; } }
        public void SetNow(decimal x, decimal y, decimal z)
        {
            value=new AccelerationVector(x,y,z);
            LastUpdateNanoseconds=machine.ClockSource.CurrentValue.TotalNanoseconds;
        }
        public AccelerationVector SampleAt(ulong nanoseconds)
        {
            if(value==null) throw new InvalidOperationException("Acceleration input must be initialized explicitly.");
            if(nanoseconds!=machine.ClockSource.CurrentValue.TotalNanoseconds || nanoseconds<LastUpdateNanoseconds)
                throw new InvalidOperationException("Acceleration samples must be requested at the current virtual instant.");
            return value;
        }
        public bool HasValue { get { return value!=null; } }
        public ulong LastUpdateNanoseconds { get; private set; }
        public void Reset() { value=null; LastUpdateNanoseconds=0; }
        private readonly IMachine machine;
        private AccelerationVector value;
    }

    public sealed class TimedLis2dw12 : ISPIPeripheral, IGPIOReceiver
    {
        public TimedLis2dw12(IMachine machine, ICausalAccelerationSource source)
        {
            if(machine==null || source==null) throw new ArgumentNullException("machine/source");
            if(!Object.ReferenceEquals(machine,source.AcquisitionMachine))
                throw new NotSupportedException("Sensor must use the input delivery endpoint on its own acquisition machine.");
            this.machine=machine; this.source=source;
            timer=new LimitTimer(machine.ClockSource,1000000,this,"LIS2DW12 1600 Hz acquisition",625,
                direction:Direction.Ascending,workMode:WorkMode.Periodic,enabled:false,eventEnabled:true);
            timer.LimitReached+=Acquire;
            Reset();
        }
        public uint SampleRate { get { return (ctrl1==0x94) ? 1600u : 0u; } }
        public int FullScaleG { get { return ctrl6==0x34 ? 16 : 2; } }
        public decimal SensitivityGPerDigit { get { return ctrl6==0x34 ? 0.001952m : 0.000244m; } }
        public bool LowNoiseSelected { get { return (ctrl6&4)!=0; } }
        public bool PhysicalFilterModeled { get { return false; } }
        public bool PhysicalNoiseModeled { get { return false; } }
        public string SignalModelFidelity { get { return "Idealized unfiltered/noiseless acquisition; CTRL6 filter/noise bits are readback only; no physical or native-integration validation."; } }
        public bool IsSampling { get { return timer.Enabled; } }
        public int FifoCount { get { return fifo.Count; } }
        public ulong GeneratedSamples { get; private set; }
        public ulong OverwrittenSamples { get; private set; }
        public ulong StoppedFifoSamples { get; private set; }
        public ulong LastSampleNanoseconds { get; private set; }
        public string SourceFault { get; private set; }
        public ulong[] FifoTimesNanoseconds
        {
            get { var a=new ulong[fifo.Count]; var i=0; foreach(var frame in fifo) a[i++]=frame.Time; return a; }
        }

        public void Reset()
        {
            timer.Reset(); timer.Enabled=false; timer.Value=0;
            ctrl1=0; ctrl2=4; ctrl6=0; fifoControl=0;
            fifo.Clear(); latest=null; latched=null; nextOutput=0;
            overrun=false; fifoStopped=false; dataReady=false;
            GeneratedSamples=OverwrittenSamples=StoppedFifoSamples=LastSampleNanoseconds=0;
            SourceFault=null; FinishTransmission();
            // The external physical input is intentionally NOT reset here.
        }
        public void OnGPIO(int number,bool value)
        {
            if(number!=0) throw new ArgumentOutOfRangeException("number","Only explicit active-low CS input 0 exists.");
            if(value) FinishTransmission();
            else if(!selected) { selected=true; hasCommand=false; }
        }
        public void FinishTransmission()
        {
            pendingRead=null;
            selected=false; hasCommand=false; address=0;
            // The output latch survives CS, permitting six single-register reads.
        }
        public byte Transmit(byte value)
        {
            if(!selected) return 0xFF; // Fixture pull-up convention; not high-impedance modeling.
            if(!hasCommand)
            {
                address=(byte)(value&0x7F); reading=(value&0x80)!=0; hasCommand=true; return 0xFF;
            }
            try
            {
                byte result=0xFF;
                if(reading) result=ReadRegister(address); else WriteRegister(address,value);
                if(selected && (ctrl2&4)!=0)
                    address=(byte)(reading && address==0x2D && FifoMode!=0 ? 0x28 : ((address+1)&0x7F));
                return result;
            }
            catch { FinishTransmission(); throw; }
        }
        // GPIO transport extension: reserve one immutable response without changing
        // address, output cursor, FIFO or flags. Commit only after all 8 sample edges.
        // Exclusive ownership of the SPI transaction by one transport is required.
        public sealed class ReadReservation
        {
            public byte Value { get; internal set; }
            internal byte Address, Ctrl2, FifoControl;
            internal int Offset, ExpectedOutput;
            internal object Frame, ExpectedLatch;
        }
        public ReadReservation PrepareReadByte()
        {
            try
            {
                if(!selected || !hasCommand || !reading || pendingRead!=null)
                    throw new InvalidOperationException("A selected read transaction and no pending byte are required.");
                var p=new ReadReservation { Address=address, Ctrl2=ctrl2, FifoControl=fifoControl,
                    Offset=-1, ExpectedOutput=nextOutput, ExpectedLatch=latched };
                if(address>=0x28 && address<=0x2D)
                {
                    if(SourceFault!=null) throw new InvalidOperationException("Sample source/clock failed: "+SourceFault);
                    var offset=address-0x28;
                    Frame frame;
                    if(offset==0)
                    {
                        if(FifoMode==0 && (ctrl2&8)==0)
                            throw new NotSupportedException("Bypass output reads require BDU=1 in this coherent-vector subset.");
                        frame=FifoMode==0 ? latest : (fifo.Count==0 ? null : fifo.Peek());
                        if(frame==null) throw new InvalidOperationException("No timed acceleration sample is available.");
                    }
                    else
                    {
                        if(latched==null || offset!=nextOutput)
                            throw new NotSupportedException("Output reads must follow X_L, X_H, Y_L, Y_H, Z_L, Z_H order.");
                        frame=latched;
                    }
                    p.Offset=offset; p.Frame=frame; p.Value=frame.Bytes[offset];
                }
                else p.Value=ReadRegister(address); // These implemented registers have no read side effects.
                pendingRead=p; return p;
            }
            catch { FinishTransmission(); throw; }
        }
        public void CommitReadByte(ReadReservation p)
        {
            try
            {
                if(p==null || !Object.ReferenceEquals(pendingRead,p) || !selected || !hasCommand || !reading
                    || address!=p.Address || ctrl2!=p.Ctrl2 || fifoControl!=p.FifoControl
                    || nextOutput!=p.ExpectedOutput || !Object.ReferenceEquals(latched,p.ExpectedLatch))
                    throw new InvalidOperationException("Read reservation was canceled, reset or changed.");
                if(p.Offset>=0)
                {
                    if(SourceFault!=null) throw new InvalidOperationException("Sample source/clock failed: "+SourceFault);
                    var frame=(Frame)p.Frame;
                    latched=frame; nextOutput=p.Offset+1;
                    if(nextOutput==6)
                    {
                        // The original head may have been overwritten during this byte.
                        // Never consume its replacement head or invent another sample.
                        if(FifoMode!=0)
                        {
                            if(fifo.Count!=0 && Object.ReferenceEquals(fifo.Peek(),frame)) fifo.Dequeue();
                            overrun=false;
                        }
                        if(Object.ReferenceEquals(latest,frame)) dataReady=false;
                        latched=null; nextOutput=0;
                    }
                }
                pendingRead=null;
                if(selected && (ctrl2&4)!=0)
                    address=(byte)(address==0x2D && FifoMode!=0 ? 0x28 : ((address+1)&0x7F));
            }
            catch { FinishTransmission(); throw; }
        }
        public void CancelReadByte() { pendingRead=null; }
        private ReadReservation pendingRead;

        public byte ReadRegister(byte register)
        {
            if(register>=0x28 && register<=0x2D) return ReadOutput(register);
            switch(register)
            {
                case 0x0F: return 0x44;
                case 0x20: return ctrl1;
                case 0x21: return ctrl2;
                case 0x22: case 0x23: case 0x24: return 0;
                case 0x25: return ctrl6;
                case 0x27: return (byte)(dataReady ? 1 : 0);
                case 0x2E: return fifoControl;
                case 0x2F:
                    return (byte)(fifo.Count|(overrun?0x40:0)|((fifoControl&31)!=0 && fifo.Count>=(fifoControl&31) ? 0x80 : 0));
                default: throw new NotSupportedException("Register read not implemented: 0x"+register.ToString("X2"));
            }
        }
        public void WriteRegister(byte register,byte value)
        {
            switch(register)
            {
                case 0x20:
                    if(value!=0 && value!=4 && value!=0x94)
                        throw new NotSupportedException("Only power-down CTRL1=0/4 and high-performance 1600 Hz CTRL1=0x94 are supported.");
                    if(value==0x94 && !source.HasValue)
                        throw new InvalidOperationException("Initialize the causal acceleration source before enabling acquisition.");
                    if(ctrl1==value) return; // An identical configuration does not shift sample phase.
                    timer.Enabled=false; timer.Value=0; ctrl1=value;
                    if(SampleRate!=0)
                    {
                        SourceFault=null;
                        nextSampleNanoseconds=checked(machine.ClockSource.CurrentValue.TotalNanoseconds+625000ul);
                        timer.Enabled=true;
                    }
                    return;
                case 0x21:
                    if((value&~0x4C)!=0) throw new NotSupportedException("Only IF_ADD_INC, BDU and SOFT_RESET are implemented in CTRL2.");
                    if((value&0x40)!=0) { Reset(); return; }
                    ctrl2=value; return;
                case 0x22: case 0x23: case 0x24:
                    if(value!=0) throw new NotSupportedException("Interrupts and other CTRL3..5 functions are not implemented.");
                    return;
                case 0x25:
                    // Exact proven startup profile only. Filter and low-noise bits
                    // are retained, NOT simulated: see SignalModelFidelity.
                    if(value!=0 && value!=0x34)
                        throw new NotSupportedException("Only reset CTRL6=0 and native CTRL6=0x34 are supported; filter/noise response is not modeled.");
                    if(value==ctrl6) return; // Idempotent write never changes phase or stored frames.
                    // Fail closed instead of mixing scales or silently discarding/re-encoding
                    // old FIFO, output-latched or byte-reserved vectors. A sensor reset
                    // is required after any acquisition before selecting another scale.
                    if(SampleRate!=0 || latest!=null || fifo.Count!=0 || latched!=null || pendingRead!=null)
                        throw new NotSupportedException("CTRL6 changes require reset-clean power-down with no acquired, latched or reserved frame.");
                    ctrl6=value; return;
                case 0x2E:
                    var mode=(value>>5)&7;
                    if(mode!=0 && mode!=1 && mode!=6) throw new NotSupportedException("Only bypass, FIFO and continuous FIFO modes are implemented.");
                    if(FifoMode!=0 && mode!=0 && mode!=FifoMode)
                        throw new NotSupportedException("Change between active FIFO modes through bypass.");
                    if(mode==0)
                    {
                        fifo.Clear(); overrun=false; fifoStopped=false; latched=null; nextOutput=0;
                    }
                    else if(FifoMode==0) { latched=null; nextOutput=0; }
                    fifoControl=value; return;
                default: throw new NotSupportedException("Register write not implemented: 0x"+register.ToString("X2"));
            }
        }
        private void Acquire()
        {
            var now=machine.ClockSource.CurrentValue.TotalNanoseconds;
            try
            {
                if(now!=nextSampleNanoseconds)
                    throw new InvalidOperationException("Virtual sample deadline mismatch: expected "+nextSampleNanoseconds+", actual "+now);
                var v=source.SampleAt(now);
                var frame=new Frame(now,v,SensitivityGPerDigit);
                nextSampleNanoseconds=checked(nextSampleNanoseconds+625000ul);
                LastSampleNanoseconds=now; GeneratedSamples++; latest=frame; dataReady=true;
                if(FifoMode==0) return;
                if(FifoMode==1 && fifoStopped) { StoppedFifoSamples++; return; }
                if(fifo.Count==32)
                {
                    fifo.Dequeue(); OverwrittenSamples++; overrun=true;
                }
                fifo.Enqueue(frame);
                if(FifoMode==1 && fifo.Count==32) fifoStopped=true;
            }
            catch(Exception e)
            {
                SourceFault=e.Message; timer.Enabled=false;
                // No invented replacement sample. All later data access fails visibly.
            }
        }
        private byte ReadOutput(byte register)
        {
            if(SourceFault!=null) throw new InvalidOperationException("Sample source/clock failed: "+SourceFault);
            var offset=register-0x28;
            if(offset==0)
            {
                // Restarting X_L explicitly abandons any partial vector without consuming it.
                latched=null; nextOutput=0;
                if(FifoMode==0)
                {
                    if((ctrl2&8)==0) throw new NotSupportedException("Bypass output reads require BDU=1 in this coherent-vector subset.");
                    latched=latest;
                }
                else if(fifo.Count!=0) latched=fifo.Peek();
                if(latched==null) throw new InvalidOperationException("No timed acceleration sample is available.");
            }
            if(latched==null || offset!=nextOutput)
                throw new NotSupportedException("Output reads must follow X_L, X_H, Y_L, Y_H, Z_L, Z_H order.");
            var result=latched.Bytes[offset]; nextOutput++;
            if(nextOutput==6)
            {
                if(FifoMode!=0)
                {
                    // A continuously overwritten latched head may already be absent.
                    if(fifo.Count!=0 && Object.ReferenceEquals(fifo.Peek(),latched)) fifo.Dequeue();
                    overrun=false;
                }
                if(Object.ReferenceEquals(latest,latched)) dataReady=false;
                latched=null; nextOutput=0;
            }
            return result;
        }
        private int FifoMode { get { return (fifoControl>>5)&7; } }
        private sealed class Frame
        {
            public Frame(ulong time,AccelerationVector value,decimal sensitivityGPerDigit)
            {
                this.sensitivityGPerDigit=sensitivityGPerDigit;
                Time=time; Bytes=new byte[6]; Encode(value.X,0); Encode(value.Y,2); Encode(value.Z,4);
            }
            private void Encode(decimal g,int offset)
            {
                // Freeze the selected nominal sensitivity at acquisition, signed14 left-aligned.
                // +/-2g: 0.244 mg/digit; +/-16g: 1.952 mg/digit. No filter/noise DSP.
                g=Math.Max(-8192m*sensitivityGPerDigit,Math.Min(8191m*sensitivityGPerDigit,g));
                var digit=Decimal.Round(g/sensitivityGPerDigit,0,MidpointRounding.AwayFromZero);
                var raw=(short)((int)digit*4);
                Bytes[offset]=(byte)(raw&0xFF); Bytes[offset+1]=(byte)(((ushort)raw)>>8);
            }
            private readonly decimal sensitivityGPerDigit;
            public readonly ulong Time;
            public readonly byte[] Bytes;
        }
        private readonly IMachine machine;
        private readonly ICausalAccelerationSource source;
        private readonly LimitTimer timer;
        private readonly Queue<Frame> fifo=new Queue<Frame>();
        private Frame latest,latched;
        private byte ctrl1,ctrl2,ctrl6,fifoControl,address;
        private int nextOutput;
        private bool overrun,fifoStopped,dataReady,selected,hasCommand,reading;
        private ulong nextSampleNanoseconds;
    }
}
