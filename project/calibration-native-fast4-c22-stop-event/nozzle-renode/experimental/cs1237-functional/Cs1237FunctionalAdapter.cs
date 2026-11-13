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
 public class Cs1237FunctionalAdapter : IBusPeripheral
 {
  public Cs1237FunctionalAdapter(IMachine machine,Cs1237NativeGpio port,int syntheticBaseline,long outputDelayNanoseconds=500,bool idealizedElectricalSemantics=false,int maximumTraceRows=200000)
  {
   if(maximumTraceRows<1||maximumTraceRows>2000000)throw new ArgumentOutOfRangeException("maximumTraceRows");
   this.maximumTraceRows=maximumTraceRows;
   if(!idealizedElectricalSemantics)throw new ArgumentException("Explicit idealizedElectricalSemantics=true is required; use strict adapter otherwise");
   this.machine=machine;this.port=port;baselineSource=()=>syntheticBaseline;source=baselineSource;
   protocol=new Cs1237FunctionalProtocol(outputDelayNanoseconds);
   protocol.SetSyntheticCode(syntheticBaseline);
   deadline=new LimitTimer(machine.ClockSource,1000000000,this,"CS1237 deadline",ulong.MaxValue,direction:Direction.Ascending,workMode:WorkMode.OneShot,enabled:false,eventEnabled:true);
   deadline.LimitReached+=Tick;port.Access+=Access;port.BeforeRead=BeforeRead;
   scheduler=new Cs1237DeadlineScheduler(()=>ClockNow,()=>protocol.Now,()=>protocol.NextEventNanoseconds,
    ()=>AdapterErrors!=0||protocol.ProtocolFault,DisableDeadline,Advance,ApplyOutput,ArmDeadline,Error);
   ApplyOutput();Schedule();Record("power-on");
  }
  // Explicit externally supplied laboratory sensor source. Invoked at real conversion deadlines.
  // Force/geometry mapping belongs to a separate fixture and is NOT implemented here.
  public Func<int> Source {get{return source;}set{if(TimedProviderBound)throw new InvalidOperationException("Exclusive timed provider is already bound");sourceModified=true;source=value;}}
  public bool TimedProviderBound {get;private set;}
  public void BindTimedSource(Func<long,int> provider)
  {
   if(provider==null)throw new ArgumentNullException("provider");
   if(TimedProviderBound || sourceModified || timedSource!=null || source!=baselineSource)throw new InvalidOperationException("Cannot replace an existing or modified sensor source");
   source=null;timedSource=provider;TimedProviderBound=true;
  }
  // A future dynamic source must resolve this timestamp in the ADC clock domain;
  // a present-state force getter is not a historical/cross-machine time mapping.
  public Func<long,int> TimedSource {get{return timedSource;}set{if(TimedProviderBound)throw new InvalidOperationException("Exclusive timed provider is already bound");sourceModified=true;timedSource=value;}}
  public Cs1237FunctionalProtocol Protocol {get{return protocol;}}
  public string ProfileName {get{return "explicit-functional-CS1237-no-physical-timing-fidelity";}}
  public long ProviderCalls {get;private set;}
  public long ProviderFailures {get;private set;}
  public long AdapterErrors {get;private set;}
  public string AdapterError {get;private set;}
  public long ResetObservations {get;private set;}
  public long Dropped {get;private set;}
  public void Reset(){ResetObservations++;} // MCU reset is not sensor power loss.
  public void WriteTrace(string path){File.WriteAllText(path,"ns,event,ready,clock,config,host,device,transition,pa5,pa6,pa7,conversions,reads,writes,protocol_errors,overlaps,adapter_errors,error,adapter_error,high_timing_violations,low_timing_violations,wake_low_violations\n"+String.Join("\n",rows)+"\n");}
  public void WriteStatus(string path)
  {
   File.WriteAllText(path,"{\"profile\":\""+ProfileName+"\",\"timed_provider_bound\":"+(TimedProviderBound?"true":"false")+",\"physical_timing_fidelity\":false,\"high_pulse_timing_violations\":"+protocol.HighPulseTimingViolations+",\"low_pulse_timing_violations\":"+protocol.LowPulseTimingViolations+",\"wake_low_timing_violations\":"+protocol.WakeLowTimingViolations+",\"minimum_high_ns\":"+protocol.MinimumHighNanoseconds+",\"minimum_low_ns\":"+protocol.MinimumLowNanoseconds+",\"overlap_both_high\":"+protocol.OverlapBothHigh+",\"overlap_both_low\":"+protocol.OverlapBothLow+",\"overlap_host_high_device_low\":"+protocol.OverlapHostHighDeviceLow+",\"overlap_host_low_device_high\":"+protocol.OverlapHostLowDeviceHigh+",\"overlap_unknown_transition\":"+protocol.OverlapUnknownTransition+",\"now_ns\":"+port.Nanoseconds+",\"config\":"+protocol.Config+",\"conversions\":"+protocol.ConversionCount+",\"read_words\":"+protocol.ReadWordCount+",\"config_writes\":"+protocol.ConfigWrites+",\"protocol_errors\":"+protocol.Errors+",\"host_priority_overlap_observations\":"+protocol.HostPriorityOverlapObservations+",\"provider_calls\":"+ProviderCalls+",\"provider_failures\":"+ProviderFailures+",\"adapter_errors\":"+AdapterErrors+",\"dropped\":"+Dropped+",\"suppressed_ticks\":"+SuppressedTicks+",\"scheduler_drain_passes\":"+SchedulerDrainPasses+",\"scheduler_rearm_attempts\":"+SchedulerRearmAttempts+",\"scheduler_nonconvergence_errors\":"+SchedulerNonConvergenceErrors+",\"last_error\":\""+Clean(protocol.LastError)+"\",\"adapter_error\":\""+Clean(AdapterError)+"\",\"pa7_written_by_adapter\":false,\"main_pb2_connected\":false}\n");
  }
  private void Advance(long now)
  {
   if(AdapterErrors!=0)return; // Fail-stop: never retry an invalid external provider implicitly.
   // Process each true model deadline separately, sampling the provider only when
   // the ADC is about to latch a new conversion, never at a host read or requested motion.
   while(protocol.NextEventNanoseconds<=now)
   {
    var at=protocol.NextEventNanoseconds;
    if(at==protocol.NextReadyNanoseconds)
    {if(Source==null && TimedSource==null)protocol.RemoveSyntheticSource();else
     {try{ProviderCalls++;protocol.SetSyntheticCode(TimedSource!=null?TimedSource(at):Source());}catch(Exception e){ProviderFailures++;Error("Sensor provider failed: "+e.Message);return;}}}
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
  private void Tick(){if(updating){SuppressedTicks++;LastSuppressedClockNanoseconds=checked((long)machine.ClockSource.CurrentValue.TotalNanoseconds);LastSuppressedProtocolNanoseconds=protocol.Now;LastSuppressedDeadlineNanoseconds=protocol.NextEventNanoseconds;return;}updating=true;try{Advance(port.Nanoseconds);ApplyOutput();Schedule();}finally{updating=false;}}
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
   ScheduleCalls++;ScheduleEntryClockNanoseconds=ClockNow;ScheduleEntryProtocolNanoseconds=protocol.Now;
   // Timer access may synchronously flush the peripheral clock and suppress Tick
   // while this adapter is updating. Drain only genuinely due protocol events at
   // their unchanged timestamps, then arm against a verified stable clock read.
   scheduler.Run();
  }
  private void DisableDeadline(){deadline.Enabled=false;ScheduleAfterDisableNanoseconds=ClockNow;}
  private void ArmDeadline(long delta)
  {
   deadline.Limit=(ulong)delta;ScheduleAfterLimitNanoseconds=ClockNow;
   deadline.Value=0;ScheduleAfterValueNanoseconds=ClockNow;
   deadline.Enabled=true;ScheduleAfterEnableNanoseconds=ClockNow;
  }
  private void Error(string message){if(AdapterErrors==0)AdapterError=message;AdapterErrors++;deadline.Enabled=false;port.ReleasePin(6);Record("adapter-error");}
  private static string Level(bool? b){return b.HasValue?(b.Value?"1":"0"):"unknown";}
  private static string Clean(string s){return (s??"").Replace('"','\'').Replace('\\','/').Replace(',',';').Replace('\n',' ');}
  private readonly int maximumTraceRows;
  private void Record(string why)
  {
   if(rows.Count>=maximumTraceRows){Dropped++;return;}
   uint pads=port.Snapshot(8);
   rows.Add(String.Join(",",new[]{protocol.Now.ToString(),why,protocol.Ready?"1":"0",protocol.ClockCount.ToString(),protocol.Config.ToString(),Level(protocol.HostDout),Level(protocol.DeviceDout),protocol.OutputTransition?"1":"0",((pads>>5)&1).ToString(),((pads>>6)&1).ToString(),((pads>>7)&1).ToString(),protocol.ConversionCount.ToString(),protocol.ReadWordCount.ToString(),protocol.ConfigWrites.ToString(),protocol.Errors.ToString(),protocol.HostPriorityOverlapObservations.ToString(),AdapterErrors.ToString(),Clean(protocol.LastError),Clean(AdapterError),protocol.HighPulseTimingViolations.ToString(),protocol.LowPulseTimingViolations.ToString(),protocol.WakeLowTimingViolations.ToString()}));
  }
  private long ClockNow {get{return checked((long)machine.ClockSource.CurrentValue.TotalNanoseconds);}}
  public long ScheduleCalls {get;private set;}
  public long ScheduleEntryClockNanoseconds {get;private set;}
  public long ScheduleEntryProtocolNanoseconds {get;private set;}
  public long ScheduleAfterDisableNanoseconds {get;private set;}
  public long ScheduleAfterLimitNanoseconds {get;private set;}
  public long ScheduleAfterValueNanoseconds {get;private set;}
  public long ScheduleAfterEnableNanoseconds {get;private set;}
  public long SuppressedTicks {get;private set;}
  public long LastSuppressedClockNanoseconds {get;private set;}
  public long LastSuppressedProtocolNanoseconds {get;private set;}
  public long LastSuppressedDeadlineNanoseconds {get;private set;}
  public long SchedulerDrainPasses {get{return scheduler.DrainPasses;}}
  public long SchedulerRearmAttempts {get{return scheduler.RearmAttempts;}}
  public long SchedulerNonConvergenceErrors {get{return scheduler.NonConvergenceErrors;}}
  private readonly Cs1237DeadlineScheduler scheduler;
  private readonly IMachine machine;
  private bool sourceModified;private readonly Func<int> baselineSource;private Func<int> source;private Func<long,int> timedSource;
  private readonly Cs1237NativeGpio port;private readonly Cs1237FunctionalProtocol protocol;private readonly LimitTimer deadline;
  private bool updating;private readonly List<string> rows=new List<string>();
 }

 // Pure event-pump policy. Clock/timer operations are supplied explicitly so the
 // convergence and timestamp contract can be tested without mutating real clocks.
 public sealed class Cs1237DeadlineScheduler
 {
  public Cs1237DeadlineScheduler(Func<long> now,Func<long> protocolNow,Func<long> next,
   Func<bool> faulted,Action disable,Action<long> advance,Action apply,Action<long> arm,Action<string> error)
  {
   if(now==null||protocolNow==null||next==null||faulted==null||disable==null||advance==null||apply==null||arm==null||error==null)throw new ArgumentNullException();
   this.now=now;this.protocolNow=protocolNow;this.next=next;this.faulted=faulted;
   this.disable=disable;this.advance=advance;this.apply=apply;this.arm=arm;this.error=error;
  }
  public bool Run()
  {
   for(int attempt=0;attempt<MaximumAttempts;attempt++)
   {
    if(faulted())return false;
    disable();long at=next();long current;
    if(!ReadClock(out current))return false;
    if(faulted()||at==long.MaxValue)return !faulted();
    if(at<=protocolNow())return Fail("Non-advancing sensor protocol deadline; event_ns="+at+" protocol_ns="+protocolNow()+" clock_source_ns="+current);
    if(at<=current)
    {
     // Advance processes every due event separately at its original at value,
     // including one provider call per conversion candidate. Never shift at.
     DrainPasses++;advance(current);apply();
     if(faulted())return false;
     if(next()==at)return Fail("Sensor deadline failed to advance while draining; event_ns="+at);
     continue;
    }
    RearmAttempts++;arm(at-current);long after;
    if(!ReadClock(out after))return false;
    if(faulted())return false;
    // Setter/getter reentry can advance clock accounting. Verify the programmed
    // interval's base; retry with the remaining interval, never a shifted event.
    if(after==current&&next()==at)return true;
   }
   NonConvergenceErrors++;
   return Fail("Sensor scheduling did not converge within "+MaximumAttempts+" attempts; clock_source_ns="+now()+" protocol_ns="+protocolNow()+" event_ns="+next());
  }
  private bool ReadClock(out long value)
  {
   value=now();if(value<0||value<lastClock)return Fail("Sensor peripheral clock moved backwards; clock_source_ns="+value+" previous_ns="+lastClock);
   lastClock=value;
   if(protocolNow()>value)return Fail("Sensor protocol is ahead of its peripheral clock; protocol_ns="+protocolNow()+" clock_source_ns="+value);
   return true;
  }
  private bool Fail(string message){error(message);return false;}
  public long DrainPasses{get;private set;}
  public long RearmAttempts{get;private set;}
  public long NonConvergenceErrors{get;private set;}
  public const int MaximumAttempts=128;
  private long lastClock=-1;
  private readonly Func<long> now,protocolNow,next;private readonly Func<bool> faulted;
  private readonly Action disable,apply;private readonly Action<long> advance,arm;private readonly Action<string> error;
 }
}
