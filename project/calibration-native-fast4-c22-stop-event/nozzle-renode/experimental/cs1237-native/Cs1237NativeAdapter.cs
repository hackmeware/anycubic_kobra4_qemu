// SPDX-License-Identifier: MIT
// EXPLICIT experimental electrical fixture. Only PA6 is driven; never PA7/PB2.
using System;
using System.IO;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.NozzleExperimental
{
 public class Cs1237NativeAdapter : IBusPeripheral
 {
  public Cs1237NativeAdapter(IMachine machine,Cs1237NativeGpio port,int syntheticBaseline,long outputDelayNanoseconds=500,bool allowHostPriorityOverlap=false)
  {
   this.port=port;Source=()=>syntheticBaseline;
   protocol=new Cs1237NativeProtocol(outputDelayNanoseconds,allowHostPriorityOverlap);
   protocol.SetSyntheticCode(syntheticBaseline);
   deadline=new LimitTimer(machine.ClockSource,1000000000,this,"CS1237 deadline",ulong.MaxValue,direction:Direction.Ascending,workMode:WorkMode.OneShot,enabled:false,eventEnabled:true);
   deadline.LimitReached+=Tick;port.Access+=Access;port.BeforeRead=BeforeRead;
   ApplyOutput();Schedule();Record("power-on");
  }
  // Explicit externally supplied laboratory sensor source. Invoked at real conversion deadlines.
  // Force/geometry mapping belongs to a separate fixture and is NOT implemented here.
  public Func<int> Source {get;set;}
  // A future dynamic source must resolve this timestamp in the ADC clock domain;
  // a present-state force getter is not a historical/cross-machine time mapping.
  public Func<long,int> TimedSource {get;set;}
  public Cs1237NativeProtocol Protocol {get{return protocol;}}
  public long AdapterErrors {get;private set;}
  public string AdapterError {get;private set;}
  public long ResetObservations {get;private set;}
  public long Dropped {get;private set;}
  public void Reset(){ResetObservations++;} // MCU reset is not sensor power loss.
  public void WriteTrace(string path){File.WriteAllText(path,"ns,event,ready,clock,config,host,device,transition,pa5,pa6,pa7,conversions,reads,writes,protocol_errors,overlaps,adapter_errors,error\n"+String.Join("\n",rows)+"\n");}
  public void WriteStatus(string path)
  {
   File.WriteAllText(path,"{\"now_ns\":"+port.Nanoseconds+",\"config\":"+protocol.Config+",\"conversions\":"+protocol.ConversionCount+",\"read_words\":"+protocol.ReadWordCount+",\"config_writes\":"+protocol.ConfigWrites+",\"protocol_errors\":"+protocol.Errors+",\"host_priority_overlap_observations\":"+protocol.HostPriorityOverlapObservations+",\"adapter_errors\":"+AdapterErrors+",\"dropped\":"+Dropped+",\"last_error\":\""+Clean(protocol.LastError)+"\",\"adapter_error\":\""+Clean(AdapterError)+"\",\"pa7_written_by_adapter\":false,\"main_pb2_connected\":false}\n");
  }
  private void Advance(long now)
  {
   // Process each true model deadline separately, sampling the provider only when
   // the ADC is about to latch a new conversion, never at a host read or requested motion.
   while(protocol.NextEventNanoseconds<=now)
   {
    var at=protocol.NextEventNanoseconds;
    if(at==protocol.NextReadyNanoseconds)
    {if(Source==null && TimedSource==null)protocol.RemoveSyntheticSource();else
     {try{protocol.SetSyntheticCode(TimedSource!=null?TimedSource(at):Source());}catch(Exception e){Error("Sensor provider failed: "+e.Message);return;}}}
    protocol.AdvanceTo(at);ApplyOutput();Record("deadline");
   }
   protocol.AdvanceTo(now);
  }
  private void Access(long now,uint offset,uint value,uint config,uint latch)
  {
   if(updating)return;updating=true;
   try
   {
    Advance(now);if(AdapterErrors!=0)return;var mode=(config>>24)&15;bool? host=null;
    if((mode&3)!=0)
    {
     var fn=mode>>2;
     if(fn>=2){Error("Unsupported PA6 alternate function ownership");return;}
     if(fn!=1 || (latch&64)==0)host=(latch&64)!=0;
    }
    protocol.SetHostDout(host,now);
    var sclkMode=(config>>20)&15;
    bool sclk=(port.Snapshot(8)&32)!=0;
    if(((sclkMode&3)==0 && sclk) || ((sclkMode&3)!=0 && (sclkMode>>2)!=0)){Error("SCLK not driven as a digital output");return;}
    protocol.SetSclk(sclk,now);ApplyOutput();Schedule();Record("host-access");
   }
   finally{updating=false;}
  }
  private void BeforeRead(long offset)
  {
   if(offset!=8 || updating || !port.IsNativeSensorRead)return;
   updating=true;
   try
   {
    Advance(port.Nanoseconds);ApplyOutput();Schedule();Record("native-sample");
    ValidateSensorLevel();
   }
   finally{updating=false;}
  }
  public bool ValidateSensorLevel()
  {
   if(AdapterErrors!=0 || ((port.Snapshot(0)>>24)&3)!=0 || ((port.Snapshot(0)>>24)&15)==0 || protocol.HostDout.HasValue || !protocol.DeviceDout.HasValue || protocol.ProtocolFault || protocol.OutputTransition || !protocol.ResolvedDout.HasValue)
   {Error("Native sensor read has no valid electrical level");throw new InvalidOperationException(AdapterError+": "+protocol.LastError);}
   return protocol.ResolvedDout.Value;
  }
  private void Tick(){if(updating)return;updating=true;try{Advance(port.Nanoseconds);ApplyOutput();Schedule();}finally{updating=false;}}
  private void ApplyOutput()
  {
   if(protocol.ProtocolFault || AdapterErrors!=0){port.ReleasePin(6);return;}
   // A Boolean GPIO cannot encode an unknown transition. Retain the last stable
   // pad while marking it invalid and rejecting any native read during transition.
   // No interrupt edge is invented for the indeterminate interval.
   if(protocol.OutputTransition)return;
   if(protocol.DeviceDout.HasValue)port.OnGPIO(6,protocol.DeviceDout.Value);else port.ReleasePin(6);
  }
  private void Schedule()
  {
   deadline.Enabled=false;var at=protocol.NextEventNanoseconds;
   if(at==long.MaxValue || AdapterErrors!=0)return;
   var delta=at-port.Nanoseconds;
   if(delta<=0){Error("Non-future sensor deadline");return;}
   deadline.Limit=(ulong)delta;deadline.Value=0;deadline.Enabled=true;
  }
  private void Error(string message){AdapterErrors++;AdapterError=message;deadline.Enabled=false;port.ReleasePin(6);Record("adapter-error");}
  private static string Level(bool? b){return b.HasValue?(b.Value?"1":"0"):"unknown";}
  private static string Clean(string s){return (s??"").Replace('"','\'').Replace('\\','/').Replace(',',';').Replace('\n',' ');}
  private void Record(string why)
  {
   if(rows.Count>=200000){Dropped++;return;}
   uint pads=port.Snapshot(8);
   rows.Add(String.Join(",",new[]{protocol.Now.ToString(),why,protocol.Ready?"1":"0",protocol.ClockCount.ToString(),protocol.Config.ToString(),Level(protocol.HostDout),Level(protocol.DeviceDout),protocol.OutputTransition?"1":"0",((pads>>5)&1).ToString(),((pads>>6)&1).ToString(),((pads>>7)&1).ToString(),protocol.ConversionCount.ToString(),protocol.ReadWordCount.ToString(),protocol.ConfigWrites.ToString(),protocol.Errors.ToString(),protocol.HostPriorityOverlapObservations.ToString(),AdapterErrors.ToString(),Clean(protocol.LastError)}));
  }
  private readonly Cs1237NativeGpio port;private readonly Cs1237NativeProtocol protocol;private readonly LimitTimer deadline;
  private bool updating;private readonly List<string> rows=new List<string>();
 }
}
