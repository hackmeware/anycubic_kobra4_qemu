// SPDX-License-Identifier: MIT
// Explicit generic two-coil stationary electrical testbench, not an identified board.
using System;
using Antmicro.Renode.Core;
namespace Antmicro.Renode.Peripherals.AT32
{
    public class GenericStationaryMotorRL : IPeripheral, IGPIOReceiver
    {
        public GenericStationaryMotorRL(IMachine machine, AT32Timer tmr2, AT32Timer tmr1,
            AT32Timer tmr3, AT32Timer tmr4, AT32Timer tmr8, AT32ADC adc1, AT32ADC adc2, AT32ADC adc3,
            double supplyVoltage = 24, double resistanceOhms = 2, double inductanceHenries = 0.003,
            double adcCountsPerAmp = 500, double adcOffset = 2048)
        {
            this.machine = machine; timers = new[]{tmr3,tmr1,tmr4}; adcs = new[]{adc1,adc2,adc3};
            Configure(supplyVoltage,resistanceOhms,inductanceHenries,adcCountsPerAmp,adcOffset);
            tmr2.TriggerOutput.Connect(tmr1,17); tmr2.TriggerOutput.Connect(tmr3,17); tmr2.TriggerOutput.Connect(tmr4,17);
            tmr1.TriggerOutput.Connect(tmr8,16); tmr8.TriggerOutput.Connect(this,0);
            Reset();
            for(int axis=0;axis<3;axis++)
            {
                int a=axis;
                timers[a].ConfigurationChanging += () => AdvanceAxisToNow(a);
                timers[a].ConfigurationChanged += () => UpdateDrive(a);
            }
        }
        public void Configure(double supplyVoltage, double resistanceOhms, double inductanceHenries, double adcCountsPerAmp, double adcOffset)
        {
            if(!Finite(supplyVoltage) || supplyVoltage<0 || !Finite(resistanceOhms) || resistanceOhms<=0
                || !Finite(inductanceHenries) || inductanceHenries<=0 || !Finite(adcCountsPerAmp) || adcCountsPerAmp<=0
                || !Finite(adcOffset) || adcOffset<0 || adcOffset>4095) throw new ArgumentException("Invalid physical parameters");
            if(ResistanceOhms>0) for(int axis=0;axis<3;axis++) AdvanceAxisToNow(axis);
            SupplyVoltage=supplyVoltage; ResistanceOhms=resistanceOhms; InductanceHenries=inductanceHenries;
            AdcCountsPerAmp=adcCountsPerAmp; AdcOffset=adcOffset;
            if(timers!=null) for(int axis=0;axis<3;axis++) UpdateDrive(axis);
        }
        public void Reset()
        {
            Array.Clear(currents,0,currents.Length); TriggerCount=0; ClippedSamples=0;
            for(int a=0;a<3;a++) { lastTime[a]=Now; UpdateDrive(a); }
            PublishSamples();
        }
        public void OnGPIO(int number, bool value)
        {
            if(number!=0 || !value) return;
            for(int a=0;a<3;a++) AdvanceAxisToNow(a);
            PublishSamples(); TriggerCount++;
            foreach(var adc in adcs) adc.TriggerPreempt(15);
        }
        // Deterministic equation entry point for tests; runtime invokes only from actual TMR8 TRGO.
        public void Advance(double seconds)
        {
            if(!Finite(seconds) || seconds<0) throw new ArgumentException("Invalid elapsed time");
            for(int axis=0;axis<3;axis++) IntegrateAxis(axis,seconds);
            PublishSamples();
        }
        private void AdvanceAxisToNow(int axis)
        {
            double now=Now, seconds=Math.Max(0,now-lastTime[axis]); lastTime[axis]=now;
            if(seconds>0) IntegrateAxis(axis,seconds);
        }
        private void UpdateDrive(int axis)
        {
            for(int phase=0;phase<2;phase++) driveVoltage[axis*2+phase]=GetPhaseVoltage(axis,phase);
        }
        private void IntegrateAxis(int axis,double seconds)
        {
            double decay=Math.Exp(-seconds*ResistanceOhms/InductanceHenries);
            for(int phase=0;phase<2;phase++)
            {
                int index=axis*2+phase;
                double equilibrium=driveVoltage[index]/ResistanceOhms;
                currents[index]=OpenWinding ? 0 : equilibrium+(currents[index]-equilibrium)*decay;
            }
        }
        public double GetCurrent(int axis,int phase) { Validate(axis,phase); return currents[axis*2+phase]; }
        public double GetPhaseVoltage(int axis,int phase)
        {
            Validate(axis,phase); var timer=timers[axis];
            if(!timer.Enabled || (timer.ReadDoubleWord(0)&1)==0 || (axis==1 && (timer.ReadDoubleWord(0x44)&0x8000)==0)) return 0;
            return SupplyVoltage*(HighFraction(timer,phase*2)-HighFraction(timer,phase*2+1));
        }
        private static double HighFraction(AT32Timer timer,int channel)
        {
            uint enables=timer.ReadDoubleWord(0x20);
            if((enables&(1u<<(channel*4)))==0) return 0;
            uint config=timer.ReadDoubleWord(channel<2?0x18:0x1C)>>(8*(channel%2));
            if((config&3)!=0) return 0;
            uint mode=(config>>4)&7;
            double high;
            if(mode==4) high=0;
            else if(mode==5) high=1;
            else if(mode==6 || mode==7)
            {
                uint period=timer.ReadDoubleWord(0x2C); if(period==0) return 0;
                high=Math.Min(1.0,(double)timer.ReadDoubleWord(0x34+4*channel)/period);
                if(mode==7) high=1-high;
            }
            else return 0; // Unmodeled waveform modes never invent a drive voltage.
            return (enables&(2u<<(channel*4)))!=0 ? 1-high : high;
        }
        private void PublishSamples()
        {
            for(int axis=0;axis<3;axis++) for(int phase=0;phase<2;phase++)
            {
                // Generic ideal switched low-side sampling: sensed sign follows the first bridge leg.
                // This is a topology assumption consistent with firmware's PWM-polarity sign correction.
                int sign=(timers[axis].ReadDoubleWord(0x20)&(2u<<(phase*8)))==0 ? 1 : -1;
                double sample=AdcOffset+sign*currents[axis*2+phase]*AdcCountsPerAmp;
                if(sample<0 || sample>4095) ClippedSamples++;
                adcs[axis].SetChannelValue(channels[axis*2+phase],(ushort)Math.Max(0,Math.Min(4095,Math.Round(sample))));
            }
        }
        private double Now => machine.ElapsedVirtualTime.TimeElapsed.TotalSeconds;
        private static bool Finite(double x) => !double.IsNaN(x) && !double.IsInfinity(x);
        private static void Validate(int axis,int phase) { if(axis<0 || axis>2 || phase<0 || phase>1) throw new ArgumentOutOfRangeException(); }
        public bool OpenWinding { get; set; }
        public double SupplyVoltage { get; private set; }
        public double ResistanceOhms { get; private set; }
        public double InductanceHenries { get; private set; }
        public double AdcCountsPerAmp { get; private set; }
        public double AdcOffset { get; private set; }
        public ulong TriggerCount { get; private set; }
        public ulong ClippedSamples { get; private set; }
        private readonly IMachine machine;
        private readonly AT32Timer[] timers;
        private readonly AT32ADC[] adcs;
        private readonly double[] currents=new double[6];
        private readonly int[] channels={0,4,5,6,12,10};
        private readonly double[] lastTime=new double[3], driveVoltage=new double[6];
    }
}
