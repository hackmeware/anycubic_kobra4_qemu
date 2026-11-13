using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
namespace Antmicro.Renode.Peripherals.NozzleExperimental
{
 public class Cs1237BindingTests : IBusPeripheral
 {
  public Cs1237BindingTests(IMachine machine,Cs1237NativeGpio port,Cs1237FunctionalAdapter sensor,Cs1237FunctionalAdapter lab,Cs1237FunctionalAdapter timed)
  {this.machine=machine;this.port=port;this.sensor=sensor;this.lab=lab;this.timed=timed;}
  public void Reset(){}
  private void Check(bool v,string label){if(!v)throw new Exception(label);checks++;}
  private void Reject(Action a,string label){bool rejected=false;try{a();}catch(ArgumentException){rejected=true;}catch(InvalidOperationException){rejected=true;}Check(rejected,label);}
  public string RunAll()
  {
   Reject(()=>new Cs1237FunctionalAdapter(machine,port,0),"functional profile requires explicit opt-in");
   Reject(()=>sensor.BindTimedSource(null),"null bind rejected");Check(!sensor.TimedProviderBound && sensor.Source!=null,"failed bind retains explicit baseline");
   var deadline=sensor.Protocol.NextReadyNanoseconds;Func<long,int> provider=t=>77;sensor.BindTimedSource(provider);
   Check(sensor.TimedProviderBound && sensor.Source==null && sensor.TimedSource==provider,"one explicit replacement");Check(sensor.Protocol.NextReadyNanoseconds==deadline,"binding does not reset conversion readiness");
   Reject(()=>sensor.BindTimedSource(provider),"duplicate bind rejected");Reject(()=>sensor.Source=()=>0,"cannot replace exclusive source");Reject(()=>sensor.TimedSource=null,"cannot clear exclusive timed source");
   var original=lab.Source;lab.Source=()=>5;Reject(()=>lab.BindTimedSource(provider),"modified laboratory baseline protected");Check(lab.Source()==5 && !lab.TimedProviderBound,"lab source unchanged");
   lab.Source=original;Reject(()=>lab.BindTimedSource(provider),"source restore does not erase modification history");
   timed.TimedSource=t=>6;Reject(()=>timed.BindTimedSource(provider),"existing timed lab source protected");Check(timed.TimedSource(0)==6 && !timed.TimedProviderBound,"timed source unchanged");
   timed.TimedSource=null;Reject(()=>timed.BindTimedSource(provider),"clearing lab timed source does not erase modification history");
   return "CS1237 FUNCTIONAL BINDING TESTS PASS: "+checks;
  }
  private readonly IMachine machine;private readonly Cs1237NativeGpio port;private readonly Cs1237FunctionalAdapter sensor,lab,timed;private int checks;
 }
}
