// SPDX-License-Identifier: MIT
using System;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
 public class CommandedMotionTests : IPeripheral
 {
  public CommandedMotionTests(AT32GPIO port,VirtualStepperCommandObserver observer, VirtualStepperCommandObserver both) { p=port;o=observer;this.both=both; }
  public void Reset() { }
  public string Run()
  {
   // Pin4 DIR and pin5 STEP, output push/pull. Observe actual peripheral changes.
   p.WriteDoubleWord(0,0x44334444);p.WriteDoubleWord(12,0);
   ulong before=o.RisingEdges;long signed=o.SignedSteps;
   for(int i=0;i<3200;i++){p.WriteDoubleWord(12,32);p.WriteDoubleWord(12,0);}
   if(o.RisingEdges-before!=3200 || o.SignedSteps-signed!=3200) throw new Exception("pulse count/direction");
   if(Math.Abs(o.CommandedTravelMillimeters-39)>1e-8)throw new Exception("configured scale");
   p.WriteDoubleWord(12,16);p.WriteDoubleWord(12,48);p.WriteDoubleWord(12,48);
   if(o.RisingEdges!=before+3201 || o.SignedSteps!=signed+3199)throw new Exception("reverse/duplicate");
   var retained=o.SignedSteps;o.Reset();if(o.SignedSteps!=retained)throw new Exception("reset retention");
   if(o.RowCount!=8 || !o.CapacityReached)throw new Exception("bounded trace");
   if(both.StepEvents!=6401 || both.SignedSteps!=6399)throw new Exception("both-edge mode");
   return "COMMANDED MOTION TESTS PASS";
  }
  private AT32GPIO p;private VirtualStepperCommandObserver o,both;
 }
}
