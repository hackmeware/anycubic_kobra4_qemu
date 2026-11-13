using System;
using System.IO;
using System.Text;
using System.Globalization;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    // Read-only observer. Never changes plant, timer, ADC or firmware state.
    public class CurrentLoopTrace : IPeripheral, IGPIOReceiver
    {
        public CurrentLoopTrace(IMachine machine,GenericStationaryMotorRL plant,AT32Timer tmr1,AT32Timer tmr3,AT32Timer tmr4,AT32Timer tmr8)
        { this.machine=machine; this.plant=plant; timers=new[]{tmr3,tmr1,tmr4}; tmr8.TriggerOutput.Connect(this,0); }
        public void Reset() { Enabled=false; data.Clear(); }
        public void Start() { data.Clear(); data.AppendLine("time,axis,i1,i2,v1,v2,ctrl,ccmr1,ccmr2,ccer,ccr1,ccr2,ccr3,ccr4"); Enabled=true; }
        public void Save(string path) { File.WriteAllText(path,data.ToString()); }
        public void OnGPIO(int number,bool value)
        {
            if(!Enabled || !value || number!=0) return;
            for(int a=0;a<3;a++)
            {
                var t=timers[a];
                data.Append(machine.ElapsedVirtualTime.TimeElapsed.TotalSeconds.ToString("R",CultureInfo.InvariantCulture)).Append(',').Append(a);
                foreach(double x in new[]{plant.GetCurrent(a,0),plant.GetCurrent(a,1),plant.GetPhaseVoltage(a,0),plant.GetPhaseVoltage(a,1)}) data.Append(',').Append(x.ToString("R",CultureInfo.InvariantCulture));
                foreach(int offset in new[]{0,0x18,0x1c,0x20,0x34,0x38,0x3c,0x40}) data.Append(',').Append(t.ReadDoubleWord(offset));
                data.AppendLine();
            }
        }
        public bool Enabled { get; set; }
        readonly IMachine machine; readonly GenericStationaryMotorRL plant; readonly AT32Timer[] timers;
        readonly StringBuilder data=new StringBuilder();
    }
}
