// SPDX-License-Identifier: MIT
// EXPERIMENTAL, opt-in synthetic fixture. Not recovered physical geometry/calibration.
// Requires the separately reviewed disable-contact.patch. No firmware state, GPIO or thresholds.
using System;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.MotorExperimental
{
    public class VirtualZBedContactFixture : IPeripheral
    {
        public VirtualZBedContactFixture(GenericStepperElectromechanical plant,
            double bedRelativeMillimeters=-10, double oppositeStopRelativeMillimeters=252,
            bool bedIsMinimum=true, double stiffnessNewtonsPerMillimeter=20,
            double dampingNewtonSecondsPerMillimeter=0.05,
            int baselineCounts=0, double countsPerNewton=10000, int signalPolarity=1)
        {
            if(plant==null)throw new ArgumentNullException("plant");
            if(!Finite(bedRelativeMillimeters)||!Finite(oppositeStopRelativeMillimeters)
                ||Math.Abs(bedRelativeMillimeters)>1000||Math.Abs(oppositeStopRelativeMillimeters)>1000
                ||(bedIsMinimum ? bedRelativeMillimeters>=oppositeStopRelativeMillimeters : bedRelativeMillimeters<=oppositeStopRelativeMillimeters))
                throw new ArgumentException("Invalid synthetic fixture geometry, bounded to +/-1000 mm");
            if(!Finite(stiffnessNewtonsPerMillimeter)||stiffnessNewtonsPerMillimeter<=0||stiffnessNewtonsPerMillimeter>10000
                ||!Finite(dampingNewtonSecondsPerMillimeter)||dampingNewtonSecondsPerMillimeter<0||dampingNewtonSecondsPerMillimeter>100
                ||baselineCounts<MinimumAdcCode||baselineCounts>MaximumAdcCode
                ||!Finite(countsPerNewton)||countsPerNewton<=0||countsPerNewton>1000000000
                ||(signalPolarity!=1&&signalPolarity!=-1))throw new ArgumentException("Invalid synthetic force calibration");
            this.plant=plant;BedRelativeMillimeters=bedRelativeMillimeters;
            OppositeStopRelativeMillimeters=oppositeStopRelativeMillimeters;BedIsMinimum=bedIsMinimum;
            StiffnessNewtonsPerMillimeter=stiffnessNewtonsPerMillimeter;
            DampingNewtonSecondsPerMillimeter=dampingNewtonSecondsPerMillimeter;
            BaselineCounts=baselineCounts;CountsPerNewton=countsPerNewton;SignalPolarity=signalPolarity;
        }
        // MCU reset never moves the fixture, re-enables it or changes physical state.
        public void Reset() { }
        public bool Enabled { get; private set; }
        public double BedRelativeMillimeters { get; private set; }
        public double OppositeStopRelativeMillimeters { get; private set; }
        public bool BedIsMinimum { get; private set; }
        public double StiffnessNewtonsPerMillimeter { get; private set; }
        public double DampingNewtonSecondsPerMillimeter { get; private set; }
        public int BaselineCounts { get; private set; }
        public double CountsPerNewton { get; private set; }
        public int SignalPolarity { get; private set; }
        public double AngularStiffnessNewtonMetersPerRadian { get { return LinearToAngular(StiffnessNewtonsPerMillimeter); } }
        public double AngularDampingNewtonMeterSecondsPerRadian { get { return LinearToAngular(DampingNewtonSecondsPerMillimeter); } }
        public double StateTimeSeconds { get { return plant.GetLastIntegrationTimeSeconds(2); } }
        public double RelativeTravelMillimeters { get { return plant.GetRelativeTravelMillimeters(2); } }
        public double ContactTorqueNewtonMeters { get { return plant.GetContactTorqueNewtonMeters(2); } }
        public void SetEnabled(bool enabled)
        {
            if(enabled==Enabled)return;
            if(enabled)
            {
                // Enabling a penetrating fixture would add spring energy discontinuously.
                double z=RelativeTravelMillimeters;
                if(!Finite(z)||z<MinimumStop||z>MaximumStop)throw new InvalidOperationException("Enable only while between the two synthetic stops");
                plant.ConfigureRelativeContact(2,MinimumStop,MaximumStop,
                    AngularStiffnessNewtonMetersPerRadian,AngularDampingNewtonMeterSecondsPerRadian);
                // Configure integrates old dynamics to now; reject a crossing since the first read.
                z=RelativeTravelMillimeters;
                if(!Finite(z)||z<MinimumStop||z>MaximumStop)
                {
                    plant.DisableRelativeContact(2);
                    throw new InvalidOperationException("Rotor crossed a stop before fixture installation");
                }
            }
            else plant.DisableRelativeContact(2);
            Enabled=enabled;
        }
        public double ReadForceNewtons()
        {
            // Use the actual mechanical reaction, not a recomputed penetration law.
            // At the opposite travel stop the reaction has the wrong sign and is NOT nozzle load.
            double force=BedReactionToForce(ContactTorqueNewtonMeters,BedIsMinimum);
            if(!Enabled)
            {
                if(ContactTorqueNewtonMeters!=0)throw new InvalidOperationException("Another owner configured Z contact while fixture disabled");
                return 0;
            }
            return force;
        }
        public int ReadSyntheticAdcSample()
        {
            bool overload;
            return EncodeForce(ReadForceNewtons(),BaselineCounts,CountsPerNewton,SignalPolarity,out overload);
        }
        public bool AdcWouldSaturate
        {
            get
            {
                bool overload;EncodeForce(ReadForceNewtons(),BaselineCounts,CountsPerNewton,SignalPolarity,out overload);
                return overload;
            }
        }
        public static int EncodeForce(double forceNewtons,int baselineCounts,double countsPerNewton,int polarity,out bool overload)
        {
            if(!Finite(forceNewtons)||forceNewtons<0||baselineCounts<MinimumAdcCode||baselineCounts>MaximumAdcCode
                ||!Finite(countsPerNewton)||countsPerNewton<=0||countsPerNewton>1000000000||(polarity!=1&&polarity!=-1))
                throw new ArgumentException("Invalid synthetic ADC force or calibration");
            double unrounded=baselineCounts+polarity*countsPerNewton*forceNewtons;
            if(!Finite(unrounded))throw new InvalidOperationException("Non-finite synthetic ADC input");
            overload=unrounded<MinimumAdcCode||unrounded>MaximumAdcCode;
            // ADC full-scale saturation, not a contact-force cap or firmware threshold override.
            double rounded=Math.Round(unrounded,MidpointRounding.AwayFromZero);
            return (int)Math.Max(MinimumAdcCode,Math.Min(MaximumAdcCode,rounded));
        }
        public static double BedReactionToForce(double contactTorqueNewtonMeters,bool bedIsMinimum)
        {
            if(!Finite(contactTorqueNewtonMeters))throw new ArgumentException("Non-finite contact reaction");
            double force=Math.Max(0,(bedIsMinimum?1:-1)*contactTorqueNewtonMeters)/MetersPerRadian;
            if(!Finite(force))throw new InvalidOperationException("Force conversion overflow");
            return force;
        }
        public static double LinearToAngular(double newtonsPerMillimeter)
        {
            if(!Finite(newtonsPerMillimeter)||newtonsPerMillimeter<0)throw new ArgumentException("Invalid linear coefficient");
            return newtonsPerMillimeter*MillimetersPerRadian*MillimetersPerRadian/1000.0;
        }
        public const double LeadMillimetersPerRevolution=8;
        public const int MinimumAdcCode=-8388608,MaximumAdcCode=8388607;
        public static readonly double MillimetersPerRadian=LeadMillimetersPerRevolution/(2*Math.PI);
        public static readonly double MetersPerRadian=MillimetersPerRadian/1000;
        private double MinimumStop { get { return Math.Min(BedRelativeMillimeters,OppositeStopRelativeMillimeters); } }
        private double MaximumStop { get { return Math.Max(BedRelativeMillimeters,OppositeStopRelativeMillimeters); } }
        private static bool Finite(double x){return !Double.IsNaN(x)&&!Double.IsInfinity(x);}
        private readonly GenericStepperElectromechanical plant;
    }
}
