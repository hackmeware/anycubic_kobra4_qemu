using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
 public class GenericDriverTests : IPeripheral
 {
  public GenericDriverTests(GenericMotorDriver driver,GenericStepperElectromechanical plant,AT32GPIO gpioA,AT32GPIO gpioB,AT32GPIO gpioC,AT32Timer tmr3){d=driver;p=plant;t=tmr3;ports=new[]{gpioA,gpioB,gpioC};}
  public void Reset(){}
  void Check(bool value,string why){if(!value)throw new Exception(why);count++;}
  public string Run()
  {
   count=0;
   for(int a=0;a<3;a++){Check(!p.GetBridgeEnabled(a),"default disabled");Check((ports[a].ReadDoubleWord(8)&(1u<<pins[a]))!=0,"healthy nFAULT released high");}
   d.OnGPIO(0,false);for(int a=0;a<3;a++)Check(p.GetBridgeEnabled(a),"enable input gates bridge");
   Check((ports[1].ReadDoubleWord(8)&4)==0,"active low enable reaches motor PB2");
   d.SetExternalFault(1,true);Check(!p.GetBridgeEnabled(1),"fault gates affected bridge");Check((ports[1].ReadDoubleWord(8)&2)==0,"active low fault");Check(p.GetBridgeEnabled(0)&&p.GetBridgeEnabled(2),"fault is axis local");
   d.SetExternalFault(1,false);Check(p.GetBridgeEnabled(1),"fault removal restores enabled bridge");
   d.SetSupplyVoltage(0);for(int a=0;a<3;a++){Check(!p.GetBridgeEnabled(a),"no drive without supply");Check(d.GetFault(a),"undervoltage remains fault");}
   d.SetSupplyVoltage(24);d.OnGPIO(0,true);for(int a=0;a<3;a++)Check(!p.GetBridgeEnabled(a)&&!d.GetFault(a),"disabled is not invented fault");
   d.Reset();Check(!d.EnableInput,"reset does not invent enable");
   Check((ports[1].ReadDoubleWord(8)&4)!=0,"inactive high enable reaches motor PB2");
   return "GENERIC DRIVER TESTS PASS: "+count;
  }
  public void BeginPhysicalGateTest()
  {
   count=0;p.SetRotorLocked(0,true);t.Reset();t.WriteDoubleWord(0x2c,1000);t.WriteDoubleWord(0x18,0x4040);t.WriteDoubleWord(0x1c,0x4040);t.WriteDoubleWord(0x20,0x3131);t.WriteDoubleWord(0,1);
  }
  public void EnablePhysicalDrive()
  {d.OnGPIO(0,false);Check(p.GetCurrent(0,0)==0,"disabled PWM adds no current");}
  public void DisablePhysicalDrive()
  {d.OnGPIO(0,true);expected=-12*(1-Math.Exp(-0.00001*2/0.003));Check(Math.Abs(p.GetCurrent(0,0)-expected)<1e-9,"enabled PWM produces physical current");}
  public string CheckPhysicalDecay()
  {d.OnGPIO(0,true);expected*=Math.Exp(-0.00001*2/0.003);Check(Math.Abs(p.GetCurrent(0,0)-expected)<1e-9,"disabled bridge preserves and dissipates existing current");return "GENERIC DRIVER PHYSICAL TESTS PASS: "+count;}
  GenericMotorDriver d;GenericStepperElectromechanical p;AT32GPIO[] ports;AT32Timer t;int[] pins={12,1,12};int count;double expected;
 }
}
