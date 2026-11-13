using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
 public class AssumedDiagCableTests : IPeripheral
 {
  public AssumedDiagCableTests(AT32GPIO gpio){this.gpio=gpio;}
  public void Reset(){checks=0;}
  public void SetupTarget()
  {
   gpio.WriteDoubleWord(0,0x48444444);gpio.WriteDoubleWord(4,0x84444444);gpio.WriteDoubleWord(12,0x8040);
   Check(0x8040,"unconnected target pullups");
  }
  public void SetupSource(){gpio.WriteDoubleWord(0,0x44224444);gpio.WriteDoubleWord(12,0);}
  public void Drive(int stage)
  {
   switch(stage)
   {
    case 1: gpio.WriteDoubleWord(0x10,0x20);break;
    case 2: gpio.WriteDoubleWord(0x10,0x10);break;
    case 3: gpio.WriteDoubleWord(0x14,0x20);break;
    case 4: gpio.WriteDoubleWord(0x14,0x10);break;
    case 5: gpio.WriteDoubleWord(0x10,0x40);break;
    default:throw new ArgumentOutOfRangeException("stage");
   }
  }
  // Called only after the script advances virtual time to deliver connector events.
  public void CheckStage(int stage)
  {
   uint[] expected={0,0x40,0x8040,0x8000,0,0};
   string[] labels={"idle outputs override pullups","PB5 to PA6","PB4 to PA15 independent","PB5 low propagates","both outputs low","unselected PB6 ignored"};
   if(stage<0||stage>=expected.Length)throw new ArgumentOutOfRangeException("stage");
   Check(expected[stage],labels[stage]);
  }
  public string Result(){if(checks!=7)throw new Exception("Incomplete cable test");return "PASS: six assumed diagnostic GPIO cable checks plus unconnected pullups; two machines, no firmware or homing claim";}
  private void Check(uint expected,string label){uint actual=gpio.ReadDoubleWord(8)&0x8040;if(actual!=expected)throw new Exception(label+": "+actual+" != "+expected);checks++;}
  private readonly AT32GPIO gpio;private int checks;
 }
}
