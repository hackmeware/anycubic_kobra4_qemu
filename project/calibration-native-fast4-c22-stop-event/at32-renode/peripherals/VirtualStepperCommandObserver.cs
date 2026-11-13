// SPDX-License-Identifier: MIT
// Passive STEP/DIR observation: commanded travel only, not a physical motor model.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.AT32
{
 public class VirtualStepperCommandObserver : IPeripheral, IGPIOReceiver
 {
  public VirtualStepperCommandObserver(IMachine machine, AT32GPIO stepPort, int stepPin,
   AT32GPIO directionPort, int directionPin, double stepsPerMillimeter,
   bool invertDirection = false, int maximumRows = 1000000, bool bothEdges = false)
  {
   if(stepPort==null || directionPort==null || stepPin<0 || stepPin>15 || directionPin<0 || directionPin>15
    || Double.IsNaN(stepsPerMillimeter) || Double.IsInfinity(stepsPerMillimeter) || stepsPerMillimeter<=0
    || maximumRows<1 || maximumRows>5000000) throw new ArgumentException("Invalid observation binding");
   scale=stepsPerMillimeter; reversed=invertDirection; maximum=maximumRows; this.bothEdges=bothEdges;
   clock=new LimitTimer(machine.ClockSource,1000000,this,"commanded step observation",ulong.MaxValue,
    direction:Direction.Ascending,enabled:true,eventEnabled:false);
   stepLevel=(stepPort.ReadDoubleWord(8)&(1u<<stepPin))!=0;
   directionLevel=(directionPort.ReadDoubleWord(8)&(1u<<directionPin))!=0;
   stepPort.Connections[stepPin].Connect(this,0); directionPort.Connections[directionPin].Connect(this,1);
   Add("attached");
  }
  // MCU reset is recorded; position does not teleport and counters do not clear.
  public void Reset() { Add("MCU_reset"); }
  public void OnGPIO(int number,bool value)
  {
   if(number==1) { directionLevel=value; return; }
   if(number!=0) throw new ArgumentOutOfRangeException("number");
   if(value!=stepLevel)
   {
    if(value) RisingEdges++; else FallingEdges++;
    if(bothEdges || value) { StepEvents++; SignedSteps+=(directionLevel^reversed)?1:-1; Add(value?"step_rise":"step_fall"); }
   }
   stepLevel=value;
  }
  public ulong RisingEdges { get; private set; }
  public ulong FallingEdges { get; private set; }
  public ulong StepEvents { get; private set; }
  public long SignedSteps { get; private set; }
  public double CommandedTravelMillimeters => SignedSteps/scale;
  public bool CapacityReached { get; private set; }
  public int RowCount => rows.Count;
  public string GetCsv() { return "time_us,rising_edges,falling_edges,step_events,signed_steps,commanded_travel_mm,direction_level,event\n"+String.Join("\n",rows)+"\n"; }
  public void WriteCsv(string path) { File.WriteAllText(path,GetCsv()); }
  private void Add(string kind)
  {
   if(rows.Count>=maximum) { CapacityReached=true; return; }
   rows.Add(clock.Value.ToString(CultureInfo.InvariantCulture)+","+RisingEdges+","+FallingEdges+","+StepEvents+","+SignedSteps+","+CommandedTravelMillimeters.ToString("R",CultureInfo.InvariantCulture)+","+(directionLevel?1:0)+","+kind);
  }
  private readonly double scale;private readonly bool reversed,bothEdges;private readonly int maximum;
  private bool stepLevel,directionLevel;private readonly LimitTimer clock;private readonly List<string> rows=new List<string>();
 }
}
