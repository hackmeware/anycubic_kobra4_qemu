// SPDX-License-Identifier: MIT
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
 public class GenericElectromechanicalTimingTests : IPeripheral
 {
  public GenericElectromechanicalTimingTests(GenericStepperElectromechanical plant,AT32Timer tmr3,AT32Timer tmr8,AT32ADC adc1){p=plant;t=tmr3;trigger=tmr8;adc=adc1;}
  public void Reset(){}
  void Check(bool v,string s){if(!v)throw new Exception(s);n++;}
  void Near(double a,double b,string s){Check(Math.Abs(a-b)<1e-9,s+": "+a+" vs "+b);}
  public string Start()
  {
   n=0;p.SetRotorLocked(0,true);t.Reset();trigger.Reset();adc.Reset();
   t.WriteDoubleWord(0x2c,1000);t.WriteDoubleWord(0x18,0x4040);t.WriteDoubleWord(0x1c,0x4040);
   t.WriteDoubleWord(0x20,0x1111);t.WriteDoubleWord(0,1);t.WriteDoubleWord(0x20,0x3131);
   Check(p.TriggerCount==0,"no invented ADC trigger");return "ELECTROMECHANICAL PULSE STARTED";
  }
  public string EndPulse()
  {
   t.WriteDoubleWord(0x20,0x1111);expected=-12*(1-Math.Exp(-0.000001*2/0.003));
   Near(p.GetCurrent(0,0),expected,"old voltage integrated before change");
   t.WriteDoubleWord(0x20,0x3131);t.WriteDoubleWord(0x20,0x1111);
   Near(p.GetCurrent(0,0),expected,"same timestamp adds no energy");return "ELECTROMECHANICAL PULSE ENDED";
  }
  public string CheckAfterDecay()
  {
   adc.WriteDoubleWord(0x38,0);adc.WriteDoubleWord(8,0x0100f001);
   trigger.WriteDoubleWord(4,0x20);trigger.WriteDoubleWord(0x14,1);
   expected*=Math.Exp(-0.000032*2/0.003);
   Near(p.GetCurrent(0,0),expected,"real elapsed decay at trigger");
   Check(p.TriggerCount>0,"actual timer trigger sampled plant");
   Check(adc.ReadDoubleWord(0x3c)==(uint)Math.Round(2048+500*expected),"actual ADC current sample");
   double before=p.GetCurrent(0,0);p.Reset();Near(p.GetCurrent(0,0),before,"MCU reset retains physical current");
   Near(p.GetAngleRadians(0),0,"physical lock retained");p.CaptureTrace();
   return "ELECTROMECHANICAL TIMING TESTS PASS: "+n;
  }
  GenericStepperElectromechanical p;AT32Timer t,trigger;AT32ADC adc;int n;double expected;
 }
}
