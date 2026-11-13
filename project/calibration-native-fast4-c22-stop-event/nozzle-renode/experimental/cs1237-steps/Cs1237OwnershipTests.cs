// CPU-free checks of host-drive classification; no original firmware or physical circuit claim.
using System;
using Antmicro.Renode.Peripherals.Bus;
namespace Antmicro.Renode.Peripherals.NozzleExperimental
{
 public class Cs1237OwnershipTests : IBusPeripheral
 {
  public Cs1237OwnershipTests(Cs1237NativeGpio port,Cs1237NativeAdapter sensor,Cs1237NativeGpio afod,Cs1237NativeAdapter afods,Cs1237NativeGpio afpp,Cs1237NativeAdapter afpps)
  {this.port=port;this.sensor=sensor;this.afod=afod;this.afods=afods;this.afpp=afpp;this.afpps=afpps;}
  public void Reset(){}
  private void Check(bool yes,string label){if(!yes)throw new Exception(label);checks++;}
  private void Mode(Cs1237NativeGpio p,uint nibble){p.WriteDoubleWord(0,(p.Snapshot(0)&~0x0f000000u)|(nibble<<24));}
  public string RunAll()
  {
   port.WriteDoubleWord(16,64);
   foreach(uint n in new uint[]{5,6,7})
   {
    Mode(port,n);Check(sensor.Protocol.HostDout==null,"open-drain high releases host at all MODE speeds");
    Check(sensor.Protocol.Errors==0 && sensor.Protocol.HostPriorityOverlapObservations==0,"released OD high is not overlap");
    Check((port.Snapshot(8)&64)!=0,"released OD pad follows external device high");
   }
   port.WriteDoubleWord(16,64u<<16);Check(sensor.Protocol.HostDout==false,"open-drain low drives low");Check(sensor.Protocol.ProtocolFault,"OD low against device high is strict conflict");
   afod.WriteDoubleWord(16,64);Mode(afod,13);Check(afods.AdapterErrors==1,"alternate OD explicitly unsupported");Check(afods.Protocol.HostPriorityOverlapObservations==0,"unsupported AF OD not miscounted as push-pull");
   afpp.WriteDoubleWord(16,64);Mode(afpp,9);Check(afpps.AdapterErrors==1,"alternate push-pull explicitly unsupported");
   return "CS1237 OWNERSHIP TESTS PASS: "+checks;
  }
  private readonly Cs1237NativeGpio port,afod,afpp;private readonly Cs1237NativeAdapter sensor,afods,afpps;private int checks;
 }
}
