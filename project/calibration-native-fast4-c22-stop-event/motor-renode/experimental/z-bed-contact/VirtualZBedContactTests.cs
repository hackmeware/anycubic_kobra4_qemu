// SPDX-License-Identifier: MIT
// CPU-free tests. All initial states, currents and drive voltages are laboratory stimuli.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.MotorExperimental
{
    public class VirtualZBedContactTests : IDoubleWordPeripheral, IKnownSize
    {
        public VirtualZBedContactTests(IMachine machine)
        {
            this.machine=machine;
            var t2=new AT32Timer(machine);var t1=new AT32Timer(machine);
            var t3=new AT32Timer(machine);zTimer=new AT32Timer(machine);var t8=new AT32Timer(machine);
            plant=new GenericStepperElectromechanical(machine,t2,t1,t3,zTimer,t8,new AT32ADC(),new AT32ADC(),new AT32ADC());
            fixture=new VirtualZBedContactFixture(plant,bedRelativeMillimeters:-0.01,oppositeStopRelativeMillimeters:1);
        }
        public long Size { get { return 4; } }
        public void Reset() { }
        public uint ReadDoubleWord(long offset) { return 0; }
        public void WriteDoubleWord(long offset,uint value) { }
        private void Check(bool ok,string label){checks++;if(!ok)throw new Exception(label);}
        private void Near(double a,double b,double eps,string label){Check(Math.Abs(a-b)<=eps,label+": "+a+" vs "+b);}
        private void Throws(Action f,string label){bool threw=false;try{f();}catch(ArgumentException){threw=true;}Check(threw,label);}
        private double Force(GenericStepperRotor rotor,bool minimum=true){return VirtualZBedContactFixture.BedReactionToForce(rotor.ContactReactionTorque,minimum);}
        public string RunEquations()
        {
            checks=0;double l=VirtualZBedContactFixture.MillimetersPerRadian;
            double k=VirtualZBedContactFixture.LinearToAngular(20),d=VirtualZBedContactFixture.LinearToAngular(0.05);
            var r=new GenericStepperRotor(fluxLinkage:0,damping:0);
            Check(!r.ContactEnabled,"kernel initially contact-disabled");
            r.SetInitialState(0,0,-100,-5);Near(Force(r),0,0,"disabled kernel has no reaction even beyond proposed bed");
            r.ConfigureContact(-10/l,252/l,k,d);
            r.SetInitialState(0,0,0,-50/l);Near(Force(r),0,0,"no force before contact despite inward speed");
            r.SetInitialState(0,0,-10/l,-50/l);Near(Force(r),0,0,"no precontact damping exactly on boundary");
            r.SetInitialState(0,0,-10.05/l,0);Near(Force(r),1,1e-12,"20 N/mm times 0.05 mm gives 1 N");
            Near(Force(r)*VirtualZBedContactFixture.MetersPerRadian,r.ContactReactionTorque,1e-15,"force and torque consistency");
            Near(r.StoredEnergy,0.5*20*0.05*0.05/1000,1e-15,"spring energy conversion in joules");
            r.SetInitialState(0,0,-10.05/l,-2/l);Near(Force(r),1.1,1e-12,"inward damping 0.05 N s/mm times 2 mm/s adds 0.1 N");
            double velocityMeters=r.VelocityRadiansPerSecond*VirtualZBedContactFixture.MetersPerRadian;
            Near(Force(r)*velocityMeters,r.ContactReactionTorque*r.VelocityRadiansPerSecond,1e-15,"ideal lead preserves mechanical power");
            r.SetInitialState(0,0,-10.05/l,2/l);Near(Force(r),1,1e-12,"separation velocity cannot pull into bed");
            r.SetInitialState(0,0,-9.99/l,2/l);Near(Force(r),0,0,"complete separation releases force");
            r.SetInitialState(0,0,252.05/l,0);Near(Force(r),0,0,"opposite travel stop is not bed load");
            Near(Force(r,false),1,1e-10,"optional upper-side bed direction");
            var free=new GenericStepperRotor(fluxLinkage:0,damping:0);
            free.SetInitialState(0,0,-10.05/l,0);r.SetInitialState(0,0,-10.05/l,0);
            double initial=r.StoredEnergy;r.Advance(0,0,0.001);free.Advance(0,0,0.001);
            Check(r.VelocityRadiansPerSecond>free.VelocityRadiansPerSecond,"actual contact reaction accelerates rotor away from bed");
            Check(r.AngleRadians>free.AngleRadians,"actual contact changes integrated position");
            Check(r.StoredEnergy<=initial+1e-12,"spring/contact dynamics are passive");
            r.SetInitialState(0.2,-0.3,-10.05/l,-2/l);
            double angle=r.AngleRadians,speed=r.VelocityRadiansPerSecond,ia=r.CurrentA,ib=r.CurrentB;
            r.DisableContact();Check(!r.ContactEnabled,"genuine contact disable flag");Near(Force(r),0,0,"disable removes actual kernel reaction");
            Near(r.AngleRadians,angle,0,"disable retains angle");Near(r.VelocityRadiansPerSecond,speed,0,"disable retains velocity");
            Near(r.CurrentA,ia,0,"disable retains current A");Near(r.CurrentB,ib,0,"disable retains current B");
            r.DisableContact();Near(Force(r),0,0,"disable is idempotent");
            Throws(()=>VirtualZBedContactFixture.BedReactionToForce(double.NaN,true),"nonfinite torque rejected");
            Throws(()=>new VirtualZBedContactFixture(plant,stiffnessNewtonsPerMillimeter:0),"zero stiffness rejected");
            Throws(()=>new VirtualZBedContactFixture(plant,dampingNewtonSecondsPerMillimeter:-1),"negative damping rejected");
            Throws(()=>new VirtualZBedContactFixture(plant,bedRelativeMillimeters:1001),"out-of-envelope geometry rejected");
            Throws(()=>new VirtualZBedContactFixture(plant,countsPerNewton:double.PositiveInfinity),"infinite ADC gain rejected");
            Throws(()=>new VirtualZBedContactFixture(plant,signalPolarity:0),"invalid ADC polarity rejected");
            Check(!fixture.Enabled,"wrapper is disabled on construction");Near(fixture.ReadForceNewtons(),0,0,"disabled wrapper no load");
            Check(fixture.ReadSyntheticAdcSample()==0,"zero-load synthetic baseline");
            Check(!fixture.AdcWouldSaturate,"zero-load no saturation");
            fixture.Reset();Check(!fixture.Enabled,"MCU reset does not arm fixture");
            fixture.SetEnabled(true);Check(fixture.Enabled,"explicit enable required");
            Near(fixture.ReadForceNewtons(),0,0,"enabled but separated fixture no load");
            fixture.Reset();Check(fixture.Enabled,"MCU reset retains explicit fixture placement");
            fixture.SetEnabled(false);Near(plant.GetContactTorqueNewtonMeters(2),0,0,"wrapper disable reaches core");
            Check(!fixture.Enabled,"wrapper disabled after explicit removal");
            return "VIRTUAL Z CONTACT EQUATION TESTS PASS: "+checks;
        }
        public string StartContactDrive()
        {
            checks=0;fixture.SetEnabled(true);
            zTimer.WriteDoubleWord(0x2c,1000);zTimer.WriteDoubleWord(0x18,0x4040);zTimer.WriteDoubleWord(0x1c,0x4040);
            zTimer.WriteDoubleWord(0x20,0x3111);zTimer.WriteDoubleWord(0,1);
            return "VIRTUAL Z LABORATORY DRIVE STARTED";
        }
        public string CheckContact()
        {
            // Synchronize through a real control mutation, not through an observer call.
            plant.SetSupplyVoltage(24);
            Check(fixture.RelativeTravelMillimeters<fixture.BedRelativeMillimeters,"laboratory PWM drove rotor into synthetic bed");
            double torque=plant.GetContactTorqueNewtonMeters(2);Check(torque>0,"plant itself bears positive bed reaction");
            Near(fixture.ReadForceNewtons(),torque/VirtualZBedContactFixture.MetersPerRadian,1e-12,"wrapper reads actual reaction torque");
            Check(fixture.ReadSyntheticAdcSample()>0,"force produces signed synthetic ADC sample");
            ulong calls=plant.IntegrationCalls;double time=fixture.StateTimeSeconds,angle=plant.GetAngleRadians(2);
            for(int i=0;i<100;i++){fixture.ReadForceNewtons();fixture.ReadSyntheticAdcSample();}
            Check(calls==plant.IntegrationCalls,"sensor reads do not advance integration");
            Near(time,fixture.StateTimeSeconds,0,"sensor reads preserve integration timestamp");
            Near(angle,plant.GetAngleRadians(2),0,"sensor reads preserve physical angle");
            bool overloaded;
            Check(VirtualZBedContactFixture.EncodeForce(1000,0,10000,1,out overloaded)==8388607 && overloaded,"positive ADC full scale and overload observable");
            Check(VirtualZBedContactFixture.EncodeForce(1000,0,10000,-1,out overloaded)==-8388608 && overloaded,"negative ADC full scale and overload observable");
            Check(VirtualZBedContactFixture.EncodeForce(1,123,10000,-1,out overloaded)==-9877 && !overloaded,"baseline and negative polarity explicit");
            Check(VirtualZBedContactFixture.EncodeForce(0.00005,0,10000,1,out overloaded)==1,"half-count rounds away from zero");
            return "ACTUAL Z LAB STATE: relative_mm="+fixture.RelativeTravelMillimeters.ToString("R")+", contact_torque_nm="+torque.ToString("R")+", force_N="+fixture.ReadForceNewtons().ToString("R")+", sample="+fixture.ReadSyntheticAdcSample()+"\nVIRTUAL Z CONTACT OBSERVER TESTS PASS: "+checks;
        }
        public string StartDisableTiming()
        {
            checks=0;beforeDisable=plant.GetLastIntegrationTimeSeconds(2);
            expected=new GenericStepperRotor();
            expected.ConfigureContact(-0.01/VirtualZBedContactFixture.MillimetersPerRadian,1/VirtualZBedContactFixture.MillimetersPerRadian,
                fixture.AngularStiffnessNewtonMetersPerRadian,fixture.AngularDampingNewtonMeterSecondsPerRadian);
            expected.SetInitialState(plant.GetCurrent(2,0),plant.GetCurrent(2,1),plant.GetAngleRadians(2),plant.GetVelocityRadiansPerSecond(2));
            Check(expected.ContactReactionTorque>0,"disable test begins under actual contact load");
            return "VIRTUAL Z DISABLE TIMING STARTED";
        }
        public string CheckDisableTiming()
        {
            Check(machine.ElapsedVirtualTime.TimeElapsed.TotalSeconds>beforeDisable,"virtual time progressed before disable");
            expected.Advance(0,-24,machine.ElapsedVirtualTime.TimeElapsed.TotalSeconds-beforeDisable);
            fixture.SetEnabled(false);
            Near(plant.GetAngleRadians(2),expected.AngleRadians,1e-12,"old contact contributes through disable timestamp: angle");
            Near(plant.GetVelocityRadiansPerSecond(2),expected.VelocityRadiansPerSecond,1e-12,"old contact contributes through disable timestamp: speed");
            Near(plant.GetCurrent(2,0),expected.CurrentA,1e-12,"old contact contributes through disable timestamp: current A");
            Near(plant.GetCurrent(2,1),expected.CurrentB,1e-12,"old contact contributes through disable timestamp: current B");
            Near(plant.GetLastIntegrationTimeSeconds(2),machine.ElapsedVirtualTime.TimeElapsed.TotalSeconds,1e-12,"disable advances old contact to now");
            Near(plant.GetContactTorqueNewtonMeters(2),0,0,"disable removes mechanics rather than hiding telemetry");
            Near(fixture.ReadForceNewtons(),0,0,"disabled observed force zero");
            Check(fixture.ReadSyntheticAdcSample()==fixture.BaselineCounts,"disabled ADC returns baseline");
            double angle=plant.GetAngleRadians(2),speed=plant.GetVelocityRadiansPerSecond(2),ia=plant.GetCurrent(2,0),ib=plant.GetCurrent(2,1);
            fixture.Reset();Near(plant.GetAngleRadians(2),angle,0,"reset retains angle");Near(plant.GetVelocityRadiansPerSecond(2),speed,0,"reset retains velocity");
            Near(plant.GetCurrent(2,0),ia,0,"reset retains current A");Near(plant.GetCurrent(2,1),ib,0,"reset retains current B");
            bool rejected=false;try{fixture.SetEnabled(true);}catch(InvalidOperationException){rejected=true;}
            Check(rejected,"cannot reinsert fixture into already penetrating rotor");
            return "VIRTUAL Z DISABLE TIMING TESTS PASS: "+checks;
        }
        private readonly IMachine machine;private readonly GenericStepperElectromechanical plant;private readonly AT32Timer zTimer;
        private VirtualZBedContactFixture fixture;private int checks;private double beforeDisable;private GenericStepperRotor expected;
    }
}
