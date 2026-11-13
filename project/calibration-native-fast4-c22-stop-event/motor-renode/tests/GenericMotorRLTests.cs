using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    public class GenericMotorRLTests : IPeripheral
    {
        public GenericMotorRLTests(GenericStationaryMotorRL plant, AT32Timer tmr1, AT32Timer tmr2,
            AT32Timer tmr3, AT32Timer tmr4, AT32Timer tmr8, AT32ADC adc1)
        { this.plant=plant; this.t1=tmr1; this.t2=tmr2; this.t3=tmr3; this.t4=tmr4; this.t8=tmr8; this.adc=adc1; }
        public void Reset() { }
        void Check(bool x,string label) { if(!x) throw new Exception(label); checks++; }
        void Near(double x,double y,string label) { Check(Math.Abs(x-y)<1e-8,label+": "+x+" != "+y); }
        void Drive(AT32Timer t)
        {
            t.Reset(); t.WriteDoubleWord(0x2C,1000); t.WriteDoubleWord(0x18,0x6060);
            t.WriteDoubleWord(0x1C,0x6060); t.WriteDoubleWord(0x20,0x1111);
            t.WriteDoubleWord(0x34,750); t.WriteDoubleWord(0x38,250); t.WriteDoubleWord(0x44,0x8000); t.WriteDoubleWord(0,1);
        }
        public string Equations()
        {
            checks=0; foreach(var t in new[]{t1,t2,t3,t4,t8}) t.Reset();
            plant.Configure(24,2,0.003,500,2048); plant.OpenWinding=false; plant.Reset(); Drive(t3);
            Near(plant.GetPhaseVoltage(0,0),12,"differential PWM voltage");
            plant.Advance(0.0015); double initial=6*(1-Math.Exp(-1));
            Near(plant.GetCurrent(0,0),initial,"RL analytic step");
            Near(plant.GetCurrent(1,0),0,"disabled axis no current");
            t3.WriteDoubleWord(0x20,0x1133); Near(plant.GetPhaseVoltage(0,0),-12,"polarity reversal changes voltage");
            plant.Advance(0); Near(plant.GetCurrent(0,0),initial,"reversal cannot jump current");
            plant.Advance(0.0001); Check(plant.GetCurrent(0,0)>0 && plant.GetCurrent(0,0)<initial,"current continuous after reversal");
            double before=plant.GetCurrent(0,0); t3.WriteDoubleWord(0,0); plant.Advance(0.0015);
            Near(plant.GetCurrent(0,0),before*Math.Exp(-1),"disabled-drive RL decay");
            Drive(t3); plant.Configure(0,2,0.003,500,2048); plant.Reset(); plant.Advance(1);
            Near(plant.GetCurrent(0,0),0,"zero supply remains zero");
            plant.Configure(2.4,2,0.003,500,2048); plant.Reset(); plant.Advance(1);
            Near(plant.GetCurrent(0,0),0.6,"low supply scales physical equilibrium without threshold logic");
            plant.Configure(24,2,0.003,500,2048); plant.OpenWinding=true; plant.Reset(); plant.Advance(1);
            Near(plant.GetCurrent(0,0),0,"open winding cannot generate current");
            plant.OpenWinding=false; plant.Reset(); Drive(t1); t1.WriteDoubleWord(0x44,0);
            Near(plant.GetPhaseVoltage(1,0),0,"advanced timer MOE gates plant drive");
            t1.WriteDoubleWord(0x44,0x8000); Near(plant.GetPhaseVoltage(1,0),12,"MOE enabled permits drive");
            plant.Reset(); Drive(t3); t3.WriteDoubleWord(0x34,1000); t3.WriteDoubleWord(0x38,0);
            plant.Advance(1); Check(plant.ClippedSamples>0,"overrange current clips ADC");
            adc.Reset(); adc.WriteDoubleWord(0x38,0); adc.WriteDoubleWord(8,0x0100F001); adc.TriggerPreempt(15);
            Check(adc.ReadDoubleWord(0x3C)==4095,"ADC positive saturation is4095");
            t3.WriteDoubleWord(0x20,0x1133); plant.Advance(0); adc.TriggerPreempt(15);
            Check(adc.ReadDoubleWord(0x3C)==0,"reversed sample polarity clips negative current reading");
            foreach(var t in new[]{t1,t2,t3,t4,t8}) t.Reset(); plant.Reset(); adc.Reset();
            Near(plant.GetCurrent(0,0),0,"reset clears electrical energy");
            Check(plant.TriggerCount==0,"no free-running plant triggers");
            t2.WriteDoubleWord(0x2C,100); t2.WriteDoubleWord(4,0x10);
            t1.WriteDoubleWord(0x2C,100); t1.WriteDoubleWord(4,0x20); t1.WriteDoubleWord(8,0x16);
            t3.WriteDoubleWord(0x2C,100); t3.WriteDoubleWord(8,0x16);
            t4.WriteDoubleWord(0x2C,100); t4.WriteDoubleWord(8,0x16);
            t8.WriteDoubleWord(0x2C,10); t8.WriteDoubleWord(4,0x20); t8.WriteDoubleWord(8,6); t8.WriteDoubleWord(0,8);
            adc.WriteDoubleWord(0x38,0); adc.WriteDoubleWord(8,0x0100F001);
            return "GENERIC RL EQUATIONS PREPARED";
        }
        public string BeforeEnable() { Check(plant.TriggerCount==0,"stopped master suppresses plant and ADC"); t2.WriteDoubleWord(0,1); return "GENERIC RL CLOCK STARTED"; }
        public string AfterEnable()
        {
            Check(plant.TriggerCount>0,"real selected timer chain triggers plant");
            Check(t3.Enabled && t4.Enabled,"both real PWM timers started");
            Check(adc.ReadDoubleWord(0x3C)==2048,"undriven coil samples remain at offset");
            t2.WriteDoubleWord(0,0); t1.WriteDoubleWord(0,0); t8.WriteDoubleWord(0,8);
            priorTriggers=plant.TriggerCount; return "GENERIC RL CLOCK STOPPED";
        }
        public string AfterDisable()
        {
            Check(plant.TriggerCount==priorTriggers,"stopped timers suppress further samples");
            foreach(var t in new[]{t1,t2,t3,t4,t8}) t.Reset();
            plant.Configure(24,2,0.003,500,2048); Drive(t3);
            t3.WriteDoubleWord(0x18,0x4040); t3.WriteDoubleWord(0x1C,0x4040); t3.WriteDoubleWord(0x20,0x1111);
            plant.Reset(); t3.WriteDoubleWord(0x20,0x3131);
            Near(plant.GetPhaseVoltage(0,0),-24,"forced inactive plus inverted leg is a real brief voltage");
            return "GENERIC RL TRANSIENT STARTED";
        }
        public string EndShortPulse()
        {
            t3.WriteDoubleWord(0x20,0x1111);
            Near(plant.GetCurrent(0,0),-12*(1-Math.Exp(-0.000001*2/0.003)),"one microsecond transient energy before mutation");
            double prior=plant.GetCurrent(0,0);
            t3.WriteDoubleWord(0x20,0x3131); t3.WriteDoubleWord(0x20,0x1111);
            Near(plant.GetCurrent(0,0),prior,"same timestamp mutations add no energy");
            return "GENERIC RL TRANSIENT ENDED";
        }
        public string AfterShortPulse()
        {
            t8.WriteDoubleWord(4,0x20); t8.WriteDoubleWord(0x14,1);
            Near(plant.GetCurrent(0,0),-12*(1-Math.Exp(-0.000001*2/0.003))*Math.Exp(-0.000032*2/0.003),"ADC boundary sees only actual pulse duration then decay");
            return "GENERIC RL TESTS PASS: "+checks;
        }
        readonly GenericStationaryMotorRL plant; readonly AT32Timer t1,t2,t3,t4,t8; readonly AT32ADC adc; int checks; ulong priorTriggers;
    }
}
