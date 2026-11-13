using System;
using Antmicro.Renode.Peripherals.Bus;
namespace Antmicro.Renode.Peripherals.NozzleExperimental
{
 public class Cs1237FunctionalTests : IBusPeripheral
 {
  public void Reset(){}
  private void Check(bool v,string s){if(!v)throw new Exception(s);checks++;}
  public string RunAll()
  {
   foreach(int code in new[]{0,1,-1,123456,-123456,8388607,-8388608})
   {
    var p=new Cs1237FunctionalProtocol(500);p.SetSyntheticCode(code);p.AdvanceTo(301999999);Check(!p.Ready,"no early readiness");p.AdvanceTo(302000000);uint word=0;long t=302001000;
    for(int n=0;n<24;n++)
    {p.SetSclk(true,t);p.SetSclk(false,t+300);p.AdvanceTo(t+550);word=(word<<1)|(p.ResolvedDout==true?1u:0u);t+=600;}
    Check(word==Cs1237FunctionalProtocol.WireBits(code),"actual signed wire word");Check(!p.ProtocolFault,"functional pulse does not masquerade as strict failure");Check(p.HighPulseTimingViolations==24 && p.LowPulseTimingViolations==23,"all short phases counted");Check(p.MinimumHighNanoseconds==300 && p.MinimumLowNanoseconds==300,"measured durations retained");
   }
   var q=new Cs1237FunctionalProtocol(500);q.SetSyntheticCode(0);q.SetSclk(true,1000);q.SetSclk(false,1300);Check(q.ProtocolFault,"pre-ready clock still fails");
   q.SetSclk(true,1600);q.SetSclk(false,1900);Check(q.HighPulseTimingViolations==2 && q.LowPulseTimingViolations==1,"timing observations retained after semantic fault");
   var missing=new Cs1237FunctionalProtocol(500);missing.AdvanceTo(302000000);Check(missing.ProtocolFault && !missing.Ready,"missing source cannot manufacture conversion");
   var overlap=new Cs1237FunctionalProtocol(500);overlap.SetSyntheticCode(0);overlap.SetHostDout(true,0);overlap.SetHostDout(false,1);Check(overlap.OverlapBothHigh==1 && overlap.OverlapHostLowDeviceHigh==1,"electrical deviations classified");Check(!overlap.ProtocolFault,"explicit arbitration is separate from framing fault");overlap.SetHostDout(null,2);overlap.SetSclk(true,10);overlap.AdvanceTo(100011);Check(overlap.PoweredDown,"elapsed power-down retained");overlap.SetSclk(false,100012);Check(!overlap.Ready,"wake does not manufacture readiness");
   return "CS1237 FUNCTIONAL TESTS PASS: "+checks;
  }
  private int checks;
 }
}
