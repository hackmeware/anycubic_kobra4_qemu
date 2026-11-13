// CPU-free TEST ONLY: supplies register stimuli and explicitly synthetic SRAM.
// None of these stimuli is part of the passive observer or a native run.
using System;
using System.IO;
using System.Reflection;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Memory;
using Antmicro.Renode.Peripherals.NozzleExperimental;
namespace Antmicro.Renode.Peripherals.PrinterExperimental
{
 public sealed class ProbeStateTraceTests : IPeripheral, IGPIOReceiver
 {
  public ProbeStateTraceTests(IMachine machine,Cs1237NativeGpio port,Cs1237FunctionalAdapter sensor,
   Cs1237NativeGpio controlPort,Cs1237FunctionalAdapter controlSensor,MappedMemory sram,MappedMemory flash)
  {this.machine=machine;this.port=port;this.sensor=sensor;this.controlPort=controlPort;this.controlSensor=controlSensor;this.sram=sram;this.flash=flash;port.Connections[7].Connect(this,7);}
  public void Reset(){} public void OnGPIO(int n,bool v){if(v!=last){fanoutEdges++;last=v;}}
  private void Check(bool yes,string why){if(!yes)throw new Exception(why);checks++;Console.WriteLine("PROBE STATE CHECK PASS: "+why);}
  private void Reject(Action a,string why){bool rejected=false;try{a();}catch{rejected=true;}Check(rejected,why);}
  private PassiveZProbeStateTrace New(int cap=256){return new PassiveZProbeStateTrace(machine,port,sensor,sram,flash,cap);}
  private void High(){port.WriteDoubleWord(16,128);controlPort.WriteDoubleWord(16,128);}
  private void Low(){port.WriteDoubleWord(20,128);controlPort.WriteDoubleWord(20,128);}
  private void Seed()
  {
   sram.WriteByte(0x70,10);sram.WriteDoubleWord(0x74,0x20000480);
   sram.WriteDoubleWord(0x480+72,0x0800a391);sram.WriteDoubleWord(0x480+76,0x200006f0);
   foreach(var x in new int[]{0x1f4,0x1cc,0x1d4,0x1dc})sram.WriteDoubleWord(x,0x40010800);
   sram.WriteDoubleWord(0x1f8,128);sram.WriteDoubleWord(0x1d0,64);sram.WriteDoubleWord(0x1d8,64);sram.WriteDoubleWord(0x1e0,32);
   sram.WriteDoubleWord(0x6f0+24,10000);sram.WriteDoubleWord(0x6f0+28,9000);sram.WriteDoubleWord(0x6f0+16,unchecked((uint)-1200));
   sram.WriteDoubleWord(0x6f0+60,1275);sram.WriteDoubleWord(0x6f0+40,0);sram.WriteDoubleWord(0x6f0+32,unchecked((uint)-77));
   sram.WriteByte(0x6f0+0x25,1);sram.WriteDoubleWord(0x3d8,300);sram.WriteDoubleWord(0x1e8,1575);sram.WriteWord(0x200,32);
  }
  public string RunAll(string firmware,string directory)
  {
   dir=directory;Seed();port.WriteDoubleWord(0,0x24444444);controlPort.WriteDoubleWord(0,0x24444444);
   var before=Fingerprint();var bad=New();Check(before==Fingerprint(),"constructor preserves actual models");
   Reject(()=>New(0),"zero capacity rejected");Reject(()=>New(100001),"oversize capacity rejected");
   Reject(()=>bad.Start(Path.Combine(dir,"missing.bin"),Path.Combine(dir,"missing.csv")),"missing original image rejected");
   var wrong=Path.Combine(dir,"wrong.bin");File.WriteAllBytes(wrong,new byte[]{0,1});
   Reject(()=>bad.Start(wrong,Path.Combine(dir,"wrong.csv")),"wrong original image rejected");
   Check(!bad.FirmwareVerified&&!File.Exists(Path.Combine(dir,"wrong.csv")),"wrong file creates no decoded trace");
   var first=flash.ReadByte(0x4000);flash.WriteByte(0x4000,(byte)(first^1));
   Reject(()=>bad.Start(firmware,Path.Combine(dir,"wrong-live.csv")),"wrong mapped firmware rejected");flash.WriteByte(0x4000,first);
   Reject(()=>bad.Start(firmware,Path.Combine(dir,"absent-directory/a.csv")),"stream-open error reported");Check(bad.StreamErrors==1,"stream-open failure counted");
   High();int initialFanout=fanoutEdges;var high=New();before=Fingerprint();high.Start(firmware,Path.Combine(dir,"initial-high.csv"));
   Check(high.Edges==0&&high.RowsWritten==1&&before==Fingerprint(),"initial high is level not fabricated edge; Start invariant");
   Reject(()=>high.Start(firmware,Path.Combine(dir,"second.csv")),"duplicate start rejected");
   Low();Check(high.Edges==1&&fanoutEdges==initialFanout+1,"real falling edge preserves independent source fanout");
   High();High();Check(high.Edges==2&&fanoutEdges==initialFanout+2,"real rise recorded, same-level writes not edges");
   high.Stop();Check(File.ReadAllLines(Path.Combine(dir,"initial-high.csv")).Length==4,"initial plus two edge records streamed immediately");
   var observed=New();observed.Start(firmware,Path.Combine(dir,"fields.csv"));Low();High();
   var lines=File.ReadAllLines(Path.Combine(dir,"fields.csv"));var cells=lines[3].Split(',');
   Check(cells[1]=="pa7-rise"&&cells[8]=="true"&&cells[11]=="10000"&&cells[12]=="9000"&&cells[13]=="-1200"&&cells[14]=="1275"&&cells[16]=="-77", "signed raw/filter and prior trigger-difference kept verbatim");
   sram.WriteDoubleWord(0x6f0+32,unchecked((uint)-10000));sram.WriteByte(0x6f0+0x25,0);sram.WriteByte(0x1f0,1);Low();
   Check(File.ReadAllLines(Path.Combine(dir,"fields.csv"))[4].Split(',')[16]=="-10000","later falling snapshot sees later stored state without inventing a hook");
   long rejects=observed.LayoutRejections;sram.WriteByte(0x70,0);High();Check(observed.LayoutRejections==++rejects,"absent OID rejected");Seed();
   sram.WriteDoubleWord(0x74,0xfffffff0);Low();Check(observed.LayoutRejections==++rejects,"out-of-bounds table rejected before read");Seed();
   sram.WriteDoubleWord(0x74,0x20000481);High();Check(observed.LayoutRejections==++rejects,"unaligned table rejected");Seed();
   sram.WriteDoubleWord(0x480+72,0x0800a393);Low();Check(observed.LayoutRejections==++rejects,"wrong constructor rejected");Seed();
   sram.WriteDoubleWord(0x480+76,0x20004fe0);High();Check(observed.LayoutRejections==++rejects,"partial object outside SRAM rejected");Seed();
   sram.WriteDoubleWord(0x1f8,64);Low();Check(observed.LayoutRejections==++rejects,"wrong native pin descriptor rejected");Seed();
   flash.WriteByte(0x4000,(byte)(first^1));High();Check(observed.LayoutRejections==++rejects&&!observed.FirmwareVerified,"changed live firmware blocks decode on next edge");flash.WriteByte(0x4000,first);Low();
   cells=File.ReadAllLines(Path.Combine(dir,"fields.csv"))[File.ReadAllLines(Path.Combine(dir,"fields.csv")).Length-2].Split(',');
   Check(cells[8]=="false"&&cells[11]==""&&cells[16]=="","invalid layout never emits interpreted raw/filter fields");
   observed.WriteStatus(Path.Combine(dir,"fields-status.json"));observed.Stop();
   var capped=New(2);capped.Start(firmware,Path.Combine(dir,"cap.csv"));High();Low();High();
   Check(capped.RowsWritten==2&&capped.RowsAttempted==4&&capped.CapDrops==2,"bounded stream counts cap losses");capped.WriteStatus(Path.Combine(dir,"cap-status.json"));capped.Stop();
   var failed=New();failed.Start(firmware,Path.Combine(dir,"write-failure.csv"));
   // Test-only fault injection closes only the observer's own writer. No model reflection.
   ((StreamWriter)typeof(PassiveZProbeStateTrace).GetField("writer",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(failed)).Dispose();
   initialFanout=fanoutEdges;Low();High();Check(failed.StreamErrors==1&&failed.StreamDrops==2&&failed.WriteOutcomeUncertain,"mid-stream error fails closed and records uncertain loss");
   Check(fanoutEdges==initialFanout+2,"stream failure cannot block independent GPIO fanout");failed.WriteStatus(Path.Combine(dir,"write-failure-status.json"));failed.Stop();
   Reject(()=>observed.WriteStatus(Path.Combine(dir,"fields.csv")),"status cannot overwrite evidence stream");
   var reset=New();reset.Start(firmware,Path.Combine(dir,"source-reset.csv"));initialFanout=fanoutEdges;
   port.Reset();controlPort.Reset();Check(reset.Edges==1&&fanoutEdges==initialFanout+1,"source reset emits real low and preserves fanout");
   before=Fingerprint();reset.Reset();Check(reset.ObserverResets==1&&before==Fingerprint(),"observer Reset retains models and clocks");
   port.WriteDoubleWord(0,0x24444444);controlPort.WriteDoubleWord(0,0x24444444);High();Check(reset.Edges==2,"fanout survives source reset");reset.Stop();
   before=Fingerprint();Low();Check(before!=Fingerprint()&&reset.InactiveEdgeDrops==1,"stopped observer counts later edges without sampling");
   Check(port.Synchronizations==0&&controlPort.Synchronizations==0,"zero explicit CPU synchronization");
   Check(EqualModels(),"actual observed/control model invariance after stimuli and negative paths");
   // Keep one active observer while the real unchanged protocol timers convert.
   Seed();live=New();live.Start(firmware,Path.Combine(dir,"timed.csv"));
   Check(live.Edges==0&&File.ReadAllLines(Path.Combine(dir,"timed.csv"))[1].Split(',')[2]=="false","initial low is recorded without an invented edge");
   Reject(()=>New().Start(firmware,Path.Combine(dir,"timed.csv")),"existing evidence stream is never overwritten");
   return "PROBE STATE INITIAL TESTS PASS: "+checks;
  }
  public string Finish()
  {
   Check(sensor.Protocol.ConversionCount>0,"real existing protocol conversion timer fired CPU-free");
   Check(EqualModels(),"observation leaves actual model counters/deadlines/clock values unchanged");
   var before=Fingerprint();High();Check(live.Edges==1,"post-conversion actual GPIO rise observed");
   Check(EqualModels(),"reading all existing protocol properties leaves observed/control states identical");
   live.WriteStatus(Path.Combine(dir,"timed-status.json"));live.Stop();
   Check(port.Synchronizations==0&&controlPort.Synchronizations==0,"observer added no synchronization through real timed conversion");
   return "PROBE STATE ALL TESTS PASS: "+checks;
  }
  private string Fingerprint(){return One(port,sensor)+"|"+One(controlPort,controlSensor)+"|"+machine.ClockSource.CurrentValue.TotalNanoseconds+"|"+machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds;}
  private bool EqualModels(){return One(port,sensor)==One(controlPort,controlSensor);}
  private string One(Cs1237NativeGpio p,Cs1237FunctionalAdapter a)
  {
   var v=new List<string>{p.Snapshot(0).ToString(),p.Snapshot(8).ToString(),p.Snapshot(12).ToString(),p.Synchronizations.ToString()};
   foreach(var prop in typeof(Cs1237FunctionalProtocol).GetProperties())if(prop.CanRead)v.Add(prop.Name+"="+prop.GetValue(a.Protocol,null));
   foreach(var prop in typeof(Cs1237FunctionalAdapter).GetProperties())if(prop.CanRead&&prop.Name!="Source"&&prop.Name!="TimedSource"&&prop.Name!="Protocol")v.Add(prop.Name+"="+prop.GetValue(a,null));
   return String.Join(";",v);
  }
  private readonly IMachine machine;private readonly Cs1237NativeGpio port,controlPort;private readonly Cs1237FunctionalAdapter sensor,controlSensor;private readonly MappedMemory sram,flash;
  private int checks,fanoutEdges;private bool last;private string dir;private PassiveZProbeStateTrace live;
 }
}
