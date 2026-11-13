// SPDX-License-Identifier: MIT
// Two CPU-free machines. Explicit laboratory constant load, actual AT32 ADC timer integration.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.AT32;
using Antmicro.Renode.Peripherals.MotorExperimental;
using Antmicro.Renode.Peripherals.NozzleExperimental;
namespace Antmicro.Renode.Peripherals.PrinterExperimental
{
    public sealed class ZForceMotorLab : IPeripheral
    {
        public ZForceMotorLab(IMachine machine)
        {
            this.machine=machine;
            traced=new Rig(machine,"z-traced",16);quiet=new Rig(machine,"z-quiet",0);
            new MotorZForceSource(machine,traced.Fixture,traced.Trigger,100000,1000,16,0).Register("z-skew");
            new MotorZForceSource(machine,traced.Fixture,traced.Trigger,100000,1000,16,0).Register("z-rollback");
        }
        public void Reset(){}
        private void Check(bool v,string label){checks++;if(!v)throw new Exception(label);}
        private void Equal(double a,double b,string label){Check(BitConverter.DoubleToInt64Bits(a)==BitConverter.DoubleToInt64Bits(b),label);}
        public string VerifyPhysicalInvariance()
        {
            checks=0;
            Check(traced.Source.Bound&&quiet.Source.Bound,"both real motor sources bound across machine boundary");
            Check(!traced.Source.History.Faulted&&!quiet.Source.History.Faulted,"no history fault during ordinary conversion");
            Check(traced.Source.History.Retired>1000,"history safely retires during initial 302 ms settling");
            Check(traced.Source.History.Count<=5&&quiet.Source.History.Count<=5,"retention stays bounded for declared window");
            Check(traced.Source.MaximumCaptureIntervalNanoseconds<=34000&&traced.Source.MinimumCaptureIntervalNanoseconds>=32000,"captured actual trigger cadence justifies explicit 100 us age limit");
            Equal(traced.Plant.GetAngleRadians(2),quiet.Plant.GetAngleRadians(2),"trace on/off angle bitwise invariance");
            Equal(traced.Plant.GetVelocityRadiansPerSecond(2),quiet.Plant.GetVelocityRadiansPerSecond(2),"trace on/off speed bitwise invariance");
            Equal(traced.Plant.GetCurrent(2,0),quiet.Plant.GetCurrent(2,0),"trace on/off current A bitwise invariance");
            Equal(traced.Plant.GetCurrent(2,1),quiet.Plant.GetCurrent(2,1),"trace on/off current B bitwise invariance");
            Equal(traced.Plant.GetStoredEnergyJoules(2),quiet.Plant.GetStoredEnergyJoules(2),"trace on/off energy bitwise invariance");
            Check(traced.Plant.IntegrationCalls==quiet.Plant.IntegrationCalls,"trace on/off integration-count invariance");
            Check(traced.Plant.TriggerCount==quiet.Plant.TriggerCount,"trace on/off actual ADC-trigger-count invariance");
            ulong before=traced.Plant.IntegrationCalls;double angle=traced.Plant.GetAngleRadians(2),current=traced.Plant.GetCurrent(2,1);
            long now=checked((long)machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds);
            for(int i=0;i<100;i++){traced.Source.ReadAt(now);quiet.Source.ReadAt(now);}
            Check(traced.Plant.IntegrationCalls==before,"repeated history reads add no physical integration");
            Equal(traced.Plant.GetAngleRadians(2),angle,"history reads preserve angle");Equal(traced.Plant.GetCurrent(2,1),current,"history reads preserve current");
            return "Z FORCE PHYSICS INVARIANCE TESTS PASS: "+checks+"; actual_capture_interval_ns="+traced.Source.MinimumCaptureIntervalNanoseconds+".."+traced.Source.MaximumCaptureIntervalNanoseconds;
        }
        public void DisableFixtures(){traced.Fixture.SetEnabled(false);quiet.Fixture.SetEnabled(false);}
        public void StopAdcTriggers(){traced.Trigger.WriteDoubleWord(0,0);quiet.Trigger.WriteDoubleWord(0,0);}
        public void WriteTrace(string path){traced.Source.WriteTrace(path);}
        private sealed class Rig
        {
            public Rig(IMachine machine,string name,int traceRows)
            {
                var t2=new AT32Timer(machine,1000000);var t1=new AT32Timer(machine,1000000);var t3=new AT32Timer(machine,1000000);var t4=new AT32Timer(machine,1000000);
                Trigger=new AT32Timer(machine,1000000);
                Plant=new GenericStepperElectromechanical(machine,t2,t1,t3,t4,Trigger,new AT32ADC(),new AT32ADC(),new AT32ADC(),traceEveryTriggers:1000000);
                Fixture=new VirtualZBedContactFixture(Plant,bedRelativeMillimeters:-0.01,oppositeStopRelativeMillimeters:1);
                Fixture.SetEnabled(true);Plant.SetLoadTorque(2,0.002);
                Source=new MotorZForceSource(machine,Fixture,Trigger,100000,1000,16,traceRows);Source.Register(name);
                Trigger.WriteDoubleWord(0x2c,33);Trigger.WriteDoubleWord(4,0x20);Trigger.WriteDoubleWord(0,1);
            }
            public readonly GenericStepperElectromechanical Plant;public readonly VirtualZBedContactFixture Fixture;
            public readonly AT32Timer Trigger;public readonly MotorZForceSource Source;
        }
        private readonly IMachine machine;private readonly Rig traced,quiet;private int checks;
    }
    public sealed class ZForceNozzleLab : IPeripheral
    {
        public ZForceNozzleLab(IMachine machine)
        {
            this.machine=machine;
            portA=new Cs1237NativeGpio(machine);portB=new Cs1237NativeGpio(machine);
            sensorA=new Cs1237FunctionalAdapter(machine,portA,0,idealizedElectricalSemantics:true);
            sensorB=new Cs1237FunctionalAdapter(machine,portB,0,idealizedElectricalSemantics:true);
            Reject(()=>new Cs1237ZForceBinding(machine,portA,sensorA,"missing-source"),"missing named provider rejected");
            bindA=new Cs1237ZForceBinding(machine,portA,sensorA,"z-traced");bindB=new Cs1237ZForceBinding(machine,portB,sensorB,"z-quiet");
            Reject(()=>new Cs1237ZForceBinding(machine,portB,sensorB,"z-traced"),"duplicate source consumer rejected");
            Reject(()=>sensorA.TimedSource(1),"future ADC callback rejected");
            Check(bindA.Bound&&bindB.Bound&&sensorA.TimedProviderBound&&sensorB.TimedProviderBound,"typed exclusive cross-machine bindings installed");
            var portC=new Cs1237NativeGpio(machine);var portD=new Cs1237NativeGpio(machine);
            sensorC=new Cs1237FunctionalAdapter(machine,portC,0,idealizedElectricalSemantics:true);
            sensorD=new Cs1237FunctionalAdapter(machine,portD,0,idealizedElectricalSemantics:true);
            new Cs1237ZForceBinding(machine,portC,sensorC,"z-skew");new Cs1237ZForceBinding(machine,portD,sensorD,"z-rollback");
        }
        public void Reset(){}
        private void Check(bool v,string label){checks++;if(!v)throw new Exception(label);}
        private void Reject(Action action,string label){bool failed=false;try{action();}catch(ArgumentException){failed=true;}catch(InvalidOperationException){failed=true;}Check(failed,label);}
        public string VerifyContactConversion()
        {
            Check(sensorA.AdapterErrors==0&&sensorB.AdapterErrors==0,"actual conversion callbacks have no provider errors");
            Check(sensorA.Protocol.ConversionCount==1&&sensorB.Protocol.ConversionCount==1,"one actual 302 ms conversion in both adapters");
            Check(sensorA.Protocol.LastLatchedSignedCode>0,"mechanical contact force latched by actual ADC conversion");
            Check(sensorA.Protocol.LastLatchedSignedCode==sensorB.Protocol.LastLatchedSignedCode,"trace on/off ADC code invariance");
            Check(ZForceSourceDirectory.Resolve("z-traced").History.LastDeadlineNanoseconds==302000000,"exact conversion candidate deadline retained");
            Check((portA.Snapshot(8)&128)==0&&(portB.Snapshot(8)&128)==0,"binding never drives native probe PA7");
            return "Z FORCE CROSS-MACHINE CONTACT TESTS PASS: "+checks+"; ADC_code="+sensorA.Protocol.LastLatchedSignedCode;
        }
        public string VerifyDisabledConversion()
        {
            checks=0;Check(sensorA.AdapterErrors==0&&sensorB.AdapterErrors==0,"disabled force source still valid");
            Check(sensorA.Protocol.ConversionCount==2&&sensorB.Protocol.ConversionCount==2,"second real conversion occurred");
            Check(sensorA.Protocol.LastLatchedSignedCode==0&&sensorB.Protocol.LastLatchedSignedCode==0,"genuine mechanical disable gives force-free ADC baseline");
            Check((portA.Snapshot(8)&128)==0&&(portB.Snapshot(8)&128)==0,"disable path does not drive native probe");
            Reject(()=>new Cs1237ZForceBinding(machine,portA,sensorA,"z-traced"),"nonzero epoch rebinding rejected");
            return "Z FORCE DISABLED CONVERSION TESTS PASS: "+checks;
        }
        public string VerifyTemporalGuardRejections()
        {
            checks=0;long now=checked((long)machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds);
            Check(sensorC.AdapterErrors==0&&sensorD.AdapterErrors==0,"temporal-negative adapters first completed real conversions normally");
            Reject(()=>sensorC.TimedSource(now-1001),"cross-machine producer clock lead over explicit 1 us rejected");
            Check(ZForceSourceDirectory.Resolve("z-skew").History.LastError.Contains("skew"),"cross-machine skew reason retained");
            Check(sensorD.TimedSource(now)==0,"rollback fixture first accepts current candidate");
            Reject(()=>sensorD.TimedSource(now-1),"cross-machine callback deadline rollback rejected");
            Check(ZForceSourceDirectory.Resolve("z-rollback").History.LastError.Contains("backwards"),"callback rollback reason retained");
            return "Z FORCE CROSS-MACHINE TEMPORAL NEGATIVES PASS: "+checks;
        }
        public string VerifyStaleFault()
        {
            checks=0;Check(sensorA.AdapterErrors==1&&sensorB.AdapterErrors==1,"stale actual physical history fails both ADC adapters closed");
            Check(sensorA.Protocol.ConversionCount==2&&sensorB.Protocol.ConversionCount==2,"failed provider does not invent third conversion");
            Check(sensorA.AdapterError.Contains("stale")&&sensorB.AdapterError.Contains("stale"),"staleness reason visible");
            Reject(()=>sensorA.ValidateSensorLevel(),"failed provider cannot return valid electrical sample");
            Check((portA.Snapshot(8)&128)==0&&(portB.Snapshot(8)&128)==0,"provider failure never drives native probe");
            Check(sensorC.AdapterErrors==1&&sensorD.AdapterErrors==1,"skew/rollback failures reach actual ADC deadline fail-stop");
            Check(sensorC.AdapterError.Contains("skew")&&sensorD.AdapterError.Contains("backwards"),"actual ADC fail-stop preserves original temporal reasons");
            Check(sensorC.Protocol.ConversionCount==2&&sensorD.Protocol.ConversionCount==2,"skew/rollback cannot invent third conversions");
            return "Z FORCE STALE FAIL-CLOSED TESTS PASS: "+checks;
        }
        private readonly IMachine machine;private readonly Cs1237NativeGpio portA,portB;
        private readonly Cs1237FunctionalAdapter sensorA,sensorB,sensorC,sensorD;private readonly Cs1237ZForceBinding bindA,bindB;private int checks;
    }
}
