// SPDX-License-Identifier: MIT
// Passive shared-MCU virtual-time telemetry. Never reads or modifies firmware state.
using System;
using System.Globalization;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.PrinterShared
{
 public sealed class VirtualTimeTelemetry : IPeripheral
 {
  public VirtualTimeTelemetry(IMachine machine, uint periodMicroseconds=10000)
  {
   if(periodMicroseconds==0) throw new ArgumentOutOfRangeException("periodMicroseconds");
   this.machine=machine;
   timer=new LimitTimer(machine.ClockSource,1000000,this,"shared virtual-time telemetry",periodMicroseconds,
    direction:Direction.Ascending,workMode:WorkMode.Periodic,enabled:false,eventEnabled:true);
   timer.LimitReached+=Publish;
  }
  public void Enable(string path)
  {
   if(String.IsNullOrWhiteSpace(path)||!Path.IsPathRooted(path)) throw new ArgumentException("Absolute telemetry output path required");
   Stop(); output=Path.GetFullPath(path); temporary=output+"."+Guid.NewGuid().ToString("N")+".tmp";
   epoch=Guid.NewGuid().ToString("N");sequence=0;previous=0;hasStep=false;stepPath=null;LastError="";
   timer.Value=0;timer.Enabled=true;Publish();
  }
  public void Stop() { if(timer.Enabled) { timer.Enabled=false;Publish(); } }
  public void Reset()
  {
   bool active=timer.Enabled;timer.Reset();timer.Value=0;timer.Enabled=active;
   epoch=Guid.NewGuid().ToString("N");sequence=0;previous=0;hasStep=false;stepPath=null;
   if(output!=null) Publish();
  }
  public bool Enabled=>timer.Enabled;
  public string LastError { get; private set; }="";
  public ulong Sequence=>sequence;
  public ulong LastNanoseconds=>previous;
  public void Publish()
  {
   if(output==null) return;
   try
   {
    ulong now=(ulong)machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds;
    bool backwards=sequence>0&&now<previous;
    if(backwards) epoch=Guid.NewGuid().ToString("N");
    previous=now;sequence++;
    string json="{\"schema\":1,\"source\":\"renode-shared-mcu\",\"virtual_time_ns\":"+now.ToString(CultureInfo.InvariantCulture)
      +",\"sequence\":"+sequence.ToString(CultureInfo.InvariantCulture)+",\"epoch\":\""+epoch+"\",\"enabled\":"+(timer.Enabled?"true":"false")
      +",\"time_went_backwards\":"+(backwards?"true":"false")+"}\n";
    File.WriteAllText(temporary,json);
    if(File.Exists(output)) File.Replace(temporary,output,null); else File.Move(temporary,output);
   }
   catch(Exception e)
   {
    timer.Enabled=false;LastError=e.Message;
    this.Log(LogLevel.Error,"Virtual-time telemetry stopped: {0}",e.Message);
    throw;
   }
  }
  // Explicit lockstep acknowledgement. The monitor invokes this only AFTER
  // emulation RunFor returns; no time, firmware register or CPU state is changed.
  public void PublishStep(string path, long stepId)
  {
   if(stepId<0 || String.IsNullOrWhiteSpace(path) || !Path.IsPathRooted(path))
    throw new ArgumentException("Absolute step acknowledgement path and nonnegative id required");
   if(!timer.Enabled) throw new InvalidOperationException("Virtual-time telemetry is disabled");
   if(!machine.IsPaused) throw new InvalidOperationException("Step acknowledgement requires paused machine");
   if((!hasStep && stepId!=0) || (hasStep && stepId!=lastStep+1))
    throw new InvalidOperationException("Step acknowledgement id is not sequential");
   string target=Path.GetFullPath(path);
   if(stepPath!=null && stepPath!=target) throw new InvalidOperationException("Step acknowledgement path changed");
   ulong now=(ulong)machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds;
   if((hasStep && now<lastStepTime) || now<previous)
    throw new InvalidOperationException("Step virtual time moved backwards");
   string temp=target+"."+Guid.NewGuid().ToString("N")+".tmp";
   try
   {
    string json="{\"schema\":1,\"source\":\"renode-shared-mcu-step\",\"step_id\":"+stepId.ToString(CultureInfo.InvariantCulture)
     +",\"virtual_time_ns\":"+now.ToString(CultureInfo.InvariantCulture)+",\"epoch\":\""+epoch
     +"\",\"enabled\":true,\"paused\":true,\"time_went_backwards\":false}\n";
    File.WriteAllText(temp,json);
    if(File.Exists(target)) File.Replace(temp,target,null); else File.Move(temp,target);
    hasStep=true;lastStep=stepId;lastStepTime=now;stepPath=target;
   }
   catch(Exception e)
   {
    timer.Enabled=false;LastError=e.Message;
    this.Log(LogLevel.Error,"Virtual-time step acknowledgement failed: {0}",e.Message);
    throw;
   }
  }
  private bool hasStep;
  private long lastStep;
  private ulong lastStepTime;
  private string stepPath;
  private readonly IMachine machine;
  private readonly LimitTimer timer;
  private string output,temporary,epoch=Guid.NewGuid().ToString("N");
  private ulong sequence,previous;
 }
}
