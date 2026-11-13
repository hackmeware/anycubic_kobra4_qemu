using System;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    public class PassiveMotorStateTraceTests : IBusPeripheral
    {
        public PassiveMotorStateTraceTests(IMachine machine,PassiveMotorStateTrace observer,
            GenericStepperElectromechanical plant,GenericMotorDriver driver,AT32GPIO gpioB,AT32Timer tmr3,AT32Timer tmr8)
        {bus=machine.GetSystemBus(this);o=observer;p=plant;d=driver;g=gpioB;t=tmr3;triggerTimer=tmr8;}
        public void Reset(){}
        private void Check(bool condition,string why){if(!condition)throw new Exception(why);checks++;}
        public string Run(string path)
        {
            // Synthetic test preparation only; no firmware is loaded or run.
            checks=0;bus.WriteByte(0x2000000a,4);bus.WriteWord(0x20000c00,0x1234);
            bus.WriteWord(0x2000418c,0x4567);bus.WriteWord(0x2000206c,0x2345);
            d.OnGPIO(0,false);t.WriteDoubleWord(0x2c,4000);
            var gpio=g.ReadDoubleWord(8);var angle=p.GetAngleRadians(0);var current=p.GetCurrent(0,0);
            var triggers=p.TriggerCount;var timer=t.ReadDoubleWord(0x2c);
            Check(!o.Enabled,"default observer is inactive");o.Start(path);
            Check(File.ReadAllLines(path).Length==3,"header visible while stream open");
            o.OnGPIO(1,true);o.OnGPIO(0,false);Check(o.TriggerCount==0,"ignore wrong pin and falling edge");
            o.OnGPIO(0,true);o.OnGPIO(0,true);Check(o.SampleCount==0,"decimation respected");
            o.OnGPIO(0,true);Check(o.SampleCount==1 && o.Enabled,"first decimated sample");
            var lines=File.ReadAllLines(path);Check(lines.Length==6,"three rows immediately readable");
            var header=lines[2].Split(',');var row=lines[3].Split(',');
            Check(row.Length==header.Length,"row/header field count");
            Func<string,string> field=name=>row[Array.IndexOf(header,name)];
            Check(field("commutation_mode")=="4" && field("status_word_raw")=="4660","SRAM sentinel reads");
            Check(field("control_angle_u16")=="17767" && field("calibration_target_current_u16_raw")=="9029","control/current sentinel reads");
            Check(field("logical_enable")=="1" && field("derived_raw_enable_level")=="0" && field("bridge_enabled")=="1","enable labels are not inverted twice");
            Check(field("pwm_reg_2c")=="4000","actual timer register read");
            o.OnGPIO(0,true);o.OnGPIO(0,true);o.OnGPIO(0,true);
            Check(o.SampleCount==2 && o.CapacityReached && !o.Enabled,"bounded stop");
            var size=new FileInfo(path).Length;o.OnGPIO(0,true);Check(new FileInfo(path).Length==size,"no writes after capacity");
            Check(bus.ReadWord(0x20000c00)==0x1234 && bus.ReadWord(0x2000418c)==0x4567,"observations preserve firmware SRAM");
            Check(g.ReadDoubleWord(8)==gpio && t.ReadDoubleWord(0x2c)==timer,"observations preserve GPIO and timer configuration");
            Check(p.GetAngleRadians(0)==angle && p.GetCurrent(0,0)==current && p.TriggerCount==triggers,"observer does not advance physical plant");
            Check(d.EnableInput && p.GetBridgeEnabled(0) && !d.GetFault(0),"observer preserves driver state");
            bool rejected=false;try{o.Start(path);}catch(IOException){rejected=true;}
            Check(rejected && new FileInfo(path).Length==size,"existing capture never overwritten");
            o.Reset();Check(!o.Enabled && o.SampleCount==0 && o.LastError=="","reset only observer state");
            o.Start(path+".fanout.csv");var before=p.TriggerCount;
            triggerTimer.TriggerOutput.Blink();
            Check(p.TriggerCount==before+1 && o.TriggerCount==1,"additional observer preserves existing physical-plant trigger receiver");
            o.Stop();
            return "PASSIVE MOTOR OBSERVER TESTS PASS: "+checks;
        }
        private readonly IBusController bus;private readonly PassiveMotorStateTrace o;
        private readonly GenericStepperElectromechanical p;private readonly GenericMotorDriver d;
        private readonly AT32GPIO g;private readonly AT32Timer t,triggerTimer;private int checks;
    }
}
