using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
 public class GenericMcuControlDriverTests : IPeripheral
 {
  public GenericMcuControlDriverTests(GenericMotorDriver driver,GenericStepperElectromechanical plant,AT32GPIO gpioB){d=driver;p=plant;b=gpioB;}
  public void Reset(){}
  private void Check(bool ok,string why){if(!ok)throw new Exception(why);n++;}
  public string Run()
  {
   n=0;Check(!d.EnableControlsBridges,"explicit alternate topology");
   d.OnGPIO(0,true);Check(!d.EnableInput,"logical input still inactive");Check((b.ReadDoubleWord(8)&4)!=0,"raw high forwarded to PB2");
   for(int a=0;a<3;a++)Check(p.GetBridgeEnabled(a)&&!d.GetFault(a),"inactive MCU input does not gate powered bridge");
   d.OnGPIO(0,false);Check(d.EnableInput&&(b.ReadDoubleWord(8)&4)==0,"raw low forwarded");
   for(int a=0;a<3;a++)Check(p.GetBridgeEnabled(a),"raw low retains bridge power");
   d.OnGPIO(0,true);d.SetExternalFault(1,true);Check(!p.GetBridgeEnabled(1)&&d.GetFault(1),"external fault still gates");Check((b.ReadDoubleWord(8)&2)==0,"fault pin asserted");Check(p.GetBridgeEnabled(0)&&p.GetBridgeEnabled(2),"fault local");
   d.SetExternalFault(1,false);Check(p.GetBridgeEnabled(1),"fault removal restores power");
   d.SetSupplyVoltage(0);for(int a=0;a<3;a++)Check(!p.GetBridgeEnabled(a)&&d.GetFault(a),"zero supply remains disabling fault");
   d.SetSupplyVoltage(7);for(int a=0;a<3;a++)Check(!p.GetBridgeEnabled(a)&&d.GetFault(a),"undervoltage remains disabling fault");
   Check((b.ReadDoubleWord(8)&4)!=0,"faults do not fabricate PB2 edges");
   d.SetSupplyVoltage(24);d.Reset();Check(!d.EnableInput&&(b.ReadDoubleWord(8)&4)!=0,"reset preserves raw high");
   for(int a=0;a<3;a++)Check(p.GetBridgeEnabled(a)&&!d.GetFault(a),"healthy supply restores powered bridge");
   return "MCU CONTROL ONLY DRIVER TESTS PASS: "+n;
  }
  private readonly GenericMotorDriver d;private readonly GenericStepperElectromechanical p;private readonly AT32GPIO b;private int n;
 }
}
