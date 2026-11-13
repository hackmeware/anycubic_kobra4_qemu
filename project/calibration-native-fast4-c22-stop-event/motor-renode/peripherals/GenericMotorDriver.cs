// SPDX-License-Identifier: MIT
// Opt-in generic enable/undervoltage/fault wiring, not an identified driver IC.
using System;
using Antmicro.Renode.Core;
namespace Antmicro.Renode.Peripherals.AT32
{
    public class GenericMotorDriver : IPeripheral, IGPIOReceiver
    {
        public GenericMotorDriver(GenericStepperElectromechanical plant, AT32GPIO gpioA,
            AT32GPIO gpioB, AT32GPIO gpioC, double supplyVoltage=24, double minimumSupplyVoltage=8, bool enableControlsBridges=true)
        {
            if(Double.IsNaN(minimumSupplyVoltage)||Double.IsInfinity(minimumSupplyVoltage)||minimumSupplyVoltage<=0)
                throw new ArgumentException("Invalid generic undervoltage threshold");
            this.enableControlsBridges=enableControlsBridges;
            this.plant=plant;ports=new[]{gpioA,gpioB,gpioC};threshold=minimumSupplyVoltage;
            SetSupplyVoltage(supplyVoltage);
        }
        public void Reset(){Refresh();} // MCU reset is not a power-cycle of the external driver.
        public void OnGPIO(int number,bool value)
        {
            if(number!=0)throw new ArgumentOutOfRangeException("number");
            enable=!value;Refresh();
        }
        public void SetSupplyVoltage(double value)
        {
            if(Double.IsNaN(value)||Double.IsInfinity(value)||value<0)throw new ArgumentException("Invalid supply");
            plant.SetSupplyVoltage(value);supply=value;Refresh();
        }
        public void SetExternalFault(int axis,bool fault){Check(axis);faults[axis]=fault;Refresh();}
        public bool GetFault(int axis){Check(axis);return supply<threshold||faults[axis];}
        public bool EnableInput=>enable;
        public bool EnableControlsBridges=>enableControlsBridges;
        private void Refresh()
        {
            // Both explicit wiring hypotheses forward the actual raw control net to PB2.
            // Only the legacy hypothesis additionally gates bridge power from this net.
            ports[1].OnGPIO(2,!enable);
            // Report only external electrical faults, never rotor stall/homed state.
            for(int a=0;a<3;a++){bool fault=GetFault(a);plant.SetBridgeEnabled(a,(!enableControlsBridges||enable)&&!fault);ports[a].OnGPIO(pins[a],!fault);}
        }
        private static void Check(int a){if(a<0||a>2)throw new ArgumentOutOfRangeException("axis");}
        private readonly GenericStepperElectromechanical plant;private readonly AT32GPIO[] ports;
        private readonly int[] pins={12,1,12};private readonly bool[] faults=new bool[3];
        private readonly bool enableControlsBridges;
        private readonly double threshold;private double supply;private bool enable;
    }
}
