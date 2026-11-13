// Passive clock reads inside an ordinary fractional timer callback. No CPUs or firmware.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.PrinterExperimental
{
 public sealed class ClockDomainProbe : IPeripheral
 {
  public ClockDomainProbe(IMachine machine)
  {
   this.machine=machine;
   stamp=new LimitTimer(machine.ClockSource,1000000000,this,"monotonic stamp",ulong.MaxValue,direction:Direction.Ascending,enabled:true,eventEnabled:false);
   alarm=new LimitTimer(machine.ClockSource,1000000000,this,"fractional alarm",1234,direction:Direction.Ascending,workMode:WorkMode.OneShot,enabled:true,eventEnabled:true);
   alarm.LimitReached+=()=>{Calls++;Stamp=stamp.Value;Clock=machine.ClockSource.CurrentValue.TotalNanoseconds;Elapsed=machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds;};
  }
  public string Report()
  {
   if(Calls!=1||Stamp!=1234||Clock!=1234)throw new Exception("Unexpected callback count/peripheral clock");
   return "CLOCK DOMAIN CALLBACK: calls="+Calls+" stamp_ns="+Stamp+" clock_source_ns="+Clock+" machine_elapsed_ns="+Elapsed;
  }
  public void Reset(){}
  public int Calls{get;private set;} public ulong Stamp{get;private set;} public ulong Clock{get;private set;} public ulong Elapsed{get;private set;}
  private readonly IMachine machine;private readonly LimitTimer stamp,alarm;
 }
}
