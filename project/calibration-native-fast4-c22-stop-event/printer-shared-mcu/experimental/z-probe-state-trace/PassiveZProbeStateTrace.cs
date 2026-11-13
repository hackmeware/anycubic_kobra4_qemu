// SPDX-License-Identifier: MIT
// Optional edge-only observation. No model timer, synchronization, GPIO write,
// firmware-memory write, provider call, or physical integration is performed.
using System;
using System.IO;
using System.Text;
using System.Globalization;
using System.Collections.Generic;
using System.Security.Cryptography;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Memory;
using Antmicro.Renode.Peripherals.NozzleExperimental;
namespace Antmicro.Renode.Peripherals.PrinterExperimental
{
 public sealed class PassiveZProbeStateTrace : IBusPeripheral, IGPIOReceiver, IDisposable
 {
  public const string FirmwareSha256="ae09264667ff4a72905706026b1591bdede91e1f250755319fec531328e54e2f";
  public const int FirmwareLength=37469;
  public PassiveZProbeStateTrace(IMachine machine, Cs1237NativeGpio port,
   Cs1237FunctionalAdapter sensor, MappedMemory sram, MappedMemory flash, int maximumRows=4096)
  {
   if(machine==null||port==null||sensor==null||sram==null||flash==null)throw new ArgumentNullException();
   if(maximumRows<1||maximumRows>100000)throw new ArgumentOutOfRangeException("maximumRows");
   if(sram.Size!=0x5000||flash.Size<0x4000+FirmwareLength)throw new ArgumentException("Expected original nozzle SRAM/flash layout");
   this.machine=machine;this.port=port;this.sensor=sensor;this.sram=sram;this.flash=flash;maximum=maximumRows;
   // Connect is additive. Seed first so its initial callback is never an edge.
   last=port.Connections[7].IsSet;port.Connections[7].Connect(this,7);
  }
  public long Callbacks{get;private set;} public long DuplicateCallbacks{get;private set;}
  public long Edges{get;private set;} public long RowsAttempted{get;private set;}
  public long RowsWritten{get;private set;} public long CapDrops{get;private set;}
  public long InactiveEdgeDrops{get;private set;} public long StreamDrops{get;private set;}
  public long LayoutRejections{get;private set;} public long SnapshotErrors{get;private set;}
  public long StreamErrors{get;private set;} public long ObserverResets{get;private set;}
  public bool WriteOutcomeUncertain{get;private set;} public bool FirmwareVerified{get;private set;}
  public string LastError{get;private set;}="";
  public bool Active{get{return active;}}
  public void Start(string firmwarePath,string csvPath)
  {
   if(started)throw new InvalidOperationException("One capture per observer; create a fresh observer/fixture");
   // Do not trust only a path or a user-supplied digest: verify disk AND mapped bytes.
   var bytes=File.ReadAllBytes(firmwarePath);
   if(bytes.Length!=FirmwareLength||Hash(bytes)!=FirmwareSha256)throw new InvalidOperationException("Original firmware file hash/length mismatch");
   if(Hash(flash.ReadBytes(0x4000,FirmwareLength))!=FirmwareSha256)throw new InvalidOperationException("Loaded nozzle flash hash mismatch");
   FirmwareVerified=true;
   var target=Path.GetFullPath(csvPath);
   try { writer=new StreamWriter(new FileStream(target,FileMode.CreateNew,FileAccess.Write,FileShare.Read),new UTF8Encoding(false));writer.WriteLine(Header);writer.Flush(); }
   catch(Exception e){StreamErrors++;LastError=e.Message;CloseWriter();throw;}
   streamPath=target;started=true;active=true;
   last=port.Connections[7].IsSet;Capture("initial-level",last);
  }
  public void OnGPIO(int number,bool value)
  {
   // Never throw through GPIO fanout: an observer failure must not block other sinks.
   if(number!=7){SnapshotErrors++;LastError="Unexpected observer input pin";return;}
   Callbacks++;
   if(value==last){DuplicateCallbacks++;return;}
   last=value;Edges++;
   if(!active){InactiveEdgeDrops++;return;}
   Capture(value?"pa7-rise":"pa7-fall",value);
  }
  public void Reset(){ObserverResets++;} // Does not reset source, clocks, protocol or evidence.
  public void Stop(){active=false;CloseWriter();}
  public void Dispose(){Stop();} // Keep harmless sink attached; never disconnect other sinks.
  public void WriteStatus(string path)
  {
   if(streamPath!=null&&Path.GetFullPath(path)==streamPath)throw new ArgumentException("Status cannot overwrite stream");
   File.WriteAllText(path,StatusJson());
  }
  public string StatusJson()
  {
   return "{\"schema\":1,\"profile\":\"passive-original-nozzle-pa7-edge-state\",\"firmware_sha256\":\""+FirmwareSha256+
    "\",\"firmware_verified\":"+B(FirmwareVerified)+",\"active\":"+B(active)+",\"callbacks\":"+Callbacks+",\"duplicate_callbacks\":"+DuplicateCallbacks+
    ",\"edges\":"+Edges+",\"rows_attempted\":"+RowsAttempted+",\"rows_written\":"+RowsWritten+",\"maximum_rows\":"+maximum+
    ",\"cap_drops\":"+CapDrops+",\"inactive_edge_drops\":"+InactiveEdgeDrops+",\"stream_drops\":"+StreamDrops+
    ",\"layout_rejections\":"+LayoutRejections+",\"snapshot_errors\":"+SnapshotErrors+",\"stream_errors\":"+StreamErrors+
    ",\"observer_resets\":"+ObserverResets+",\"write_outcome_uncertain\":"+B(WriteOutcomeUncertain)+",\"last_error\":"+J(LastError)+
    ",\"new_model_timer\":false,\"sync_time_called\":false,\"signal_or_memory_writes\":false,\"native_replay_validated\":false}\n";
  }
  private void Capture(string kind,bool value)
  {
   RowsAttempted++;
   if(RowsAttempted>maximum){CapDrops++;return;} // No unbounded buffer or SRAM work after cap.
   if(writer==null){StreamDrops++;return;}
   string row;
   try
   {
    var p=sensor.Protocol;
    // Only cached/model clock properties. In particular, do NOT read port.Nanoseconds:
    // its LimitTimer.Value getter can flush the clock. No forced peripheral update.
    long published=checked((long)machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds);
    long peripheral=checked((long)machine.ClockSource.CurrentValue.TotalNanoseconds);
    ulong pc=0;bool hasCpu=machine.GetSystemBus(this).TryGetCurrentCPU(out var cpu);if(hasCpu)pc=cpu.PC.RawValue;
    FirmwareVerified=Hash(flash.ReadBytes(0x4000,FirmwareLength))==FirmwareSha256;
    string reason;uint obj;bool valid=TryLayout(out obj,out reason);
    var a=new List<string>{S(RowsAttempted),kind,B(value),S(published),S(peripheral),S(p.Now),B(hasCpu),S(pc),B(valid),reason,S(obj)};
    if(valid)
    {
     foreach(var off in new long[]{0x18,0x1c,0x10,0x3c,0x28,0x20})a.Add(S(unchecked((int)sram.ReadDoubleWord(obj-0x20000000+off))));
     foreach(var off in new long[]{0x24,0x25,0x26,0x30,0x32,0x38})a.Add(S(sram.ReadByte(obj-0x20000000+off)));
     a.Add(S(unchecked((int)sram.ReadDoubleWord(0x3d8))));a.Add(S(unchecked((int)sram.ReadDoubleWord(0x1e8))));
     a.Add(S(unchecked((short)sram.ReadWord(0x200))));a.Add(S(unchecked((short)sram.ReadWord(0x1ec))));a.Add(S(sram.ReadByte(0x1f0)));
    }
    else {LayoutRejections++;for(int i=0;i<17;i++)a.Add("");}
    a.AddRange(new[]{S(p.ConversionCount),S(p.ReadWordCount),S(p.LastLatchedSignedCode),S(p.ClockCount),S(p.Config),B(p.Ready),B(p.ProtocolFault),
     S(p.NextReadyNanoseconds),S(p.NextEventNanoseconds),S(p.OverwrittenUnreadWords),S(p.ConfigWrites),S(p.ConfigReads),S(p.Errors),
     S(sensor.ProviderCalls),S(sensor.ProviderFailures),S(sensor.AdapterErrors),S(sensor.ResetObservations),
     S(sensor.ScheduleCalls),S(sensor.ScheduleEntryClockNanoseconds),S(sensor.ScheduleEntryProtocolNanoseconds),
     S(sensor.ScheduleAfterDisableNanoseconds),S(sensor.ScheduleAfterLimitNanoseconds),S(sensor.ScheduleAfterValueNanoseconds),S(sensor.ScheduleAfterEnableNanoseconds),
     S(sensor.SuppressedTicks),S(sensor.LastSuppressedClockNanoseconds),S(sensor.LastSuppressedProtocolNanoseconds),S(sensor.LastSuppressedDeadlineNanoseconds),
     S(sensor.SchedulerDrainPasses),S(sensor.SchedulerRearmAttempts),S(sensor.SchedulerNonConvergenceErrors),S(p.HighPulseTimingViolations),S(p.LowPulseTimingViolations),S(p.HostPriorityOverlapObservations),S(port.Snapshot(0)),S(port.Snapshot(12)),S(port.Snapshot(8)),S(port.Synchronizations)});
    row=String.Join(",",a);
   }
   catch(Exception e){SnapshotErrors++;StreamDrops++;LastError=e.Message;return;}
   try{writer.WriteLine(row);writer.Flush();RowsWritten++;}
   catch(Exception e){StreamErrors++;StreamDrops++;WriteOutcomeUncertain=true;LastError=e.Message;CloseWriter();}
  }
  private bool TryLayout(out uint obj,out string reason)
  {
   obj=0;reason="";
   if(!FirmwareVerified){reason="firmware-unverified";return false;}
   uint count=sram.ReadByte(0x70),table=sram.ReadDoubleWord(0x74);
   if(count<=9){reason="oid9-absent";return false;}
   if(!Range(table,count*8)||((table&3)!=0)){reason="oid-table-outside-aligned-sram";return false;}
   if(sram.ReadDoubleWord(table-0x20000000+72)!=0x0800a391){reason="oid9-constructor-mismatch";return false;}
   obj=sram.ReadDoubleWord(table-0x20000000+76);
   if(!Range(obj,0x40)||((obj&3)!=0)){obj=0;reason="oid9-object-outside-aligned-sram";return false;}
   // Constructor stores the actual configured GPIO descriptors in fixed globals.
   if(sram.ReadDoubleWord(0x1f4)!=0x40010800||sram.ReadDoubleWord(0x1f8)!=0x80||
      sram.ReadDoubleWord(0x1cc)!=0x40010800||sram.ReadDoubleWord(0x1d0)!=0x40||
      sram.ReadDoubleWord(0x1d4)!=0x40010800||sram.ReadDoubleWord(0x1d8)!=0x40||
      sram.ReadDoubleWord(0x1dc)!=0x40010800||sram.ReadDoubleWord(0x1e0)!=0x20)
   {obj=0;reason="native-pa7-pa6-pa5-descriptor-mismatch";return false;}
   return true;
  }
  private static bool Range(uint address,uint size){return address>=0x20000000&&address<=0x20005000&&size<=0x20005000-address;}
  private void CloseWriter(){if(writer==null)return;try{writer.Dispose();}catch(Exception e){StreamErrors++;WriteOutcomeUncertain=true;LastError=e.Message;}writer=null;}
  private static string S(object o){return Convert.ToString(o,CultureInfo.InvariantCulture);}private static string B(bool v){return v?"true":"false";}
  private static string J(string s){return "\""+(s??"").Replace("\\","\\\\").Replace("\"","\\\"").Replace("\n","\\n").Replace("\r","\\r").Replace("\t","\\t")+"\"";}
  private static string Hash(byte[] b){using(var h=SHA256.Create())return BitConverter.ToString(h.ComputeHash(b)).Replace("-","").ToLowerInvariant();}
  public const string Header="sequence,event,pa7,published_machine_ns,peripheral_clock_ns,protocol_now_ns,has_current_cpu,pc,layout_valid,layout_reason,oid9_address,raw_signed,average_signed,sensitivity_signed,filtered_difference_signed,baseline_signed,stored_trigger_difference_signed,byte24,arm25,byte26,byte30,byte32,byte38,slow_signed,fast_signed,settle_signed,inhibit_signed,trigger_latch,conversions,read_words,last_latched_signed_code,clock_count,config,ready,protocol_fault,next_ready_ns,next_event_ns,overwritten_unread_words,config_writes,config_reads,protocol_errors,provider_calls,provider_failures,adapter_errors,adapter_reset_observations,schedule_calls,schedule_entry_clock_ns,schedule_entry_protocol_ns,schedule_after_disable_ns,schedule_after_limit_ns,schedule_after_value_ns,schedule_after_enable_ns,suppressed_ticks,last_suppressed_clock_ns,last_suppressed_protocol_ns,last_suppressed_deadline_ns,scheduler_drain_passes,scheduler_rearm_attempts,scheduler_nonconvergence_errors,high_timing_violations,low_timing_violations,host_priority_overlaps,gpio_config_low,gpio_latch,gpio_pads,source_sync_count";
  private readonly IMachine machine;private readonly Cs1237NativeGpio port;private readonly Cs1237FunctionalAdapter sensor;private readonly MappedMemory sram,flash;private readonly int maximum;
  private bool last,active,started;private StreamWriter writer;private string streamPath;
 }
}
