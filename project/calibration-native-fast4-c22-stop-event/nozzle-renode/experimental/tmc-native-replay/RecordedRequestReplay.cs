using System;
using System.IO;
using System.Globalization;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.AT32;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.NozzleTests {
 public class RecordedRequestReplay:IDoubleWordPeripheral,IKnownSize {
 public RecordedRequestReplay(IMachine machine, AT32GPIO gpio){g=gpio;timer=new LimitTimer(machine.ClockSource,1000000000,this,"recorded GPIO requests",1,direction:Direction.Ascending,workMode:WorkMode.OneShot,enabled:false,eventEnabled:true);timer.LimitReached+=Next;}
 public long Size{get{return 4;}}public void Reset(){} public uint ReadDoubleWord(long o){return 0;}public void WriteDoubleWord(long o,uint v){}
 public void Load(string path){events=File.ReadAllLines(path);index=0;previous=0;Next();}
 void Next(){if(index>=events.Length)return;var p=events[index].Split(',');var ns=ulong.Parse(p[0],CultureInfo.InvariantCulture);if(ns>previous){timer.Limit=ns-previous;timer.Value=0;timer.Enabled=true;previous=ns;return;}var kind=p[1];if(kind=="start"){g.WriteDoubleWord(0xc,8);g.WriteDoubleWord(0,0x44441444);}else if(kind=="release")g.WriteDoubleWord(0,0x44444444);else g.WriteDoubleWord(0xc,kind=="1"?8u:0u);index++;Next();}
 readonly AT32GPIO g;readonly LimitTimer timer;string[] events;int index;ulong previous;
 }
}
