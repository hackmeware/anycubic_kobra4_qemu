// SPDX-License-Identifier: MIT
// Generic assumed two-phase PM rotor. No firmware RAM, command or fault-state access.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using Antmicro.Renode.Core;
namespace Antmicro.Renode.Peripherals.AT32
{
    // Independent physical-state kernel, also used directly by equation tests.
    public class GenericStepperRotor
    {
        public GenericStepperRotor(double resistance=2, double inductance=0.003, double inertia=0.00001,
            double fluxLinkage=0.002, int polePairs=50, double damping=0.0001,
            double loadTorque=0, double maximumStepSeconds=0.00002)
        {
            if(!Positive(resistance)||!Positive(inductance)||!Positive(inertia)||!Nonnegative(fluxLinkage)
                ||polePairs<1||polePairs>1000||!Nonnegative(damping)||!Finite(loadTorque)||!Positive(maximumStepSeconds))
                throw new ArgumentException("Invalid generic motor parameters");
            R=resistance;L=inductance;J=inertia;Psi=fluxLinkage;Pairs=polePairs;Damping=damping;
            LoadTorque=loadTorque;MaxStep=maximumStepSeconds;
        }
        public double CurrentA { get; private set; }
        public double CurrentB { get; private set; }
        public double AngleRadians { get; private set; }
        public double VelocityRadiansPerSecond { get; private set; }
        public double ElectromagneticTorque => Torque(CurrentA,CurrentB,AngleRadians);
        public double BackEmfA => -Pairs*Psi*VelocityRadiansPerSecond*Math.Sin(Pairs*AngleRadians);
        public double BackEmfB => Pairs*Psi*VelocityRadiansPerSecond*Math.Cos(Pairs*AngleRadians);
        public double StoredEnergy => 0.5*L*(CurrentA*CurrentA+CurrentB*CurrentB)+0.5*J*VelocityRadiansPerSecond*VelocityRadiansPerSecond+ContactEnergy(AngleRadians);
        public double ContactReactionTorque => ContactTorque(AngleRadians,VelocityRadiansPerSecond);
        public double ConstraintReactionTorque => LockedRotor ? -(ElectromagneticTorque-LoadTorque+ContactReactionTorque) : 0;
        public double LoadTorque { get; set; }
        public bool LockedRotor { get; set; }
        public bool OpenWinding { get; set; }
        public bool ContactEnabled { get; private set; }
        public double DissipatedByIdealOpening { get; private set; }
        public double DissipatedByIdealLock { get; private set; }
        public ulong IntegrationSteps { get; private set; }
        public void ConfigureContact(double minimumAngle,double maximumAngle,double stiffness=10,double contactDamping=0.01)
        {
            if(!Finite(minimumAngle)||!Finite(maximumAngle)||minimumAngle>=maximumAngle||!Positive(stiffness)||!Nonnegative(contactDamping))throw new ArgumentException("Invalid contact model");
            min=minimumAngle;max=maximumAngle;spring=stiffness;dashpot=contactDamping;ContactEnabled=true;
        }
        // Explicit scenario initial conditions. Never called on an MCU reset.
        public void SetInitialState(double currentA,double currentB,double angle,double velocity)
        {
            if(!Finite(currentA)||!Finite(currentB)||!Finite(angle)||!Finite(velocity))throw new ArgumentException("Non-finite initial state");
            CurrentA=currentA;CurrentB=currentB;AngleRadians=angle;VelocityRadiansPerSecond=velocity;
            IntegrationSteps=0;DissipatedByIdealOpening=0;DissipatedByIdealLock=0;
        }
        public void Advance(double voltageA,double voltageB,double seconds)
        {
            if(!Finite(voltageA)||!Finite(voltageB)||!Finite(seconds)||seconds<0||!Finite(LoadTorque))throw new ArgumentException("Invalid integration input");
            if(seconds==0)return;
            if(OpenWinding)
            {
                // Ideal open switch dumps inductive energy into an unmodelled clamp, explicitly recorded.
                DissipatedByIdealOpening+=0.5*L*(CurrentA*CurrentA+CurrentB*CurrentB);CurrentA=CurrentB=0;
            }
            if(LockedRotor)
            {
                // External ideal lock supplies reaction torque. No work at zero angular velocity.
                DissipatedByIdealLock+=0.5*J*VelocityRadiansPerSecond*VelocityRadiansPerSecond;VelocityRadiansPerSecond=0;
                double decay=Math.Exp(-seconds*R/L);
                CurrentA=OpenWinding?0:voltageA/R+(CurrentA-voltageA/R)*decay;
                CurrentB=OpenWinding?0:voltageB/R+(CurrentB-voltageB/R)*decay;
                IntegrationSteps++;return;
            }
            double remaining=seconds;
            while(remaining>0)
            {
                // Bound electrical, rotational and compliant-contact time scales. No target-dependent adaptation.
                double h=Math.Min(remaining,Math.Min(MaxStep,0.05*L/R));
                h=Math.Min(h,0.05/(Pairs*Math.Abs(VelocityRadiansPerSecond)+1));
                if(ContactEnabled)h=Math.Min(h,0.05*Math.Sqrt(J/spring));
                if(h<=0 || !Finite(h))throw new InvalidOperationException("Invalid physical integration step");
                var y=new State(CurrentA,CurrentB,AngleRadians,VelocityRadiansPerSecond);
                var a=Derivative(y,voltageA,voltageB);var b=Derivative(y.Plus(a,h/2),voltageA,voltageB);
                var c=Derivative(y.Plus(b,h/2),voltageA,voltageB);var d=Derivative(y.Plus(c,h),voltageA,voltageB);
                CurrentA+=h*(a.A+2*b.A+2*c.A+d.A)/6;CurrentB+=h*(a.B+2*b.B+2*c.B+d.B)/6;
                AngleRadians+=h*(a.Theta+2*b.Theta+2*c.Theta+d.Theta)/6;
                VelocityRadiansPerSecond+=h*(a.Omega+2*b.Omega+2*c.Omega+d.Omega)/6;
                if(!Finite(CurrentA)||!Finite(CurrentB)||!Finite(AngleRadians)||!Finite(VelocityRadiansPerSecond))throw new InvalidOperationException("Physical state diverged");
                IntegrationSteps++;remaining-=h;
            }
        }
        private State Derivative(State y,double va,double vb)
        {
            double sa=Math.Sin(Pairs*y.Theta),ca=Math.Cos(Pairs*y.Theta),k=Pairs*Psi;
            double ea=-k*y.Omega*sa,eb=k*y.Omega*ca;
            double torque=k*(-y.A*sa+y.B*ca);
            return new State(OpenWinding?0:(va-R*y.A-ea)/L,OpenWinding?0:(vb-R*y.B-eb)/L,
                y.Omega,(torque-Damping*y.Omega-LoadTorque+ContactTorque(y.Theta,y.Omega))/J);
        }
        private double Torque(double a,double b,double theta) => Pairs*Psi*(-a*Math.Sin(Pairs*theta)+b*Math.Cos(Pairs*theta));
        private double ContactTorque(double angle,double speed)
        {
            if(!ContactEnabled)return 0;
            // Unilateral compliant stops: damping resists penetration only, never pulls into a stop.
            if(angle<min)return spring*(min-angle)-dashpot*Math.Min(0,speed);
            if(angle>max)return -spring*(angle-max)-dashpot*Math.Max(0,speed);
            return 0;
        }
        private double ContactEnergy(double angle)
        {double x=!ContactEnabled?0:Math.Max(0,Math.Max(min-angle,angle-max));return 0.5*spring*x*x;}
        private struct State
        {
            public State(double a,double b,double theta,double omega){A=a;B=b;Theta=theta;Omega=omega;}
            public State Plus(State d,double h)=>new State(A+h*d.A,B+h*d.B,Theta+h*d.Theta,Omega+h*d.Omega);
            public double A,B,Theta,Omega;
        }
        private static bool Finite(double x)=>!Double.IsNaN(x)&&!Double.IsInfinity(x);
        private static bool Positive(double x)=>Finite(x)&&x>0;
        private static bool Nonnegative(double x)=>Finite(x)&&x>=0;
        private readonly double R,L,J,Psi,Damping,MaxStep;private readonly int Pairs;
        private double min,max,spring,dashpot;
    }

    public class GenericStepperElectromechanical : IPeripheral, IGPIOReceiver, IDisposable
    {
        public GenericStepperElectromechanical(IMachine machine, AT32Timer tmr2, AT32Timer tmr1,
            AT32Timer tmr3, AT32Timer tmr4, AT32Timer tmr8, AT32ADC adc1, AT32ADC adc2, AT32ADC adc3,
            double supplyVoltage=24,double resistanceOhms=2,double inductanceHenries=0.003,
            double inertiaKilogramMetersSquared=0.00001,double fluxLinkageWebers=0.002,
            int polePairs=50,double dampingNewtonMeterSeconds=0.0001,double loadTorqueNewtonMeters=0,
            double adcCountsPerAmp=500,double adcOffset=2048,double maximumStepSeconds=0.00002,
            int traceEveryTriggers=1000,int maximumTraceSamples=100000)
        {
            if(!Finite(supplyVoltage)||supplyVoltage<0||!Finite(adcCountsPerAmp)||adcCountsPerAmp<=0||!Finite(adcOffset)||adcOffset<0||adcOffset>4095)throw new ArgumentException("Invalid supply/ADC parameters");
            if(traceEveryTriggers<1||maximumTraceSamples<1||maximumTraceSamples>1000000)throw new ArgumentException("Invalid trace limits");
            traceEvery=traceEveryTriggers;traceMaximum=maximumTraceSamples;
            this.machine=machine;timers=new[]{tmr3,tmr1,tmr4};adcs=new[]{adc1,adc2,adc3};
            supply=supplyVoltage;adcGain=adcCountsPerAmp;offset=adcOffset;
            for(int i=0;i<3;i++)rotors[i]=new GenericStepperRotor(resistanceOhms,inductanceHenries,inertiaKilogramMetersSquared,fluxLinkageWebers,polePairs,dampingNewtonMeterSeconds,loadTorqueNewtonMeters,maximumStepSeconds);
            tmr2.TriggerOutput.Connect(tmr1,17);tmr2.TriggerOutput.Connect(tmr3,17);tmr2.TriggerOutput.Connect(tmr4,17);
            tmr1.TriggerOutput.Connect(tmr8,16);tmr8.TriggerOutput.Connect(this,0);
            Reset();
            for(int axis=0;axis<3;axis++){int a=axis;timers[a].ConfigurationChanging+=()=>AdvanceAxisToNow(a);timers[a].ConfigurationChanged+=()=>UpdateDrive(a);}
        }
        // MCU reset preserves physical inertia/current/position. Timer callbacks update drive separately.
        public void Reset(){for(int a=0;a<3;a++){AdvanceAxisToNow(a);UpdateDrive(a);}PublishSamples();}
        public void OnGPIO(int number,bool value)
        {
            if(number!=0||!value)return;
            for(int a=0;a<3;a++)AdvanceAxisToNow(a);
            PublishSamples();TriggerCount++;if(TriggerCount%(ulong)traceEvery==0)CaptureTrace();foreach(var adc in adcs)adc.TriggerPreempt(15);
        }
        public double GetCurrent(int axis,int phase){Check(axis);if(phase<0||phase>1)throw new ArgumentOutOfRangeException();return phase==0?rotors[axis].CurrentA:rotors[axis].CurrentB;}
        public double GetAngleRadians(int axis){Check(axis);return rotors[axis].AngleRadians;}
        public double GetVelocityRadiansPerSecond(int axis){Check(axis);return rotors[axis].VelocityRadiansPerSecond;}
        public double GetTorqueNewtonMeters(int axis){Check(axis);return rotors[axis].ElectromagneticTorque;}
        public double GetStoredEnergyJoules(int axis){Check(axis);return rotors[axis].StoredEnergy;}
        // Relative mechanical projection only; no homing/absolute-position/firmware-state assignment.
        public double GetRelativeTravelMillimeters(int axis){Check(axis);return rotors[axis].AngleRadians*(axis==2?8:39)/(2*Math.PI);}
        public void SetRotorLocked(int axis,bool locked){Check(axis);AdvanceAxisToNow(axis);rotors[axis].LockedRotor=locked;}
        public void SetOpenWinding(int axis,bool open){Check(axis);AdvanceAxisToNow(axis);rotors[axis].OpenWinding=open;}
        // Explicit external bridge gating. Preserve accumulated physical state on enable edges.
        public void SetBridgeEnabled(int axis,bool enabled){Check(axis);AdvanceAxisToNow(axis);bridgeEnabled[axis]=enabled;UpdateDrive(axis);}
        public bool GetBridgeEnabled(int axis){Check(axis);return bridgeEnabled[axis];}
        public void SetSupplyVoltage(double voltage){if(!Finite(voltage)||voltage<0)throw new ArgumentException("Invalid supply");for(int a=0;a<3;a++)AdvanceAxisToNow(a);supply=voltage;for(int a=0;a<3;a++)UpdateDrive(a);}
        public void SetLoadTorque(int axis,double torque){Check(axis);if(!Finite(torque))throw new ArgumentException();AdvanceAxisToNow(axis);rotors[axis].LoadTorque=torque;}
        public void ConfigureRelativeContact(int axis,double minimumMillimeters,double maximumMillimeters,double stiffness=10,double damping=0.01)
        {Check(axis);AdvanceAxisToNow(axis);double k=2*Math.PI/(axis==2?8:39);rotors[axis].ConfigureContact(minimumMillimeters*k,maximumMillimeters*k,stiffness,damping);}
        public ulong TriggerCount{get;private set;}public ulong ClippedSamples{get;private set;}
        public bool TraceCapacityReached{get;private set;}
        public int TraceSamples=>trace.Count;
        public void CaptureTrace()
        {
            if(trace.Count>=traceMaximum){TraceCapacityReached=true;return;}
            string row=Now.ToString("R",CultureInfo.InvariantCulture);
            for(int a=0;a<3;a++)row+=","+String.Join(",",Array.ConvertAll(new[]{rotors[a].AngleRadians,rotors[a].VelocityRadiansPerSecond,rotors[a].CurrentA,rotors[a].CurrentB,rotors[a].ElectromagneticTorque,rotors[a].StoredEnergy,GetRelativeTravelMillimeters(a),rotors[a].ContactReactionTorque},v=>v.ToString("R",CultureInfo.InvariantCulture)));
            trace.Add(row);
        }
        public void WriteCsv(string path)
        {
            string header="virtual_time_s";foreach(var axis in new[]{"x","y","z"})header+=","+axis+"_angle_rad,"+axis+"_velocity_rad_s,"+axis+"_ia_amp,"+axis+"_ib_amp,"+axis+"_torque_nm,"+axis+"_stored_energy_j,"+axis+"_relative_mm,"+axis+"_contact_torque_nm";
            File.WriteAllText(path,"# GENERIC ASSUMED PHYSICAL MODEL: rotor state, not queued targets or calibrated printer position\n"+header+"\n"+String.Join("\n",trace)+"\n");
        }
        // Optional observation only. No observer path advances time or physical state.
        public double GetContactTorqueNewtonMeters(int axis){Check(axis);return rotors[axis].ContactReactionTorque;}
        public double GetLastIntegrationTimeSeconds(int axis){Check(axis);return last[axis];}
        public ulong IntegrationCalls{get;private set;}
        public ulong ContactRowsWritten{get;private set;}
        public ulong ContactDroppedRows{get;private set;}
        public string ContactLastError{get;private set;} = "";
        public bool ContactTraceEnabled => contactWriter!=null;
        public void StartContactTrace(string path,int maximumRows=100000,bool flushEachRow=true)
        {
            if(contactWriter!=null)throw new InvalidOperationException("Contact trace already active");
            if(maximumRows<1||maximumRows>1000000)throw new ArgumentOutOfRangeException("maximumRows");
            // CreateNew prevents accidental replacement of previous evidence.
            contactWriter=new StreamWriter(new FileStream(path,FileMode.CreateNew,FileAccess.Write,FileShare.Read));
            contactMaximum=maximumRows;contactFlush=flushEachRow;ContactRowsWritten=0;ContactDroppedRows=0;ContactLastError="";
            try
            {
                contactWriter.WriteLine("observation_time_s,previous_integration_time_s,state_time_s,axis,kind,contact_nonzero,angle_rad,velocity_rad_s,relative_mm,contact_torque_nm");
                for(int a=0;a<3;a++){contactLevel[a]=rotors[a].ContactReactionTorque!=0;RecordContact(a,"initial",Now,last[a]);}
                contactWriter.Flush();
            }
            catch(Exception e){ContactTraceError(e);}
        }
        public void StopContactTrace()
        {
            var writer=contactWriter;contactWriter=null;
            if(writer!=null)try{writer.Dispose();}catch(Exception e){ContactLastError=e.Message;}
        }
        public void Dispose(){StopContactTrace();}
        private void ContactTraceError(Exception e){ContactLastError=e.Message;StopContactTrace();}
        private void RecordContact(int a,string kind,double now,double previous)
        {
            if(contactWriter==null)return;
            if(ContactRowsWritten>=(ulong)contactMaximum){ContactDroppedRows++;return;}
            try
            {
                var c=CultureInfo.InvariantCulture;
                contactWriter.WriteLine(String.Join(",",new[]{now.ToString("R",c),previous.ToString("R",c),last[a].ToString("R",c),a.ToString(c),kind,contactLevel[a]?"1":"0",rotors[a].AngleRadians.ToString("R",c),rotors[a].VelocityRadiansPerSecond.ToString("R",c),GetRelativeTravelMillimeters(a).ToString("R",c),rotors[a].ContactReactionTorque.ToString("R",c)}));
                if(contactFlush)contactWriter.Flush();ContactRowsWritten++;
            }
            catch(Exception e){ContactTraceError(e);}
        }
        private void AdvanceAxisToNow(int a)
        {
            double now=Now,previous=last[a],dt=Math.Max(0,now-previous);last[a]=now;
            if(dt>0)
            {
                rotors[a].Advance(drive[2*a],drive[2*a+1],dt);IntegrationCalls++;
                if(contactWriter!=null)
                {
                    bool level=rotors[a].ContactReactionTorque!=0;
                    if(level!=contactLevel[a]){contactLevel[a]=level;RecordContact(a,"transition",now,previous);}
                }
            }
        }
        private StreamWriter contactWriter;private int contactMaximum;private bool contactFlush;
        private readonly bool[] contactLevel=new bool[3];
        private void UpdateDrive(int a){for(int p=0;p<2;p++)drive[2*a+p]=GetPhaseVoltage(a,p);}
        private double GetPhaseVoltage(int a,int p)
        {var t=timers[a];if(!bridgeEnabled[a]||!t.Enabled||(t.ReadDoubleWord(0)&1)==0||(a==1&&(t.ReadDoubleWord(0x44)&0x8000)==0))return 0;return supply*(HighFraction(t,2*p)-HighFraction(t,2*p+1));}
        private static double HighFraction(AT32Timer t,int c)
        {
            uint enables=t.ReadDoubleWord(0x20);if((enables&(1u<<(4*c)))==0)return 0;
            uint config=t.ReadDoubleWord(c<2?0x18:0x1c)>>(8*(c%2));if((config&3)!=0)return 0;
            uint mode=(config>>4)&7;double high;
            if(mode==4)high=0;else if(mode==5)high=1;
            else if(mode==6||mode==7){uint period=t.ReadDoubleWord(0x2c);if(period==0)return 0;high=Math.Min(1.0,(double)t.ReadDoubleWord(0x34+4*c)/period);if(mode==7)high=1-high;}
            else return 0;
            return (enables&(2u<<(4*c)))!=0?1-high:high;
        }
        private void PublishSamples()
        {
            for(int a=0;a<3;a++)for(int p=0;p<2;p++)
            {
                int sign=(timers[a].ReadDoubleWord(0x20)&(2u<<(p*8)))==0?1:-1;
                double sample=offset+sign*GetCurrent(a,p)*adcGain;if(sample<0||sample>4095)ClippedSamples++;
                adcs[a].SetChannelValue(channels[2*a+p],(ushort)Math.Max(0,Math.Min(4095,Math.Round(sample))));
            }
        }
        private double Now=>machine.ElapsedVirtualTime.TimeElapsed.TotalSeconds;
        private static void Check(int a){if(a<0||a>2)throw new ArgumentOutOfRangeException();}
        private static bool Finite(double x)=>!Double.IsNaN(x)&&!Double.IsInfinity(x);
        private readonly IMachine machine;private readonly AT32Timer[] timers;private readonly AT32ADC[] adcs;
        private readonly GenericStepperRotor[] rotors=new GenericStepperRotor[3];private readonly double[] last=new double[3],drive=new double[6];
        private readonly bool[] bridgeEnabled={true,true,true};
        private readonly List<string> trace=new List<string>();private readonly int traceEvery,traceMaximum;
        private readonly int[] channels={0,4,5,6,12,10};private readonly double adcGain,offset;private double supply;
    }
}
