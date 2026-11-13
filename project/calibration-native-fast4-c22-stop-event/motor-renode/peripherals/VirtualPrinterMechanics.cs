// SPDX-License-Identifier: MIT
// Pure virtual board-side components. No real GPIO, motor or heater access.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals;
namespace Antmicro.Renode.Peripherals.AT32
{
    // Minimal linear axis: step/dir/enable -> position and endstops. This is NOT a
    // motor electrical model and does not invent which board pins drive an axis.
    public class VirtualPrinterAxis : IPeripheral, IGPIOReceiver
    {
        public VirtualPrinterAxis(double stepsPerMillimeter = 80, double minimumMillimeters = 0,
            double maximumMillimeters = 250, double initialMillimeters = 10,
            bool enableActiveLow = true, bool invertDirection = false, bool endstopActiveLow = true)
        {
            if(!Finite(stepsPerMillimeter) || stepsPerMillimeter<=0 || !Finite(minimumMillimeters)
                || !Finite(maximumMillimeters) || maximumMillimeters<=minimumMillimeters
                || !Finite(initialMillimeters) || initialMillimeters<minimumMillimeters || initialMillimeters>maximumMillimeters)
                throw new ArgumentException("Invalid virtual axis geometry");
            steps=stepsPerMillimeter; min=minimumMillimeters; max=maximumMillimeters; initial=initialMillimeters;
            activeLow=enableActiveLow; reversed=invertDirection; stopLow=endstopActiveLow;
            PositionMillimeters=initial; Reset();
        }
        // Inputs: 0 STEP (rising), 1 DIR, 2 ENABLE. Outputs have explicitly configurable polarity.
        public void OnGPIO(int number, bool value)
        {
            if(number==1) { direction=value; return; }
            if(number==2) { enableLevel=value; return; }
            if(number!=0) { this.Log(LogLevel.Warning,"Unknown virtual axis input {0}",number); return; }
            if(value && !stepLevel && Enabled)
            {
                TotalStepPulses++;
                if(!Stalled)
                {
                    double requested=PositionMillimeters+((direction^reversed) ? 1 : -1)/steps;
                    bool hit=requested<min || requested>max;
                    if(hit) LimitCollisionCount++;
                    PositionMillimeters=Math.Max(min,Math.Min(max,requested)); UpdateOutputs();
                }
            }
            stepLevel=value;
        }
        // MCU reset drops drive, but does not teleport mechanics or clear a physical fault.
        public void Reset() { stepLevel=direction=false; enableLevel=activeLow; UpdateOutputs(); }
        public void SetPosition(double millimeters)
        {
            if(!Finite(millimeters)||millimeters<min||millimeters>max) throw new ArgumentOutOfRangeException("millimeters");
            PositionMillimeters=millimeters; UpdateOutputs();
        }
        public void RestoreInitialPosition() { SetPosition(initial); TotalStepPulses=LimitCollisionCount=0; }
        public bool Enabled => enableLevel != activeLow;
        public bool Stalled { get; set; }
        public double PositionMillimeters { get; private set; }
        public ulong TotalStepPulses { get; private set; }
        public ulong LimitCollisionCount { get; private set; }
        public GPIO MinimumEndstop { get; } = new GPIO();
        public GPIO MaximumEndstop { get; } = new GPIO();
        public void RefreshOutputs() { UpdateOutputs(); }
        private void UpdateOutputs()
        {
            MinimumEndstop.Set((PositionMillimeters<=min+1e-10)^stopLow);
            MaximumEndstop.Set((PositionMillimeters>=max-1e-10)^stopLow);
        }
        private static bool Finite(double x) => !Double.IsNaN(x)&&!Double.IsInfinity(x);
        private readonly double steps,min,max,initial;
        private readonly bool activeLow,reversed,stopLow;
        private bool stepLevel,direction,enableLevel;
    }

    // Filament, door, probe or user switch, without claiming a board-specific meaning.
    public class VirtualPrinterSwitch : IPeripheral
    {
        public VirtualPrinterSwitch(bool activeLow = true, bool initialAsserted = false)
        { this.activeLow=activeLow; asserted=initialAsserted; RefreshOutput(); }
        public GPIO Output { get; } = new GPIO();
        public bool Asserted { get => asserted; set { asserted=value; RefreshOutput(); } }
        // Physical external state persists across MCU reset.
        public void Reset() { RefreshOutput(); }
        public void RefreshOutput() { Output.Set(asserted^activeLow); }
        private readonly bool activeLow;
        private bool asserted;
    }
}
