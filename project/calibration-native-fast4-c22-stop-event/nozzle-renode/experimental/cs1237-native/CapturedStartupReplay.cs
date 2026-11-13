// Replays captured original host bytes through the real UART peripheral, never firmware RAM.
using System;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.AT32;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.NozzleExperimental
{
 public class CapturedStartupReplay : IBusPeripheral
 {
  public CapturedStartupReplay(IMachine machine,AT32UART uart,uint interByteMicroseconds=200)
  {
   this.machine=machine;this.uart=uart;timer=new LimitTimer(machine.ClockSource,1000000,this,"captured UART",interByteMicroseconds,direction:Direction.Ascending,workMode:WorkMode.Periodic,enabled:false,eventEnabled:true);
   timer.LimitReached+=Tick;
  }
  public void Begin(string path){if(timer.Enabled)throw new InvalidOperationException("Replay already active");data=File.ReadAllBytes(path);index=0;timer.Value=0;timer.Enabled=true;}
  public void DumpMemory(string path) { File.WriteAllBytes(path,machine.GetSystemBus(this).ReadBytes(0x20000000,0x5000)); }
  public int BytesSent {get{return index;}}
  public void Reset(){timer.Enabled=false;}
  private void Tick(){if(index==data.Length){timer.Enabled=false;return;}uart.WriteChar(data[index++]);}
  private readonly IMachine machine;private readonly AT32UART uart;private readonly LimitTimer timer;private byte[] data;private int index;
 }
}
