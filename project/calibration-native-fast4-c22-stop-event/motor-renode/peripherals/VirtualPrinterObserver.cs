// SPDX-License-Identifier: MIT
// Read-only, bounded virtual-time observation. No host/hardware connections.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.AT32
{
 public class VirtualPrinterObserver : IPeripheral
 {
  public VirtualPrinterObserver(IMachine machine, VirtualPrinterAxis axisA = null,
   VirtualPrinterAxis axisB = null, VirtualPrinterAxis axisZ = null, VirtualPrinterAxis extruder = null,
   VirtualPrinterThermal hotend = null, VirtualPrinterThermal bed = null,
   uint sampleMicroseconds = 100000, int maximumSamples = 100000,
   string sourceLabel = "unverified bindings")
  {
   if(sampleMicroseconds==0 || maximumSamples<1 || maximumSamples>1000000) throw new ArgumentOutOfRangeException();
   a=axisA; b=axisB; z=axisZ; e=extruder; h=hotend; this.bed=bed;
   period=sampleMicroseconds/1000000.0; maximum=maximumSamples;
   SourceLabel=(sourceLabel??"unverified bindings").Replace('\r',' ').Replace('\n',' ');
   timer=new LimitTimer(machine.ClockSource,1000000,this,"virtual printer observation",sampleMicroseconds,
    direction:Direction.Ascending,workMode:WorkMode.Periodic,enabled:true,eventEnabled:true);
   timer.LimitReached+=Tick; Reset();
  }
  public string SourceLabel { get; private set; }
  public int SampleCount => rows.Count;
  public bool CapacityReached { get; private set; }
  public bool Recording => timer.Enabled;
  // Reset starts a new trace, never modifies the sampled models.
  public void Reset() { rows.Clear(); ticks=0; CapacityReached=false; timer.Reset(); timer.Value=0; timer.Enabled=true; Capture(); }
  public void Stop() { timer.Enabled=false; }
  public string GetCsv() { return "# source: "+SourceLabel+"\n"+Header+"\n"+String.Join("\n",rows)+"\n"; }
  public void WriteCsv(string path) { File.WriteAllText(path,GetCsv()); }
  private void Tick() { ticks++; Capture(); }
  private void Capture()
  {
   if(rows.Count>=maximum) { CapacityReached=true; timer.Enabled=false; return; }
   rows.Add(F(ticks*period)+","+Axis(a)+","+Axis(b)+","+Axis(z)+","+Axis(e)+","+Thermal(h)+","+Thermal(bed));
  }
  private static string Axis(VirtualPrinterAxis v) { return v==null ? ",,," : F(v.PositionMillimeters)+","+v.TotalStepPulses+","+(v.Enabled?"1":"0")+","+v.LimitCollisionCount; }
  private static string Thermal(VirtualPrinterThermal v) { return v==null ? ",,,,," : F(v.TemperatureCelsius)+","+v.ADCValue+","+F(v.LastHeaterDuty)+","+F(v.LastFanDuty)+","+v.SensorFault+","+(v.HeaterLatchedOff?"1":"0"); }
  private static string F(double v) { return v.ToString("R",CultureInfo.InvariantCulture); }
  private const string Header="time_s,a_mm,a_steps,a_enabled,a_collisions,b_mm,b_steps,b_enabled,b_collisions,z_mm,z_steps,z_enabled,z_collisions,e_mm,e_steps,e_enabled,e_collisions,hotend_c,hotend_adc,hotend_duty,hotend_fan,hotend_fault,hotend_latched,bed_c,bed_adc,bed_duty,bed_fan,bed_fault,bed_latched";
  private readonly VirtualPrinterAxis a,b,z,e;
  private readonly VirtualPrinterThermal h,bed;
  private readonly LimitTimer timer;
  private readonly double period;
  private readonly int maximum;
  private ulong ticks;
  private readonly List<string> rows=new List<string>();
 }
}
