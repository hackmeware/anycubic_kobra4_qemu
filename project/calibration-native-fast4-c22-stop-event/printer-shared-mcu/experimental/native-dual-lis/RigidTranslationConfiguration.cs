// SPDX-License-Identifier: MIT
// A read-only public-plant snapshot is published only at a common master sync
// boundary. Derivatives use adjacent DISTINCT OBSERVED public endpoints, not
// consecutive acquisitions. No source mutation, interpolation, retimestamping or backfill.
using System;
using System.Linq;
using Antmicro.Renode.Core;
using GenericStepperElectromechanical = Antmicro.Renode.Peripherals.PrinterMotor.GenericStepperElectromechanical;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.SensorCrossBoard
{
    // All calibration/frame/unit parameters are REQUIRED. No printer mapping defaults.
    // a_world = WorldMetersPerRadian * angularAcceleration; fixed translational Jacobian.
    // f_sensor[g] = SensorFromWorld * (a_world - gravity_world) / g0.
    public sealed class RigidTranslationConfiguration
    {
        public RigidTranslationConfiguration(int[] plantAxes, double[,] worldMetersPerRadian,
            double[,] sensorFromWorld, double[] gravityWorldMetersPerSecondSquared,
            double standardGravityMetersPerSecondSquared, ulong maximumSourceAgeNanoseconds,
            ulong maximumDerivativeIntervalNanoseconds)
        {
            if(plantAxes==null || plantAxes.Length<1 || plantAxes.Length>3) throw new ArgumentException("Explicit selection of 1..3 plant axes is required.");
            Axes=(int[])plantAxes.Clone();
            for(int i=0;i<Axes.Length;i++)
            {
                if(Axes[i]<0 || Axes[i]>2) throw new ArgumentException("Plant axes must be 0..2.");
                for(int j=0;j<i;j++) if(Axes[i]==Axes[j]) throw new ArgumentException("Duplicate plant axis.");
            }
            if(worldMetersPerRadian==null || worldMetersPerRadian.GetLength(0)!=3 || worldMetersPerRadian.GetLength(1)!=Axes.Length)
                throw new ArgumentException("Supply a 3 by selected-axis-count Jacobian in world meters/radian.");
            Jacobian=(double[,])worldMetersPerRadian.Clone();
            for(int c=0;c<Axes.Length;c++)
            {
                bool nonzero=false;
                for(int r=0;r<3;r++) { RequireFinite(Jacobian[r,c]); nonzero|=Jacobian[r,c]!=0; }
                if(!nonzero) throw new ArgumentException("Every selected axis needs an explicit nonzero translation mapping.");
            }
            if(sensorFromWorld==null || sensorFromWorld.GetLength(0)!=3 || sensorFromWorld.GetLength(1)!=3)
                throw new ArgumentException("Supply a 3 by 3 world-to-sensor proper rotation.");
            Rotation=(double[,])sensorFromWorld.Clone();
            foreach(double x in Rotation) RequireFinite(x);
            for(int i=0;i<3;i++) for(int j=0;j<3;j++)
            {
                double dot=0; for(int k=0;k<3;k++) dot+=Rotation[i,k]*Rotation[j,k];
                if(Math.Abs(dot-(i==j?1:0))>1e-10) throw new ArgumentException("Sensor orientation must be orthonormal.");
            }
            double det=Rotation[0,0]*(Rotation[1,1]*Rotation[2,2]-Rotation[1,2]*Rotation[2,1])
                -Rotation[0,1]*(Rotation[1,0]*Rotation[2,2]-Rotation[1,2]*Rotation[2,0])
                +Rotation[0,2]*(Rotation[1,0]*Rotation[2,1]-Rotation[1,1]*Rotation[2,0]);
            if(Math.Abs(det-1)>1e-10) throw new ArgumentException("Sensor orientation must preserve handedness (determinant +1).");
            if(gravityWorldMetersPerSecondSquared==null || gravityWorldMetersPerSecondSquared.Length!=3)
                throw new ArgumentException("Supply all three world-frame gravitational acceleration components in m/s^2.");
            Gravity=(double[])gravityWorldMetersPerSecondSquared.Clone(); foreach(double x in Gravity) RequireFinite(x);
            RequireFinite(standardGravityMetersPerSecondSquared);
            if(standardGravityMetersPerSecondSquared<=0) throw new ArgumentException("g0 must be positive m/s^2 per g.");
            // A 100 Hz endpoint stream cannot qualify as this 1600 Hz input.
            if(maximumSourceAgeNanoseconds>=625000 || maximumDerivativeIntervalNanoseconds==0 || maximumDerivativeIntervalNanoseconds>625000)
                throw new ArgumentException("Source age must be <625000 ns; derivative interval must be 1..625000 ns.");
            G0=standardGravityMetersPerSecondSquared; MaximumAge=maximumSourceAgeNanoseconds; MaximumInterval=maximumDerivativeIntervalNanoseconds;
        }
        internal static void RequireFinite(double x)
        { if(Double.IsNaN(x)||Double.IsInfinity(x)) throw new ArgumentException("Finite physical parameters/state required."); }
        internal readonly int[] Axes;
        internal readonly double[,] Jacobian,Rotation;
        internal readonly double[] Gravity;
        internal readonly double G0;
        internal readonly ulong MaximumAge,MaximumInterval;
    }

}
