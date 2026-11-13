// SPDX-License-Identifier: MIT
// Optional passive GPIO observer. No GPIO, firmware, clock or plant writes.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.GPIOPort;
namespace Antmicro.Renode.Peripherals.PrinterShared
{
 public sealed class PassiveGpioEdgeTrace : IPeripheral, IGPIOReceiver, IDisposable
 {
  public PassiveGpioEdgeTrace(IMachine machine,int maximumRows=100000)
  {
   if(maximumRows<1||maximumRows>1000000)throw new ArgumentOutOfRangeException("maximumRows");
   this.machine=machine;maximum=maximumRows;
  }
  // Explicit finite opt-in. One recording per instance; never rotate/reset counters.
  // 10M rows / 1GiB are implementation ceilings, not an admitted run budget.
  public void ConfigureLongRun(long maximumRows,long maximumBytes)
  {
   if(started||writer!=null)throw new InvalidOperationException("Configure before first Start");
   if(maximumRows<1||maximumRows>10000000)throw new ArgumentOutOfRangeException("maximumRows");
   if(maximumBytes<4096||maximumBytes>1073741824L)throw new ArgumentOutOfRangeException("maximumBytes");
   if(signals.Count>16)throw new ArgumentException("Long-run trace permits at most 16 signals");
   foreach(var s in signals)CheckLongRunSignal(s.Pin,s.Label);
   maximum=maximumRows;byteMaximum=maximumBytes;longRun=true;
  }
  private void CheckLongRunSignal(int pin,string label)
  {
   if(pin<0||pin>15||label.Length>64)throw new ArgumentException("Long-run pin/label bound");
   foreach(char c in label)if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'))throw new ArgumentException("Long-run label must be ASCII identifier");
  }
  // Attach only before Start, in the source machine. Each trace has its own local clock.
  public void Observe(BaseGPIOPort source,int pin,string label)
  {
   if(writer!=null||(longRun&&started))throw new InvalidOperationException("Stop before adding sources; long-run sources are immutable after Start");
   if(source==null||!source.Connections.ContainsKey(pin))throw new ArgumentException("Unknown GPIO pin");
   if(string.IsNullOrWhiteSpace(label)||label.IndexOfAny(new[]{',','\r','\n','"'})>=0)throw new ArgumentException("Use a plain CSV-safe label");
   if(longRun){CheckLongRunSignal(pin,label);if(signals.Count>=16)throw new ArgumentException("Long-run trace permits at most 16 signals");}
   foreach(var s in signals)if(s.Label==label||(s.Source==source&&s.Pin==pin))throw new ArgumentException("Duplicate source or label");
   var signal=new Signal{Source=source,Pin=pin,Label=label,Level=source.Connections[pin].IsSet};
   int index=signals.Count;signals.Add(signal);source.Connections[pin].Connect(this,index);
   signal.Level=source.Connections[pin].IsSet;
  }
  public void Start(string outputPath)
  {
   if(writer!=null||(longRun&&started))throw new InvalidOperationException("Already recording or long-run recording already used");
   if(signals.Count==0)throw new InvalidOperationException("Observe at least one source first");
   writer=new StreamWriter(new FileStream(outputPath,FileMode.CreateNew,FileAccess.Write,FileShare.Read),new UTF8Encoding(false));
   RowsWritten=0;DroppedRows=0;EdgeCount=0;BytesWritten=0;LastError="";byteCapacity=false;started=true;capturing=true;
   if(longRun)writer.NewLine="\n";
   try
   {
    WriteLine("# PASSIVE GPIO EDGE TRACE v1; source-local virtual timestamps; no SyncTime or signal writes");
    WriteLine("virtual_time_s,sequence,kind,label,pin,level");
    foreach(var s in signals){s.Level=s.Source.Connections[s.Pin].IsSet;Record(s,"initial");}
    if(writer!=null)writer.Flush();
   }
   catch(Exception e){Fail(e);throw;}
  }
  private void WriteLine(string line)
  {
   writer.WriteLine(line);writer.Flush();BytesWritten+=Encoding.UTF8.GetByteCount(line)+Encoding.UTF8.GetByteCount(writer.NewLine);
  }
  public void OnGPIO(int number,bool value)
  {
   if(number<0||number>=signals.Count)return;
   var s=signals[number];if(s.Level==value)return;s.Level=value;
   if(writer==null&&!(longRun&&capturing))return;
   EdgeCount++;Record(s,"edge");
  }
  private void Record(Signal s,string kind)
  {
   if(writer==null){if(longRun&&capturing)DroppedRows++;return;}
   if(RowsWritten>=maximum||byteCapacity){DroppedRows++;return;}
   try
   {
    string row=machine.ElapsedVirtualTime.TimeElapsed.TotalSeconds.ToString("R",CultureInfo.InvariantCulture)+","+RowsWritten.ToString(CultureInfo.InvariantCulture)+","+kind+","+s.Label+","+s.Pin+","+(s.Level?"1":"0");
    if(longRun&&BytesWritten+Encoding.UTF8.GetByteCount(row)+1>byteMaximum){byteCapacity=true;DroppedRows++;return;}
    WriteLine(row);RowsWritten++;
   }
   catch(Exception e){if(longRun)DroppedRows++;Fail(e);}
  }
  private void Fail(Exception e)
  {
   if(LastError=="")LastError=e.GetType().Name+": "+e.Message;
   // Retain active-session edge/drop accounting after IO failure in opt-in mode.
   CloseWriter();if(!longRun)capturing=false;
  }
  private void CloseWriter()
  {
   var w=writer;writer=null;if(w!=null){try{w.Dispose();}catch(Exception e){if(LastError=="")LastError=e.GetType().Name+": "+e.Message;}}
  }
  public void Stop(){capturing=false;CloseWriter();}
  // Paused caller stops first; immutable sidecar is a final recording receipt.
  // Missing/partial receipts, error strings, caps and counter mismatch fail audit.
  public void WriteStatus(string path)
  {
   if(!longRun||!started||capturing||Enabled)throw new InvalidOperationException("Stop a long-run recording before final status");
   using(var w=new StreamWriter(new FileStream(path,FileMode.CreateNew,FileAccess.Write,FileShare.Read),new UTF8Encoding(false)))
   {
    w.Write("{\"schema\":1,\"enabled\":false,\"rows_written\":"+RowsWritten+",\"edge_count\":"+EdgeCount+",\"dropped_rows\":"+DroppedRows+",\"bytes_written\":"+BytesWritten+",\"maximum_rows\":"+maximum+",\"maximum_bytes\":"+byteMaximum+",\"capacity_reached\":"+(CapacityReached?"true":"false")+",\"last_error\":\"");
    foreach(char c in LastError){if(c=='"'||c=='\\')w.Write('\\');if(c<32)w.Write("\\u"+((int)c).ToString("x4"));else w.Write(c);}
    w.Write("\"}\n");
   }
  }
  public void Reset(){Stop();} // Never reset the observed pins or clock.
  public void Dispose(){Stop();}
  public bool Enabled=>writer!=null;
  public long RowsWritten{get;private set;}
  public long DroppedRows{get;private set;}
  public long EdgeCount{get;private set;}
  public long BytesWritten{get;private set;}
  public long MaximumRows=>maximum;
  public long MaximumBytes=>byteMaximum;
  public bool CapacityReached=>RowsWritten>=maximum||byteCapacity||(longRun&&BytesWritten>=byteMaximum);
  public string LastError{get;private set;}="";
  private class Signal{public BaseGPIOPort Source;public int Pin;public string Label;public bool Level;}
  private readonly IMachine machine;private long maximum,byteMaximum;private bool longRun,started,capturing,byteCapacity;
  private readonly List<Signal> signals=new List<Signal>();private StreamWriter writer;
 }
}
