// Deterministic event-pump policy checks. Fake clock effects belong only to the test fixture.
using System;
using System.Collections.Generic;
using Antmicro.Renode.Peripherals.NozzleExperimental;
namespace Antmicro.Renode.Peripherals.PrinterExperimental
{
 public sealed class DeadlineSchedulerTests : IPeripheral
 {
  public void Reset(){}
  public string RunAll()
  {
   var f=new Fake{Next=10};var pump=f.Make();Check(pump.Run()&&f.Arms.Count==1&&f.Arms[0]==10&&f.Processed.Count==0,"future event stays future at exact interval");
   f=new Fake{Next=10};f.OnArm=delta=>{if(f.Arms.Count==1)f.Now=3;};pump=f.Make();Check(pump.Run()&&f.Arms.Count==2&&f.Arms[0]==10&&f.Arms[1]==7&&f.Next==10,"setter-time advance rearms remaining time without moving event");
   f=new Fake{Next=10};f.OnArm=delta=>{if(f.Arms.Count==1)f.Now=12;};pump=f.Make();Check(pump.Run()&&f.Processed.Count==1&&f.Processed[0]==10&&f.Arms[1]==8,"event becoming due while arming is drained at original deadline");
   f=new Fake{Next=10,Now=25};pump=f.Make();Check(pump.Run()&&f.Processed.Count==2&&f.Processed[0]==10&&f.Processed[1]==20&&f.Arms[0]==5,"multiple due events retain order and future interval");
   f=new Fake{Next=0,Now=1,Protocol=0};pump=f.Make();Check(!pump.Run()&&f.Error.Contains("Non-advancing")&&f.Advances==0,"nonadvancing deadline fails rather than looping");
   f=new Fake{Next=5,Now=10};f.OnAdvance=value=>{};pump=f.Make();Check(!pump.Run()&&f.Error.Contains("failed to advance")&&f.Advances==1,"unconsumed due event fails closed");
   f=new Fake{Next=1000000};f.OnArm=delta=>f.Now++;pump=f.Make();Check(!pump.Run()&&pump.NonConvergenceErrors==1&&f.Arms.Count==128&&f.Error.Contains("128"),"persistent setter reentry bounded at128 attempts");
   int before=f.Arms.Count;Check(!pump.Run()&&f.Arms.Count==before&&f.Errors==1,"nonconvergence remains fail-stop without retry");
   f=new Fake{Next=10};f.OnArm=delta=>f.Now=-1;pump=f.Make();Check(!pump.Run()&&f.Error.Contains("backwards"),"clock rollback is not repaired by rearming");
   f=new Fake{Next=10,Now=0,Protocol=1};pump=f.Make();Check(!pump.Run()&&f.Error.Contains("ahead"),"future protocol state rejected");
   f=new Fake{Next=10,Now=10};f.OnAdvance=value=>{f.Faulted=true;f.Error="source failed";f.Errors++;};pump=f.Make();Check(!pump.Run()&&f.Errors==1&&f.Error=="source failed"&&f.Arms.Count==0,"source error is not retried or overwritten");
   return "CS1237 DEADLINE SCHEDULER TESTS PASS: "+checks;
  }
  private sealed class Fake
  {
   public long Now,Protocol,Next;public bool Faulted;public string Error="";public int Errors,Advances;
   public readonly List<long> Arms=new List<long>(),Processed=new List<long>();public Action<long> OnArm,OnAdvance;
   public Cs1237DeadlineScheduler Make(){return new Cs1237DeadlineScheduler(()=>Now,()=>Protocol,()=>Next,()=>Faulted,()=>{},
    at=>{Advances++;if(OnAdvance!=null){OnAdvance(at);return;}while(Next<=at){Processed.Add(Next);Next+=10;}Protocol=at;},()=>{},
    delta=>{Arms.Add(delta);if(OnArm!=null)OnArm(delta);},reason=>{Faulted=true;Error=reason;Errors++;});}
  }
  private void Check(bool value,string reason){checks++;if(!value)throw new Exception(reason);}
  private int checks;
 }
}
