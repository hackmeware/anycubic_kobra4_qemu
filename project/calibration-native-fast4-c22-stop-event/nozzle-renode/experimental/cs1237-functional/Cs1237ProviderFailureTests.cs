using System;
using Antmicro.Renode.Peripherals.Bus;
namespace Antmicro.Renode.Peripherals.NozzleExperimental
{
 public class Cs1237ProviderFailureTests : IBusPeripheral
 {
  public Cs1237ProviderFailureTests(Cs1237NativeGpio throwingPort,Cs1237NativeGpio rangePort,Cs1237FunctionalAdapter throwing,Cs1237FunctionalAdapter range)
  {ports=new[]{throwingPort,rangePort};sensors=new[]{throwing,range};}
  public void Reset(){}
  public void Prepare(){sensors[0].BindTimedSource(t=>{calls[0]++;throw new Exception("explicit-stale-history-test");});sensors[1].BindTimedSource(t=>{calls[1]++;return 8388608;});}
  private void Check(bool b,string s){if(!b)throw new Exception(s);checks++;}
  public string Finish()
  {
   for(int i=0;i<2;i++)
   {
    var s=sensors[i];Check(calls[i]==1 && s.ProviderCalls==1 && s.ProviderFailures==1,"failed provider called exactly once");Check(s.AdapterErrors==1 && s.AdapterError.StartsWith("Sensor provider failed:"),"original provider cause captured");string cause=s.AdapterError;
    for(int j=0;j<2;j++){bool rejected=false;try{s.ValidateSensorLevel();}catch(InvalidOperationException e){rejected=e.Message.Contains(cause);}Check(rejected,"invalid read retains original cause");}
    ports[i].WriteDoubleWord(12,0);Check(calls[i]==1,"GPIO callback cannot retry failed provider");Check(s.AdapterError==cause,"first cause remains sticky");Check(s.Protocol.ConversionCount==0,"bad provider cannot create a conversion");
   }
   return "CS1237 PROVIDER FAILURE TESTS PASS: "+checks;
  }
  private readonly Cs1237NativeGpio[] ports;private readonly Cs1237FunctionalAdapter[] sensors;private readonly int[] calls=new int[2];private int checks;
 }
}
