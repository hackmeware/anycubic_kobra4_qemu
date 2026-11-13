// SPDX-License-Identifier: MIT
// Production composition: public references and read-only status only.
using System;
using System.Globalization;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Time;
using Antmicro.Renode.Peripherals.PrinterMotor;
using MainGpio=Antmicro.Renode.Peripherals.PrinterMain.AT32GPIO;
using NozzleGpio=Antmicro.Renode.Peripherals.PrinterNozzle.AT32GPIO;
namespace Antmicro.Renode.Peripherals.SensorCrossBoard
{
 public sealed class NativeDualSensorAttachment : IPeripheral, IDisposable
 {
  public const string Hypothesis="rigid-xy39-mainY-nozzleX-proper-rotation-v1";
  public NativeDualSensorAttachment(IMachine machine,string hypothesis)
  {
   if(hypothesis!=Hypothesis)throw new ArgumentException("Explicit supported hypothetical mechanical mapping required.");
   emulation=EmulationManager.Instance.CurrentEmulation;master=emulation.MasterTimeSource;
   main=emulation["main"];nozzle=emulation["nozzle"];motor=emulation["motor"];
   if(!Object.ReferenceEquals(machine,main))throw new ArgumentException("Register attachment on actual main machine.");
   Binding=new DualBoardSensorBinding(main,(MainGpio)main["sysbus.gpioB"],nozzle,(NozzleGpio)nozzle["sysbus.gpioB"],
     (GenericStepperElectromechanical)motor["sysbus.electromechanicalPlant"],(AT32Timer)motor["sysbus.tmr8"],Mapping(1),Mapping(0));
   master.SyncHook+=Observe;subscribed=true;
   foreach(var m in new[]{main,nozzle,motor})m.StateChanged+=OnMachineState;
  }
  public DualBoardSensorBinding Binding {get;private set;}
  public bool IsDisposed {get;private set;}
  public string Fault {get {return fault ?? Binding.Publisher.Fault ?? Binding.MainInput.Fault ?? Binding.NozzleInput.Fault ?? Binding.MainSensor.SourceFault ?? Binding.NozzleSensor.SourceFault;}}
  public ulong StatusWrites {get;private set;}
  public void Reset(){} // Never erase an already observed source/acquisition fault.
  static RigidTranslationConfiguration Mapping(int axis)
  {
   var j=new double[3,1];j[axis,0]=0.039/(2*Math.PI);
   return new RigidTranslationConfiguration(new[]{axis},j,new double[,]{{0,1,0},{1,0,0},{0,0,-1}},new[]{0.0,0.0,-9.80665},9.80665,624999,625000);
  }
  // Configure once, while paused, before any status publication or execution.
  public void ConfigureRunLimit(ulong stopSeconds)
  {
   Binding.Publisher.RequirePaused();
   if(limitsConfigured || output!=null || StatusWrites!=0 || IsDisposed || master.ElapsedVirtualTime.TotalNanoseconds!=0)
    throw new InvalidOperationException("Run limit must be configured once before time advances or status starts.");
   limits=new BoundedStatusRunLimits(stopSeconds);limitsConfigured=true;
  }
  public void StartStatus(string path)
  {
   Binding.Publisher.RequirePaused();
   if(output!=null || IsDisposed || !Path.IsPathRooted(path))throw new InvalidOperationException("One absolute status target before execution required.");
   output=Path.GetFullPath(path);temporary=output+"."+Guid.NewGuid().ToString("N")+".tmp";
   if(File.Exists(output))throw new InvalidOperationException("Fresh status output required.");
   WriteStatus(output);
  }
  void Observe(TimeInterval t)
  {
   if(IsDisposed)return;
   if(!master.IsOnSyncPhaseThread)throw new InvalidOperationException("LIS status observation requires common sync phase.");
   var now=t.TotalNanoseconds;
   if(Fault!=null)
   {
    if(fault==null)fault=Fault;
    if(output!=null)WriteStatus(output);
    this.Log(LogLevel.Error,"LIS2DW12 source/acquisition fault: {0}",fault);
    throw new InvalidOperationException("LIS2DW12 source/acquisition fault: "+fault);
   }
   if(output!=null && now>=nextStatus){WriteStatus(output);nextStatus=checked(now+10000000);}
  }
  public void WriteStatus(string path)
  {
   if(IsDisposed || !Path.IsPathRooted(path))throw new ArgumentException("Live attachment and absolute status target required.");
   if(StatusWrites>=limits.StatusWriteLimit)throw new InvalidOperationException("Bounded LIS status publication limit reached.");
   ulong now=master.ElapsedVirtualTime.TotalNanoseconds;
   string body="{\"schema\":1,\"source\":\"native-dual-lis-public-status\",\"virtual_time_ns\":"+N(now)
    +",\"run_limits\":"+limits.Json
    +",\"sequence\":"+N(StatusWrites+1)+",\"hypothesis\":"+Q(Hypothesis)+",\"disposed\":"+B(IsDisposed)
    +",\"fault\":"+Q(Fault)+",\"source_captures\":"+N(Binding.Publisher.Captures)
    +",\"published_pairs\":"+N(Binding.Publisher.PublishedPairs)+",\"last_source_ns\":"+(Binding.Publisher.LastCapturedTime.HasValue?N(Binding.Publisher.LastCapturedTime.Value):"null")
    +",\"superseded_pairs\":"+N(Binding.Publisher.SupersededUnpublishedPairs)
    +",\"main\":"+Sensor(Binding.MainSensor,Binding.MainInput)+",\"nozzle\":"+Sensor(Binding.NozzleSensor,Binding.NozzleInput)
    +",\"original_host_acquisition_proven\":false,\"calibration_complete\":false,\"physical_fidelity_proven\":false}\n";
   string temp=path==output?temporary:path+"."+Guid.NewGuid().ToString("N")+".tmp";
   File.WriteAllText(temp,body);
   if(File.Exists(path))File.Replace(temp,path,null);else File.Move(temp,path);
   StatusWrites++;
  }
  static string Sensor(TimedLis2dw12 s,PublishedSnapshotAccelerationInput i)
  {
   // Configuration getters do not acknowledge, pop or consume data/FIFO state.
   return "{\"ready\":"+B(i.HasValue)+",\"input_fault\":"+Q(i.Fault)+",\"sensor_fault\":"+Q(s.SourceFault)
    +",\"generated_samples\":"+N(s.GeneratedSamples)+",\"consumed_source_samples\":"+N(i.OutputSamples)
    +",\"last_sample_ns\":"+N(s.LastSampleNanoseconds)+",\"last_acquisition_ns\":"+N(i.LastAcquisitionNanoseconds)
    +",\"last_source_ns\":"+N(i.LastSourceNanoseconds)+",\"previous_source_ns\":"+N(i.PreviousSourceNanoseconds)
    +",\"source_age_ns\":"+N(i.LastSourceAgeNanoseconds)+",\"derivative_interval_ns\":"+N(i.LastDerivativeIntervalNanoseconds)
    +",\"last_publication_ns\":"+N(i.LastPublicationNanoseconds)+",\"sampling\":"+B(s.IsSampling)
    +",\"fifo_count\":"+s.FifoCount+",\"overwritten_samples\":"+N(s.OverwrittenSamples)+",\"ctrl1\":"+s.ReadRegister(0x20)
    +",\"ctrl2\":"+s.ReadRegister(0x21)+",\"ctrl6\":"+s.ReadRegister(0x25)+",\"fifo_ctrl\":"+s.ReadRegister(0x2e)+"}";
  }
  public void Close(string path){Binding.Publisher.RequirePaused();WriteStatus(path);Dispose();File.WriteAllText(path+".cleanup.json","{\"schema\":1,\"disposed\":true,\"binding_disposed\":"+B(Binding.IsDisposed)+",\"publisher_connected\":"+B(Binding.Publisher.IsConnected)+",\"publisher_subscribed\":"+B(Binding.Publisher.IsSubscribed)+",\"main_input_subscribed\":"+B(Binding.MainInput.IsSubscribed)+",\"nozzle_input_subscribed\":"+B(Binding.NozzleInput.IsSubscribed)+"}\n");}
  public void Dispose()
  {
   if(IsDisposed)return;
   Binding.Publisher.RequirePaused();Binding.Dispose();
   if(subscribed){master.SyncHook-=Observe;subscribed=false;}
   foreach(var m in new[]{main,nozzle,motor})m.StateChanged-=OnMachineState;
   IsDisposed=true;
  }
  void OnMachineState(IMachine m,MachineStateChangedEventArgs a){if(a.CurrentState==MachineStateChangedEventArgs.State.Disposed)Dispose();}
  static string N(ulong n){return n.ToString(CultureInfo.InvariantCulture);}
  static string B(bool b){return b?"true":"false";}
  static string Q(string s){if(s==null)return "null";return "\""+s.Replace("\\","\\\\").Replace("\"","\\\"").Replace("\n","\\n").Replace("\r","\\r").Replace("\t","\\t")+"\"";}
  readonly Emulation emulation;readonly MasterTimeSource master;readonly IMachine main,nozzle,motor;
  BoundedStatusRunLimits limits=new BoundedStatusRunLimits(719);bool limitsConfigured;
  string output,temporary,fault;ulong nextStatus=10000000;bool subscribed;
 }
}
