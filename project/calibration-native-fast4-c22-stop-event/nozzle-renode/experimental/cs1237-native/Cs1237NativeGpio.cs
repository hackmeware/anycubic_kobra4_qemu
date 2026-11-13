// SPDX-License-Identifier: MIT
// Experimental, explicit opt-in GPIO wrapper. Original firmware remains untouched.
using System;
using System.IO;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.AT32;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.NozzleExperimental
{
 public class Cs1237NativeGpio : AT32GPIO, IDoubleWordPeripheral
 {
  public Cs1237NativeGpio(IMachine machine, AT32IOMUX iomux=null, int portIndex=0) : base(machine,iomux,portIndex)
  {
   this.machine=machine;
   clock=new LimitTimer(machine.ClockSource,1000000000,this,"CS1237 GPIO timestamp",ulong.MaxValue,direction:Direction.Ascending,enabled:true,eventEnabled:false);
  }
  public override void Reset()
  {
   base.Reset();
   if(clock!=null && Access!=null)Access(Nanoseconds,uint.MaxValue,0,Snapshot(0),Snapshot(12));
  }
  public event Action<long,uint,uint,uint,uint> Access; // time,offset,value,config,latch
  public long Nanoseconds {get{return checked((long)clock.Value);}}
  public uint Snapshot(long offset){return base.ReadDoubleWord(offset);}
  public ulong Synchronizations {get;private set;}
  public new uint ReadDoubleWord(long offset)
  {
   SynchronizeIfSensorRead(offset);
   if(BeforeRead!=null)BeforeRead(offset);
   var value=base.ReadDoubleWord(offset);
   Record("read",offset,value);return value;
  }
  public Action<long> BeforeRead;
  public bool IsNativeSensorRead {get {return machine.GetSystemBus(this).TryGetCurrentCPU(out var cpu) && cpu.PC.RawValue==0x08009a52;}}
  public new void WriteDoubleWord(long offset,uint value)
  {
   SynchronizeIfSensorWrite(offset,value);base.WriteDoubleWord(offset,value);
   if(Access!=null)Access(Nanoseconds,(uint)offset,value,Snapshot(0),Snapshot(12));
   Record("write",offset,value);
  }
  public void WriteTrace(string path)
  { File.WriteAllText(path,"ns,event,offset,value,config,latch,pads,pc\n"+String.Join("\n",rows)+"\n"); }
  public long Dropped {get;private set;}
  private void SynchronizeIfSensorRead(long offset)
  {
   if(offset!=8)return;
   if(machine.GetSystemBus(this).TryGetCurrentCPU(out var cpu) && cpu.PC.RawValue==0x08009a52)
   {Synchronizations++;cpu.SyncTime();}
  }
  private void SynchronizeIfSensorWrite(long offset,uint value)
  {
   bool relevant=offset==0 ? ((value^Snapshot(0))&0x0ff00000)!=0 :
    offset==12 ? ((value^Snapshot(12))&0x60)!=0 :
    offset==16 ? (value&0x00600060)!=0 : offset==20 && (value&0x60)!=0;
   if(relevant && machine.GetSystemBus(this).TryGetCurrentCPU(out var cpu))
   {Synchronizations++;cpu.SyncTime();}
  }
  private void Record(string kind,long offset,uint value)
  {
   if(offset!=0 && offset!=8 && offset!=12 && offset!=16 && offset!=20)return;
   var c=Snapshot(0);var l=Snapshot(12);var p=Snapshot(8);
   // Keep all configuration writes, sensor-related changes and IDT reads in sensor routines.
   ulong pc=0;if(machine.GetSystemBus(this).TryGetCurrentCPU(out var cpu))pc=cpu.PC.RawValue;
   if(kind=="write" && offset!=0 && ((l^lastLatch)&0xe0)==0 && ((p^lastPads)&0xe0)==0)return;
   if(kind=="read" && !(pc>=0x080098f8 && pc<0x0800a540))return;
   lastLatch=l;lastPads=p;
   if(rows.Count>=200000){Dropped++;return;}
   rows.Add(String.Join(",",new[]{Nanoseconds.ToString(),kind,offset.ToString(),value.ToString(),c.ToString(),l.ToString(),p.ToString(),pc.ToString()}));
  }
  private readonly IMachine machine;private readonly LimitTimer clock;
  private uint lastLatch,lastPads;private readonly List<string> rows=new List<string>();
 }
}
