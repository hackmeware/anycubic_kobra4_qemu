// Negative temporal assertions for exact peripheral-clock provenance; no clock mutation.
using System;
namespace Antmicro.Renode.Peripherals.PrinterExperimental
{
 public sealed class ConsumerClockGuardTests : IPeripheral
 {
  public void Reset(){}
  public string RunAll()
  {
   var guard=new ZConsumerClockGuard();
   guard.Validate(1234,1234,1234);Check(true,"fractional callback exact peripheral clock accepted");
   // Published machine boundary2000 is deliberately not an input to peripheral-clock provenance.
   guard.Validate(1234,2000,2000);Check(true,"same past candidate accepted after ordinary clock advance");
   guard.Validate(1999,2000,2000);Check(true,"past candidate checked independently of callback now");
   Reject(()=>new ZConsumerClockGuard().Validate(1234,1235,1234),"port1ns ahead rejected");
   Reject(()=>new ZConsumerClockGuard().Validate(1234,1233,1234),"port1ns behind rejected");
   Reject(()=>new ZConsumerClockGuard().Validate(1235,1234,1234),"candidate1ns future rejected despite possible later scheduler boundary");
   Reject(()=>new ZConsumerClockGuard().Validate(-1,0,0),"negative candidate rejected");
   Reject(()=>new ZConsumerClockGuard().Validate(0,-1,-1),"negative peripheral time rejected");
   Reject(()=>guard.Validate(1900,1999,1999),"peripheral-clock rollback rejected");
   return "Z CONSUMER CLOCK GUARD TESTS PASS: "+checks;
  }
  private void Check(bool value,string reason){checks++;if(!value)throw new Exception(reason);}
  private void Reject(Action action,string reason){bool rejected=false;try{action();}catch(InvalidOperationException){rejected=true;}Check(rejected,reason);}
  private int checks;
 }
}
