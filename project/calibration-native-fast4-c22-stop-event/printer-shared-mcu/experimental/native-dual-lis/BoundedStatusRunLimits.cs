using System;
using System.Globalization;
namespace Antmicro.Renode.Peripherals.SensorCrossBoard
{
 public sealed class BoundedStatusRunLimits
 {
  public BoundedStatusRunLimits(ulong seconds)
  {
   if(seconds<1 || seconds>86400)throw new ArgumentOutOfRangeException("seconds","Shared stop seconds must be 1..86400.");
   StopSeconds=seconds;StopNanoseconds=checked(seconds*1000000000UL);
   StatusWriteLimit=checked((seconds+1)*100+10);
  }
  public readonly ulong StopSeconds,StopNanoseconds,StatusWriteLimit;
  static string N(ulong n){return n.ToString(CultureInfo.InvariantCulture);}
  public string Json {get{return "{\"schema\":1,\"shared_stop_seconds\":"+N(StopSeconds)+",\"shared_stop_ns\":"+N(StopNanoseconds)+",\"status_interval_ns\":10000000,\"status_write_limit\":"+N(StatusWriteLimit)+",\"cleanup_reserve_writes\":110,\"maximum_shared_stop_seconds\":86400}";}}
 }
}
