// Experimental passive timer witness. No firmware writes or external input.
using System;
using System.IO;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.BootstrapExperiment
{
 public sealed class BoundaryProbe : IPeripheral
 {
  public BoundaryProbe(IMachine machine)
  {
   this.machine=machine;
   timer=new LimitTimer(machine.ClockSource,1000000,this,"bootstrap witness",100,
    direction:Direction.Ascending,workMode:WorkMode.Periodic,enabled:true,eventEnabled:true);
   timer.LimitReached+=()=>rows.Add(((ulong)machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds).ToString(System.Globalization.CultureInfo.InvariantCulture));
  }
  public void Export(string path)
  {
   if(!machine.IsPaused) throw new InvalidOperationException("Paused boundary required");
   File.WriteAllLines(path,rows);
  }
  public void Reset(){timer.Reset();rows.Clear();}
  readonly IMachine machine;
  readonly LimitTimer timer;
  readonly List<string> rows=new List<string>();
 }
}
