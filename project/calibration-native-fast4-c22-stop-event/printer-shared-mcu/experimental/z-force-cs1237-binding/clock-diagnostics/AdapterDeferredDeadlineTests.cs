// CPU-free fault injection: defer a real timer callback exactly as the adapter's reentrancy guard does.
// Reflection touches only the test adapter guard, not clock, protocol deadlines, firmware or mechanics.
using System;
using System.Collections.Generic;
using System.Reflection;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.NozzleExperimental;
namespace Antmicro.Renode.Peripherals.PrinterExperimental
{
 public sealed class AdapterDeferredDeadlineTests : IPeripheral
 {
  public AdapterDeferredDeadlineTests(IMachine machine)
  {
   this.machine=machine;port=new Cs1237NativeGpio(machine);sensor=new Cs1237FunctionalAdapter(machine,port,-7,idealizedElectricalSemantics:true);
   sensor.BindTimedSource(at=>{if(at>(long)machine.ClockSource.CurrentValue.TotalNanoseconds)throw new Exception("Future provider call");candidates.Add(at);return -7;});
   updating=typeof(Cs1237FunctionalAdapter).GetField("updating",BindingFlags.NonPublic|BindingFlags.Instance);
   schedule=typeof(Cs1237FunctionalAdapter).GetMethod("Schedule",BindingFlags.NonPublic|BindingFlags.Instance);
   updating.SetValue(sensor,true);
  }
  public void Reset(){}
  public string CompleteConversion(bool expectSuccess)
  {
   long before=(long)machine.ClockSource.CurrentValue.TotalNanoseconds;
   Check(before==302000100,"real clock at100ns after first conversion deadline");
   Check(sensor.SuppressedTicks==1,"one real timer callback suppressed by existing guard");
   Check(sensor.Protocol.ConversionCount==0&&candidates.Count==0,"deferred callback did not fabricate a conversion");
   schedule.Invoke(sensor,null);updating.SetValue(sensor,false);
   Check((long)machine.ClockSource.CurrentValue.TotalNanoseconds==before,"rearming does not advance time");
   if(!expectSuccess){Check(sensor.AdapterError.Contains("Non-future sensor deadline")&&sensor.ProviderCalls==0,"old scheduler loses deferred real conversion");return "ADAPTER DEFERRED DEADLINE EXPECTED PRE-FIX FAILURE: "+checks;}
   Check(sensor.AdapterErrors==0,"deferred conversion is processed, not faulted or moved");
   Check(sensor.Protocol.ConversionCount==1&&candidates.Count==1&&candidates[0]==302000000,"original candidate deadline delivered exactly once");
   Check(sensor.Protocol.LastLatchedSignedCode==-7,"actual candidate value latched");
   Check(sensor.Protocol.NextReadyNanoseconds==402000000,"next conversion remains phase-locked to original deadline");
   return "ADAPTER DEFERRED CONVERSION TEST PASS: "+checks;
  }
  public string BeginDeferredBit()
  {
   Check(candidates.Count==2&&candidates[1]==402000000,"next scheduled conversion fires exactly once at original phase");
   port.WriteDoubleWord(0,0x44244444);port.WriteDoubleWord(16,32);
   bitAt=(long)machine.ClockSource.CurrentValue.TotalNanoseconds;
   Check(sensor.Protocol.ClockCount==1&&sensor.AdapterErrors==0,"real first output bit scheduled");
   updating.SetValue(sensor,true);return "ADAPTER DEFERRED BIT PREPARED";
  }
  public string CompleteBit(string tracePath)
  {
   long before=(long)machine.ClockSource.CurrentValue.TotalNanoseconds;
   Check(before==bitAt+600,"real clock600ns after rising edge");
   Check(sensor.Protocol.NextEventNanoseconds==bitAt+228,"original invalidation deadline remains pending; actual="+sensor.Protocol.NextEventNanoseconds+" bitAt="+bitAt+" device="+sensor.Protocol.DeviceDout);
   schedule.Invoke(sensor,null);updating.SetValue(sensor,false);
   Check(sensor.AdapterErrors==0&&!sensor.Protocol.OutputTransition&&sensor.Protocol.DeviceDout==true,"invalidation and500ns valid output both drained");
   Check(candidates.Count==2,"bit drain adds no provider/conversion call");
   Check((long)machine.ClockSource.CurrentValue.TotalNanoseconds==before,"bit drain advances no clock");
   sensor.WriteTrace(tracePath);
   string trace=System.IO.File.ReadAllText(tracePath);
   Check(trace.Contains((bitAt+228)+",deadline,")&&trace.Contains((bitAt+500)+",deadline,"),"trace retains both original event timestamps");
   port.WriteDoubleWord(16,32u<<16);
   Check(sensor.Protocol.NextReadyNanoseconds==502000000,"bit scheduling does not move conversion cadence");
   return "ADAPTER DEFERRED BIT TEST PASS: "+checks;
  }
  private void Check(bool value,string reason){checks++;if(!value)throw new Exception(reason);}
  private readonly IMachine machine;private readonly Cs1237NativeGpio port;private readonly Cs1237FunctionalAdapter sensor;
  private readonly FieldInfo updating;private readonly MethodInfo schedule;private readonly List<long> candidates=new List<long>();private int checks;private long bitAt;
 }
}
