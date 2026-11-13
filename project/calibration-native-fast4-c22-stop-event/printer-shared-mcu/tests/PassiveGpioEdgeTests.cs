using System;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.PrinterShared
{
 public class PassiveGpioEdgeTests : IPeripheral,IGPIOReceiver
 {
  public PassiveGpioEdgeTests(IMachine machine,AT32GPIO gpio){this.machine=machine;this.gpio=gpio;}
  public void Reset(){}
  public void OnGPIO(int n,bool v){deliveries++;last=v;}
  private void Check(bool ok,string why){if(!ok)throw new Exception(why);checks++;}
  public string Run(string path)
  {
   gpio.OnGPIO(13,true);gpio.Connections[13].Connect(this,0);int before=deliveries;
   var trace=new PassiveGpioEdgeTrace(machine,4);trace.Observe(gpio,13,"main_PC13");trace.Observe(gpio,6,"main_PA6_label_only");
   uint idt= gpio.ReadDoubleWord(8);var start=machine.ElapsedVirtualTime.TimeElapsed;
   trace.Start(path);Check(gpio.ReadDoubleWord(8)==idt,"initial snapshot leaves pins unchanged");Check(trace.RowsWritten==2,"two initial rows");
   gpio.OnGPIO(13,true);Check(trace.EdgeCount==0,"same level not an edge");
   gpio.OnGPIO(13,false);gpio.OnGPIO(13,true);Check(trace.EdgeCount==2,"both same-time pulse edges captured");Check(deliveries==before+2&&last,"existing receiver preserved");
   Check(trace.RowsWritten==4&&trace.CapacityReached,"bounded row capacity");
   gpio.OnGPIO(13,false);Check(trace.EdgeCount==3&&trace.DroppedRows==1,"overflow counted without changing input");Check((gpio.ReadDoubleWord(8)&8192)==0,"overflow does not suppress actual signal");
   Check(machine.ElapsedVirtualTime.TimeElapsed.Equals(start),"observer never advances time");trace.Stop();Check(!trace.Enabled,"stop closes writer");
   string[] rows=File.ReadAllLines(path);Check(rows.Length==6,"bounded csv lines");Check(rows[2].EndsWith(",initial,main_PC13,13,1"),"snapshot actual initial high despite attachment semantics");Check(rows[4].EndsWith(",edge,main_PC13,13,0")&&rows[5].EndsWith(",edge,main_PC13,13,1"),"edge ordering preserved");
   bool refused=false;try{trace.Start(path);}catch(IOException){refused=true;}Check(refused,"no overwrite");
   trace.Reset();Check((gpio.ReadDoubleWord(8)&8192)==0,"reset does not change GPIO");trace.Dispose();
   return "PASSIVE GPIO EDGE TESTS PASS: "+checks;
  }
  private IMachine machine;private AT32GPIO gpio;private int checks,deliveries;private bool last;
 }
}
