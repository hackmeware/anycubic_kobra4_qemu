// SPDX-License-Identifier: MIT
// Passive virtual GPIO observation, with no assignments of board-specific pin roles.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.AT32
{
 public class VirtualGPIOTrace : IPeripheral, IGPIOReceiver
 {
  public VirtualGPIOTrace(IMachine machine, AT32GPIO portA, AT32GPIO portB,
   AT32GPIO portC = null, AT32GPIO portD = null, AT32GPIO portE = null,
   AT32GPIO portF = null, AT32GPIO portG = null, int maximumRows = 1000000)
  {
   if(maximumRows < 1 || maximumRows > 5000000) throw new ArgumentOutOfRangeException("maximumRows");
   maximum=maximumRows; ports=new[]{portA,portB,portC,portD,portE,portF,portG};
   clock=new LimitTimer(machine.ClockSource,1000000,this,"passive GPIO trace clock",ulong.MaxValue,
    direction:Direction.Ascending,enabled:true,eventEnabled:false);
   for(int p=0;p<ports.Length;p++) if(ports[p]!=null)
    for(int bit=0;bit<16;bit++)
    {
     levels[p*16+bit]=(ports[p].ReadDoubleWord(8)&(1u<<bit))!=0;
     ports[p].Connections[bit].Connect(this,p*16+bit);
    }
   Mark("trace_attached");
  }
  public int RowCount => rows.Count;
  public bool CapacityReached { get; private set; }
  public void Reset() { Mark("MCU_reset"); }
  public void Clear() { rows.Clear(); CapacityReached=false; Mark("trace_cleared"); }
  public void OnGPIO(int number,bool value)
  {
   if(number<0 || number>=112) throw new ArgumentOutOfRangeException("number");
   if(levels[number]==value) return;
   levels[number]=value; Add(number,value,"edge");
  }
  public void Mark(string label)
  {
   label=(label??"").Replace(',',';').Replace('\r',' ').Replace('\n',' ');
   for(int p=0;p<ports.Length;p++) if(ports[p]!=null)
    for(int bit=0;bit<16;bit++) Add(p*16+bit,(ports[p].ReadDoubleWord(8)&(1u<<bit))!=0,"snapshot:"+label);
  }
  public string GetCsv() { return "time_us,pin,level,configuration_nibble,output_latch,event\n"+String.Join("\n",rows)+"\n"; }
  public void WriteCsv(string path) { File.WriteAllText(path,GetCsv()); }
  private void Add(int number,bool level,string kind)
  {
   if(rows.Count>=maximum) { CapacityReached=true; return; }
   var p=number/16; var bit=number%16; if(ports[p]==null) return;
   var configuration=(ports[p].ReadDoubleWord(bit<8?0:4)>>(4*(bit%8)))&15;
   var latch=(ports[p].ReadDoubleWord(12)>>bit)&1;
   rows.Add(clock.Value.ToString(CultureInfo.InvariantCulture)+",P"+((char)('A'+p))+bit+","+(level?"1":"0")+","+configuration+","+latch+","+kind);
  }
  private readonly bool[] levels=new bool[112];
  private readonly AT32GPIO[] ports;
  private readonly LimitTimer clock;
  private readonly int maximum;
  private readonly List<string> rows=new List<string>();
 }
}
