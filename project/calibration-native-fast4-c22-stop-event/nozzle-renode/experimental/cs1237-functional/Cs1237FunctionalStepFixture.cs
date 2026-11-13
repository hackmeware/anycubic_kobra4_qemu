// Explicit laboratory sample stimulus and passive native-state observer. No force or GPIO writes.
using System;
using System.IO;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.NozzleExperimental
{
 public class Cs1237FunctionalStepFixture : IBusPeripheral, IGPIOReceiver
 {
  public Cs1237FunctionalStepFixture(IMachine machine,Cs1237NativeGpio port,Cs1237FunctionalAdapter sensor,int baseline)
  {
   bus=machine.GetSystemBus(this);this.port=port;this.sensor=sensor;this.baseline=baseline;value=baseline;
   sensor.TimedSource=Sample;port.Connections[7].Connect(this,7);
   timer=new LimitTimer(machine.ClockSource,1000000,this,"passive native sensor snapshot",100,direction:Direction.Ascending,workMode:WorkMode.Periodic,enabled:true,eventEnabled:true);
   timer.LimitReached+=Tick;
  }
  public void StepAt(long nanoseconds,int signedCode)
  {if(nanoseconds<port.Nanoseconds || signedCode < -8388608 || signedCode>8388607)throw new ArgumentOutOfRangeException();stepAt=nanoseconds;value=signedCode;}
  public void RemoveSourceAt(long nanoseconds){if(nanoseconds<port.Nanoseconds)throw new ArgumentOutOfRangeException();removeAt=nanoseconds;}
  public void Mark(string label){Record("mark:"+label.Replace(',', ';'));}
  public void OnGPIO(int number,bool level){if(number!=7)throw new ArgumentException();Record(level?"pa7-rise":"pa7-fall");}
  public void Reset(){Record("fixture-reset-observed");} // Not sensor or native reset.
  public long Dropped {get;private set;}
  public void WriteTrace(string path)
  {File.WriteAllText(path,"ns,event,pa7,oid_valid,raw,average,threshold,filtered_difference,reset24,arm25,rearm26,baseline28,enable30,enable32,reset38,trigger20,slow,fast,settle_count,inhibit_count,trigger_latch,core_conversions,core_reads,core_errors,adapter_errors\n"+String.Join("\n",rows)+"\n");}
  public void WriteStimuli(string path)
  {File.WriteAllText(path,"deadline_ns,code\n"+String.Join("\n",stimuli)+"\n");}
  private int Sample(long at)
  {
   var code=at>=stepAt?value:baseline;
   if(stimuli.Count==0 || code!=lastSample){stimuli.Add(at+","+code);lastSample=code;}
   return code;
  }
  private void Tick()
  {
   if(port.Nanoseconds>=removeAt){sensor.Source=null;sensor.TimedSource=null;removeAt=long.MaxValue;Record("laboratory-source-removed");}
   Record("snapshot");
  }
  private int Signed(uint addr){return unchecked((int)bus.ReadDoubleWord(addr));}
  private void Record(string why)
  {
   if(timer==null)return;
   if(rows.Count>=20000){Dropped++;return;}
   uint obj=0;var table=bus.ReadDoubleWord(0x20000074);
   if(table>=0x20000000 && table<0x20004f00 && bus.ReadByte(0x20000070)>9 && bus.ReadDoubleWord(table+72)==0x0800a391)obj=bus.ReadDoubleWord(table+76);
   var vals=new List<string>{port.Nanoseconds.ToString(),why,((port.Snapshot(8)>>7)&1).ToString(),obj!=0?"1":"0"};
   foreach(var off in new uint[]{24,28,16,60})vals.Add(obj!=0?Signed(obj+off).ToString():"");
   foreach(var off in new uint[]{0x24,0x25,0x26})vals.Add(obj!=0?bus.ReadByte(obj+off).ToString():"");
   vals.Add(obj!=0?Signed(obj+0x28).ToString():"");
   foreach(var off in new uint[]{0x30,0x32,0x38})vals.Add(obj!=0?bus.ReadByte(obj+off).ToString():"");
   vals.Add(obj!=0?Signed(obj+0x20).ToString():"");
   vals.Add(Signed(0x200003d8).ToString());vals.Add(Signed(0x200001e8).ToString());
   vals.Add(unchecked((short)bus.ReadWord(0x20000200)).ToString());vals.Add(unchecked((short)bus.ReadWord(0x200001ec)).ToString());vals.Add(bus.ReadByte(0x200001f0).ToString());
   vals.Add(sensor.Protocol.ConversionCount.ToString());vals.Add(sensor.Protocol.ReadWordCount.ToString());vals.Add(sensor.Protocol.Errors.ToString());vals.Add(sensor.AdapterErrors.ToString());rows.Add(String.Join(",",vals));
  }
  private readonly IBusController bus;private readonly Cs1237NativeGpio port;private readonly Cs1237FunctionalAdapter sensor;private readonly int baseline;private readonly LimitTimer timer;
  private long stepAt=long.MaxValue,removeAt=long.MaxValue;private int value,lastSample;private readonly List<string> rows=new List<string>(),stimuli=new List<string>();
 }
}
