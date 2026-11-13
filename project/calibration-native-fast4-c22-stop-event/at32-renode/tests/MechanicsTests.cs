// SPDX-License-Identifier: MIT
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
 public class MechanicsTests : IPeripheral
 {
  public void Reset() { }
  int count;
  void Check(bool result,string name) { if(!result) throw new Exception(name); count++; }
  void Near(double actual,double expected,string name) { Check(Math.Abs(actual-expected)<1e-8,name); }
  void Step(VirtualPrinterAxis a) { a.OnGPIO(0,false); a.OnGPIO(0,true); }
  public string Run()
  {
   count=0;
   var a=new VirtualPrinterAxis(80,0,250,10);
   Check(!a.Enabled,"disabled at reset"); Near(a.PositionMillimeters,10,"initial position");
   Check(a.MinimumEndstop.IsSet && a.MaximumEndstop.IsSet,"inactive low-polarity endpoints");
   Step(a); Near(a.PositionMillimeters,10,"disabled pulses ignored");
   a.OnGPIO(2,false); Check(a.Enabled,"active-low enable"); a.OnGPIO(1,true);
   for(int i=0;i<80;i++) Step(a); Near(a.PositionMillimeters,11,"80step per mm");
   a.OnGPIO(0,true); Near(a.PositionMillimeters,11,"no repeated rising edge");
   a.OnGPIO(1,false); for(int i=0;i<80;i++) Step(a); Near(a.PositionMillimeters,10,"reverse movement");
   a.Stalled=true; Step(a); Near(a.PositionMillimeters,10,"stalled axis"); a.Stalled=false;
   a.SetPosition(0); Check(!a.MinimumEndstop.IsSet && a.MaximumEndstop.IsSet,"minimum asserted");
   Step(a); Near(a.PositionMillimeters,0,"hard-stop clamp"); Check(a.LimitCollisionCount==1,"collision observable");
   a.SetPosition(250); Check(a.MinimumEndstop.IsSet && !a.MaximumEndstop.IsSet,"maximum asserted");
   a.OnGPIO(1,true); Step(a); Near(a.PositionMillimeters,250,"maximum clamp");
   a.Reset(); Near(a.PositionMillimeters,250,"reset preserves position"); Check(!a.Enabled,"reset disables drive");
   a.RestoreInitialPosition(); Near(a.PositionMillimeters,10,"explicit initial reset"); Check(a.TotalStepPulses==0,"step count reset");
   var b=new VirtualPrinterAxis(100,0,100,10,false,true,false);
   b.OnGPIO(2,true); b.OnGPIO(1,true); Step(b); Near(b.PositionMillimeters,9.99,"active high reversed drive");
   b.SetPosition(0); Check(b.MinimumEndstop.IsSet,"active-high endstop");
   var s=new VirtualPrinterSwitch(true,false); Check(s.Output.IsSet,"inactive pullup switch");
   s.Asserted=true; Check(!s.Output.IsSet,"asserted active low switch"); s.Reset(); Check(s.Asserted && !s.Output.IsSet,"switch reset retention");
   bool rejected=false; try { new VirtualPrinterAxis(0); } catch(ArgumentException) { rejected=true; } Check(rejected,"invalid geometry rejected");
   rejected=false; try { a.SetPosition(double.NaN); } catch(ArgumentOutOfRangeException) { rejected=true; } Check(rejected,"NaN rejected");
   return "MECHANICS TESTS PASS: "+count;
  }
 }
}
