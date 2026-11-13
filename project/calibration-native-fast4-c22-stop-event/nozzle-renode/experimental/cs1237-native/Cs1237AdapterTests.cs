using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
namespace Antmicro.Renode.Peripherals.NozzleExperimental
{
 public class Cs1237AdapterTests : IBusPeripheral
 {
  public Cs1237AdapterTests(Cs1237NativeGpio p1,Cs1237NativeGpio p2,Cs1237NativeGpio p3,Cs1237NativeGpio p4,Cs1237NativeGpio p5,Cs1237NativeGpio p6,Cs1237NativeGpio p7,Cs1237NativeAdapter a1,Cs1237NativeAdapter a2,Cs1237NativeAdapter a3,Cs1237NativeAdapter a4,Cs1237NativeAdapter a5,Cs1237NativeAdapter a6,Cs1237NativeAdapter a7)
  {p=new[]{p1,p2,p3,p4,p5,p6,p7};a=new[]{a1,a2,a3,a4,a5,a6,a7};}
  public void Reset(){}
  private void Check(bool ok,string why){if(!ok)throw new Exception(why);checks++;}
  private void Reject(Action f,string why){bool threw=false;try{f();}catch(InvalidOperationException){threw=true;}Check(threw,why);}
  private void Mode(int i,int pin,uint mode){uint mask=15u<<(pin*4);p[i].WriteDoubleWord(0,(p[i].Snapshot(0)&~mask)|(mode<<(pin*4)));}
  public void Prepare()
  {
   a[1].Source=()=>{throw new Exception("deliberate laboratory source failure");};
   Mode(2,6,2);Check(a[2].Protocol.ProtocolFault,"strict overlap must fault");
   Mode(4,5,10);Check(a[4].AdapterErrors==1,"AF SCLK rejected");Reject(()=>a[4].ValidateSensorLevel(),"latched adapter error cannot return pull/default");
  }
  public void Ready()
  {
   Check(a[0].Protocol.ConversionCount==1,"conversion after actual302ms");Check(!a[0].ValidateSensorLevel(),"ready low");
   Check(a[1].AdapterErrors==1,"source exception latched");Reject(()=>a[1].ValidateSensorLevel(),"source error invalidates read");
   Mode(0,6,0);Reject(()=>a[0].ValidateSensorLevel(),"analog mode cannot read as valid sensor");
   Mode(3,6,2);Check(a[3].Protocol.HostPriorityOverlapObservations>0,"explicit overlap accounted");Reject(()=>a[3].ValidateSensorLevel(),"host-owned level is not sensor sample");
  }
  public void BeginReset()
  {
   Mode(5,5,2);p[5].WriteDoubleWord(16,32);Check(a[5].Protocol.Sclk,"real high received");
   p[6].WriteDoubleWord(16,64);Mode(6,6,2);Check(a[6].Protocol.HostDout==true,"real host drive received");
  }
  public void EndReset()
  {
   p[5].Reset();p[6].Reset();
   Check(!a[5].Protocol.Sclk,"GPIO reset propagates falling clock");Check(!a[6].Protocol.HostDout.HasValue,"GPIO reset releases host DOUT");
   Check(a[5].Protocol.ClockCount==1,"MCU reset does not reset sensor framing");Check(a[6].Protocol.ConversionCount==1,"MCU reset does not erase conversion state");
   Check(((p[6].Snapshot(8)&64)!=0)==a[6].Protocol.DeviceDout.Value,"sensor drive restored after host GPIO reset");
   Check((p[5].Snapshot(8)&128)==0 && (p[6].Snapshot(8)&128)==0,"no PA7 drive");
  }
  public string Finish()
  {
   Check(a[5].Protocol.ProtocolFault,"unfinished frame after MCU reset remains visible fault");
   Check(a[6].Protocol.ConversionCount>=2 && !a[6].Protocol.ProtocolFault,"released host reset preserves normal conversion schedule");
   return "CS1237 ADAPTER TESTS PASS: "+checks;
  }
  private readonly Cs1237NativeGpio[] p;private readonly Cs1237NativeAdapter[] a;private int checks;
 }
}
