using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    public class MotorTriggerTests : IPeripheral, IGPIOReceiver
    {
        public MotorTriggerTests(AT32Timer master, AT32Timer slave, AT32ADC adc, AT32Timer pwm3, AT32Timer pwm4, VirtualMotorPWMTriggers wiring)
        {
            this.pwm3=pwm3; this.pwm4=pwm4; this.wiring=wiring;
            this.master=master; this.slave=slave; this.adc=adc;
            master.TriggerOutput.Connect(slave,17);
            slave.TriggerOutput.Connect(adc,15);
            slave.TriggerOutput.Connect(this,0);
        }
        public void Reset() { count=0; }
        public void OnGPIO(int number,bool value) { if(value) count++; }
        private void Check(bool v,string label) { if(!v) throw new Exception(label); checks++; }
        public string Prepare()
        {
            checks=0; master.Reset(); slave.Reset(); adc.Reset(); count=0;
            Check(!master.Enabled && !slave.Enabled,"reset disabled");
            Check(master.ReadDoubleWord(4)==0,"reset master mode");
            adc.SetChannelValue(0,2048); adc.WriteDoubleWord(4,0x80); adc.WriteDoubleWord(0x38,0);
            adc.TriggerPreempt(15); Check(adc.ReadDoubleWord(0)==0,"disabled ADC rejects external event");
            adc.WriteDoubleWord(8,0x0100F001); adc.TriggerPreempt(14);
            Check(adc.ReadDoubleWord(0)==0,"wrong trigger source ignored");
            adc.TriggerPreempt(15); Check(adc.ReadDoubleWord(0x3C)==2048,"selected trigger samples zero current");
            Check(adc.IRQ.IsSet,"injected conversion IRQ"); adc.WriteDoubleWord(0,0);
            Check(!adc.IRQ.IsSet,"status clear deasserts IRQ");
            master.WriteDoubleWord(0x2C,20); master.WriteDoubleWord(4,0x10);
            slave.WriteDoubleWord(0x2C,10); slave.WriteDoubleWord(4,0x20); slave.WriteDoubleWord(8,6); slave.WriteDoubleWord(0,8);
            Check(master.ReadDoubleWord(4)==0x10 && slave.ReadDoubleWord(4)==0x20,"MMS readback retained");
            master.WriteDoubleWord(0,1); Check(!slave.Enabled,"unselected internal input does not start");
            master.WriteDoubleWord(0,0); slave.WriteDoubleWord(8,0x16); master.WriteDoubleWord(0,1);
            Check(slave.Enabled && (slave.ReadDoubleWord(0)&1)!=0,"selected edge sets slave CEN");
            Check(count==0,"ADC not triggered prematurely");
            return "MOTOR TRIGGER PREPARED";
        }
        public string AfterTime()
        {
            Check(!slave.Enabled && (slave.ReadDoubleWord(0)&1)==0,"one pulse stops slave");
            Check(count==1,"one update produces one event");
            Check(adc.ReadDoubleWord(0x3C)==2048 && adc.IRQ.IsSet,"timer update reaches ADC");
            master.WriteDoubleWord(0,0); master.WriteDoubleWord(0,1); Check(slave.Enabled,"second rising edge rearms one pulse");
            slave.WriteDoubleWord(0,8); Check(!slave.Enabled,"software disable stops slave");
            adc.WriteDoubleWord(0,0); slave.WriteDoubleWord(0x14,1); Check(count==2 && adc.IRQ.IsSet,"software update selected TRGO");
            adc.WriteDoubleWord(0,0); slave.WriteDoubleWord(0,10); slave.WriteDoubleWord(0x14,1);
            Check(count==2 && !adc.IRQ.IsSet,"UDIS suppresses update trigger");
            slave.Reset(); Check(!slave.Enabled && slave.ReadDoubleWord(4)==0,"reset clears trigger config");
            adc.WriteDoubleWord(0,0); adc.SetChannelValue(0,0); adc.TriggerPreempt(15);
            Check(adc.ReadDoubleWord(0x3C)==0,"zero input stays zero without success spoof");
            slave.Reset(); count=0;
            slave.WriteDoubleWord(0x2C,10); slave.WriteDoubleWord(0x30,1);
            slave.WriteDoubleWord(4,0x20); slave.WriteDoubleWord(0,0x21);
            return "MOTOR REPETITION PREPARED";
        }
        public string AfterRepetition()
        {
            Check(count==2,"RCR1 emits one trigger per two counter boundaries");
            slave.Reset(); Check(!slave.TriggerOutput.IsSet,"reset deasserts TRGO");
            Check(wiring.Connected,"PWM wiring component instantiated");
            master.Reset(); pwm3.Reset(); pwm4.Reset();
            foreach(var pwm in new[]{pwm3,pwm4}) { pwm.WriteDoubleWord(0x2C,4000); pwm.WriteDoubleWord(8,0x16); }
            Check(!pwm3.Enabled && !pwm4.Enabled,"PWM timers remain stopped before trigger");
            master.WriteDoubleWord(4,0x10); master.WriteDoubleWord(0x2C,20); master.WriteDoubleWord(0,1);
            Check(pwm3.Enabled && pwm4.Enabled,"TMR2 enable starts both IS1 PWM timers");
            pwm3.WriteDoubleWord(0x18,0x6868); pwm3.WriteDoubleWord(0x1C,0x6868);
            Check(pwm3.ReadDoubleWord(0x18)==0x6868 && pwm3.ReadDoubleWord(0x1C)==0x6868,"PWM modes and preload config retained");
            pwm3.WriteDoubleWord(0x20,0x3131);
            Check(pwm3.ReadDoubleWord(0x20)==0x3131,"independent output enables and polarities retained");
            pwm3.WriteDoubleWord(0x20,0x1313);
            Check(pwm3.ReadDoubleWord(0x20)==0x1313,"polarity reversal retained");
            pwm3.WriteDoubleWord(0x44,0x80A5);
            Check(pwm3.ReadDoubleWord(0x44)==0x80A5,"main output and deadtime config retained");
            pwm3.WriteDoubleWord(0x18,0x4040);
            Check(pwm3.ReadDoubleWord(0x18)==0x4040,"forced inactive mode and cleared preload retained");
            pwm3.Reset(); Check(pwm3.ReadDoubleWord(0x44)==0 && pwm3.ReadDoubleWord(0x18)==0,"reset clears diagnostic config");
            return "MOTOR TRIGGER TESTS PASS: "+checks;
        }
        private readonly AT32Timer master,slave,pwm3,pwm4; private readonly VirtualMotorPWMTriggers wiring; private readonly AT32ADC adc; private int count,checks;
    }
}
