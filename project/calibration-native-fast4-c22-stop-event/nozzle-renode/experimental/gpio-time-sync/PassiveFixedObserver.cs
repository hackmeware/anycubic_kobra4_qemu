// Passive additional GPIO sink. No SyncTime, GPIO writes, or timer events.
using System;
using System.IO;
using System.Collections.Generic;
using System.Globalization;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.AT32;
using Antmicro.Renode.Peripherals.Nozzle;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.NozzleDiagnostics
{
 public sealed class PassiveAutobaudObserver : IPeripheral, IGPIOReceiver
 {
  public PassiveAutobaudObserver(IMachine machine, AT32GPIO port, VirtualNozzleTmc2209 tmc, int pin=3, int maximumRows=200000)
  {
   if(pin<0||pin>15||maximumRows<1)throw new ArgumentException("Invalid observer parameters");
   this.machine=machine;this.port=port;this.tmc=tmc;this.pin=pin;maximum=maximumRows;
   clock=new LimitTimer(machine.ClockSource,1000000000,this,"passive UART timestamp",ulong.MaxValue,direction:Direction.Ascending,enabled:true,eventEnabled:false);
   port.Connections[pin].Connect(this,pin);Mark("attached");
  }
  public void Reset(){Mark("reset_observed");}
  public void OnGPIO(int number,bool value){if(number!=pin)throw new ArgumentException("Unexpected pin");Add("edge",value);}
  public void Mark(string label){Add("mark:"+label.Replace(',', ';').Replace('\n',' '),(port.ReadSnapshot(8)&(1u<<pin))!=0);}
  public void WriteCsv(string path)
  {
   lock(sync)File.WriteAllText(path,"clock_ns,machine_elapsed_ns,event,level,mode,latch,reads,writes,rejected,received,last_request,last_reply\n"+String.Join("\n",rows)+"\n");
  }
  public int Rows {get {lock(sync)return rows.Count;}}
  public ulong Dropped {get;private set;}
  public ulong PassiveReadChecks {get;private set;}
  private void Add(string label,bool value)
  {
   machine.ClockSource.ExecuteInLock(() => {
   lock(sync)
   {
    if(rows.Count>=maximum){Dropped++;return;}
    ulong before=clock.Value;ulong syncBefore=port.CpuSynchronizationCalls;
    var config=(port.ReadSnapshot(pin<8?0:4)>>((pin%8)*4))&15;
    rows.Add(String.Join(",",new[]{clock.Value.ToString(CultureInfo.InvariantCulture),machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds.ToString(CultureInfo.InvariantCulture),label,value?"1":"0",config.ToString(),((port.ReadSnapshot(12)>>pin)&1).ToString(),tmc.Reads.ToString(),tmc.Writes.ToString(),tmc.RejectedFrames.ToString(),tmc.ReceivedBytes.ToString(),tmc.LastRequest??"",tmc.LastReply??""}));
    ulong after=clock.Value;ulong syncAfter=port.CpuSynchronizationCalls;
    if(after!=before || syncAfter!=syncBefore)throw new InvalidOperationException("Passive observer invariance failure: clock "+before+" -> "+after+", sync calls "+syncBefore+" -> "+syncAfter);
    PassiveReadChecks++;
   }
   });
  }
  private readonly IMachine machine;private readonly AT32GPIO port;private readonly VirtualNozzleTmc2209 tmc;private readonly int pin,maximum;
  private readonly LimitTimer clock;private readonly object sync=new object();private readonly List<string> rows=new List<string>();
 }
}
