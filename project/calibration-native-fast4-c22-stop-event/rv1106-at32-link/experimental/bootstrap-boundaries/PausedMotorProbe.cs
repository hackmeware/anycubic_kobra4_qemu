// Offline-reviewed experimental observer, installed only after the 20 ms ack.
// Reads two existing IMachine properties; never advances or configures a machine.
using System;
using System.Globalization;
using System.IO;
using Antmicro.Renode.Core;
namespace Antmicro.Renode.Peripherals.BootstrapExperiment
{
 public sealed class PausedMotorProbe : IPeripheral
 {
  public PausedMotorProbe(IMachine machine) { this.machine=machine; }
  public void Reset() { }
  public void Export(string path, string board, string phase)
  {
   if(String.IsNullOrWhiteSpace(path)||!Path.IsPathRooted(path))
    throw new ArgumentException("Absolute fence path required");
   if(board!="main" && board!="nozzle" && board!="motor")
    throw new ArgumentException("Unknown board label");
   if(nextPhase>=phases.Length || phase!=phases[nextPhase])
    throw new InvalidOperationException("Unexpected fence phase or duplicate export");
   if(boardName!=null && boardName!=board)
    throw new InvalidOperationException("Board label changed");
   bool pausedBefore=machine.IsPaused;
   ulong before=(ulong)machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds;
   ulong after=(ulong)machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds;
   bool pausedAfter=machine.IsPaused;
   string json="{\"schema\":1,\"source\":\"paused-motor-probe\",\"board\":\""+board
    +"\",\"phase\":\""+phase+"\",\"phase_index\":"+nextPhase.ToString(CultureInfo.InvariantCulture)
    +",\"paused_before\":"+(pausedBefore?"true":"false")
    +",\"local_time_before_ns\":"+before.ToString(CultureInfo.InvariantCulture)
    +",\"local_time_after_ns\":"+after.ToString(CultureInfo.InvariantCulture)
    +",\"paused_after\":"+(pausedAfter?"true":"false")+"}\n";
   string target=Path.GetFullPath(path);
   string temporary=target+"."+Guid.NewGuid().ToString("N")+".tmp";
   File.WriteAllText(temporary,json);
   File.Move(temporary,target); // Same-directory atomic publication; no overwrite.
   boardName=board;
   nextPhase++;
  }
  private readonly IMachine machine;
  private readonly string[] phases={"before-a","between-a-b","after-b","before-existing","after-existing"};
  private string boardName;
  private int nextPhase;
 }
}
