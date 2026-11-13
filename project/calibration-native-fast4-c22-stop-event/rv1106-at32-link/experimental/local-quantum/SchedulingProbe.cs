using System;
using System.IO;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.UART;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.SchedulerExperiment {
 public class SchedulingProbe:UARTBase,IDoubleWordPeripheral,IKnownSize,IGPIOReceiver,INumberedGPIOOutput {
 public SchedulingProbe(IMachine machine,int identity=0,int phase=1):base(machine){Connections=new ReadOnlyDictionary<int,IGPIO>(new Dictionary<int,IGPIO>{{0,Signal}});id=identity;m=machine;timer=new LimitTimer(machine.ClockSource,1000000,this,"ordering probe",(ulong)phase,direction:Direction.Ascending,workMode:WorkMode.Periodic,enabled:true,eventEnabled:true);timer.LimitReached+=Tick;}
 public IReadOnlyDictionary<int,IGPIO> Connections {get;private set;}
 public GPIO Signal {get;}=new GPIO();
 public override uint BaudRate{get{return 576000;}}public override Parity ParityBit{get{return Parity.None;}}public override Bits StopBits{get{return Bits.One;}}
 public long Size{get{return 4;}}public uint ReadDoubleWord(long o){return ticks;}public void WriteDoubleWord(long o,uint v){}
 protected override void CharWritten(){} protected override void QueueEmptied(){}
 public override void WriteChar(byte v){lock(rows){rows.Add(Now()+",uart,"+v);}}
 public void OnGPIO(int number,bool value){lock(rows){rows.Add(Now()+",gpio"+number+","+(value?1:0));}}
 ulong Now(){return (ulong)m.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds;}
 void Tick(){timer.Limit=31;ticks++;lock(rows){rows.Add(Now()+",timer,"+ticks);}Signal.Set((ticks&1)!=0);TransmitCharacter((byte)((id<<6)|(ticks%64)));}
 public void Export(string path){lock(rows){File.WriteAllLines(path,rows);}File.WriteAllText(path+".cpu",m.GetSystemBus(this).ReadDoubleWord(0x20000000).ToString());}
 readonly int id;readonly IMachine m;readonly LimitTimer timer;readonly List<string> rows=new List<string>();uint ticks;
 }
}
