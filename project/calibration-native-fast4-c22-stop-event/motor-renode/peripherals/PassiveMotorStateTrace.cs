// SPDX-License-Identifier: MIT
// Optional observation only. No firmware/physical state is changed by this class.
using System;
using System.Globalization;
using System.IO;
using System.Text;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
namespace Antmicro.Renode.Peripherals.AT32
{
    public class PassiveMotorStateTrace : IBusPeripheral, IGPIOReceiver, IDisposable
    {
        public PassiveMotorStateTrace(IMachine machine, GenericStepperElectromechanical plant,
            GenericMotorDriver driver, AT32GPIO gpioB, AT32Timer tmr1, AT32Timer tmr2,
            AT32Timer tmr3, AT32Timer tmr4, AT32Timer tmr8,
            int sampleEveryTriggers=1000, int maximumSamples=20000)
        {
            if(sampleEveryTriggers<1 || maximumSamples<1 || maximumSamples>100000)
                throw new ArgumentException("Invalid observer bounds");
            this.machine=machine;bus=machine.GetSystemBus(this);this.plant=plant;
            this.driver=driver;this.gpioB=gpioB;this.tmr2=tmr2;
            timers=new[]{tmr3,tmr1,tmr4};every=(ulong)sampleEveryTriggers;maximum=maximumSamples;
            // Construct after the plant: this adds an observer to its existing trigger.
            tmr8.TriggerOutput.Connect(this,0);
        }
        public void Start(string outputPath)
        {
            if(Enabled)throw new InvalidOperationException("Observer already running");
            Stop();
            // Never overwrite a previous observation. Shared reads permit live inspection.
            writer=new StreamWriter(new FileStream(outputPath,FileMode.CreateNew,FileAccess.Write,FileShare.Read),new UTF8Encoding(false));
            try
            {
                writer.WriteLine("# PASSIVE MOTOR SNAPSHOT v1; SRAM layout expects motor SHA256 76b439293ab08207317007f5179243a0684c1b27668442781bcb2e201ff62661; hash not checked by observer");
                writer.WriteLine("# Raw firmware fields are not physical rotor truth; assumed physical rotor is separate; logical_enable is inverted input, derived_raw_enable_level=NOT logical_enable; sampling is decimated, not an event-complete trace");
                writer.WriteLine(Header());writer.Flush();
            }
            catch {Stop();throw;}
            TriggerCount=0;SampleCount=0;CapacityReached=false;LastError="";Enabled=true;
        }
        public void Stop()
        {
            Enabled=false;
            if(writer!=null){var closing=writer;writer=null;closing.Dispose();}
        }
        public void Reset(){Stop();TriggerCount=0;SampleCount=0;CapacityReached=false;LastError="";}
        public void Dispose(){Stop();}
        public void OnGPIO(int number,bool value)
        {
            if(!Enabled || number!=0 || !value)return;
            TriggerCount++;
            if(TriggerCount%every!=0)return;
            try
            {
                var time=machine.ElapsedVirtualTime.TimeElapsed.TotalSeconds;
                for(int axis=0;axis<3;axis++)writer.WriteLine(Row(axis,time));
                writer.Flush(); // Make each complete three-axis sample visible immediately.
                SampleCount++;
                if(SampleCount>=maximum){CapacityReached=true;Stop();}
            }
            catch(Exception e)
            {
                // An observer/output failure must not inject an exception into firmware execution.
                LastError=e.GetType().Name+": "+e.Message;Enabled=false;
                try{Stop();}catch{}
            }
        }
        private string Row(int axis,double time)
        {
            var row=new StringBuilder();
            Action<object> add=v=>{if(row.Length!=0)row.Append(',');row.Append(v is double ? ((double)v).ToString("R",CultureInfo.InvariantCulture) : Convert.ToString(v,CultureInfo.InvariantCulture));};
            add(time);add(SampleCount);add(TriggerCount);add(axis);
            add(driver.EnableInput?1:0);add(driver.EnableInput?0:1);
            add(plant.GetBridgeEnabled(axis)?1:0);add(driver.GetFault(axis)?1:0);
            foreach(long offset in new long[]{0,4,8,12})add(gpioB.ReadDoubleWord(offset));
            add(bus.ReadByte(0x2000000aUL+(ulong)axis));
            add(bus.ReadByte(0x2000070dUL+(ulong)axis));
            add(bus.ReadByte(0x20000713UL+(ulong)axis));
            add(bus.ReadByte(0x20000716UL+(ulong)axis));
            add(bus.ReadWord(0x20000c00UL+(ulong)axis*0x10));
            add(bus.ReadByte(0x20000538));
            for(ulong address=0x20000550;address<=0x20000554;address++)add(bus.ReadByte(address));
            var detector=0x20003a2cUL+(ulong)axis*0x54;
            add(bus.ReadByte(detector+0x50));add(bus.ReadByte(detector+0x51));
            add(bus.ReadByte(0x2000064cUL+(ulong)axis*6));
            add(bus.ReadByte(0x2000064dUL+(ulong)axis*6));
            add(bus.ReadByte(0x20003b3f));
            var control=0x20004180UL+(ulong)axis*0x6c;
            add(bus.ReadWord(control+0x0c));add(bus.ReadDoubleWord(control+0x10));
            foreach(ulong offset in controlHalfwords)add(bus.ReadWord(control+offset));
            var calibration=0x20002038UL+(ulong)axis*0x1f4;
            add(bus.ReadWord(calibration+0x0c));add(bus.ReadWord(calibration+0x34));
            foreach(long offset in timerOffsets)add(timers[axis].ReadDoubleWord(offset));
            foreach(long offset in syncOffsets)add(tmr2.ReadDoubleWord(offset));
            add(plant.GetAngleRadians(axis));add(plant.GetVelocityRadiansPerSecond(axis));
            add(plant.GetCurrent(axis,0));add(plant.GetCurrent(axis,1));
            add(plant.GetTorqueNewtonMeters(axis));add(plant.GetStoredEnergyJoules(axis));
            add(plant.GetRelativeTravelMillimeters(axis));
            return row.ToString();
        }
        private static string Header()
        {
            var s="virtual_time_s,sample,trigger_count,axis,logical_enable,derived_raw_enable_level,bridge_enabled,external_fault,gpiob_config_low,gpiob_config_high,gpiob_idt,gpiob_odt,commutation_mode,state_070d_raw,state_0713_raw,state_0716_raw,status_word_raw,pb2_high_count_raw,pb2_0550_raw,pb2_0551_raw,pb2_0552_raw,pb2_0553_raw,pb2_0554_raw,detector_50_raw,detector_51_raw,detector_path_raw,alternate_event_raw,xy_output_suppression_raw,control_angle_u16,control_speed_word_raw";
            foreach(ulong offset in controlHalfwords)s+=",control_"+offset.ToString("x2")+"_u16_raw";
            s+=",calibration_measured_current_u16_raw,calibration_target_current_u16_raw";
            foreach(long offset in timerOffsets)s+=",pwm_reg_"+offset.ToString("x2");
            foreach(long offset in syncOffsets)s+=",tmr2_reg_"+offset.ToString("x2");
            return s+",physical_angle_rad,physical_velocity_rad_s,physical_ia_amp,physical_ib_amp,physical_torque_nm,physical_energy_j,physical_relative_mm";
        }
        public bool Enabled{get;private set;}
        public ulong TriggerCount{get;private set;}
        public int SampleCount{get;private set;}
        public bool CapacityReached{get;private set;}
        public string LastError{get;private set;}="";
        private static readonly ulong[] controlHalfwords={0x2a,0x2c,0x32,0x34,0x36,0x38,0x3a,0x3c,0x3e,0x40,0x42,0x44};
        private static readonly long[] timerOffsets={0,4,8,0x10,0x18,0x1c,0x20,0x24,0x28,0x2c,0x30,0x34,0x38,0x3c,0x40,0x44};
        private static readonly long[] syncOffsets={0,4,8,0x10,0x20,0x24,0x28,0x2c,0x34};
        private readonly IMachine machine;private readonly IBusController bus;
        private readonly GenericStepperElectromechanical plant;private readonly GenericMotorDriver driver;
        private readonly AT32GPIO gpioB;private readonly AT32Timer[] timers;private readonly AT32Timer tmr2;
        private readonly ulong every;private readonly int maximum;private StreamWriter writer;
    }
}
