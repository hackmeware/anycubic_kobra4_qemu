// SPDX-License-Identifier: MIT
using System;
using Antmicro.Renode.Peripherals;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
 public class ObserverTests : IPeripheral
 {
  public ObserverTests(VirtualPrinterObserver observer, VirtualPrinterAxis axis, VirtualPrinterThermal thermal) { o=observer; a=axis; h=thermal; }
  public void Reset() { }
  public void Drive() { a.OnGPIO(2,false);a.OnGPIO(1,true);for(int i=0;i<80;i++){a.OnGPIO(0,false);a.OnGPIO(0,true);} h.SetDutyCycle(0.5); }
  public string Check()
  {
   if(o.SampleCount!=11) throw new Exception("virtual-time sample count "+o.SampleCount);
   if(a.PositionMillimeters<10.99 || h.TemperatureCelsius<=25) throw new Exception("components did not evolve");
   var rows=o.GetCsv().Trim().Split('\n');
   if(rows[2].Split(',').Length!=29 || rows[rows.Length-1].Split(',').Length!=29) throw new Exception("CSV width");
   if(!rows[2].StartsWith("0,10,0,0,0,")) throw new Exception("initial state");
   if(!rows[rows.Length-1].Contains(",80,1,0,")) throw new Exception("GPIO step observation");
   if(o.GetCsv().Contains("NaN")) throw new Exception("invalid numeric output");
   o.Stop();if(o.Recording)throw new Exception("stop failed");
   return "OBSERVER TESTS PASS";
  }
  public string CheckCapacity() { if(o.SampleCount!=12 || !o.CapacityReached || o.Recording)throw new Exception("bounded trace failed");return "OBSERVER CAPACITY PASS"; }
  public void Restart() { o.Reset(); }
  private readonly VirtualPrinterObserver o;private readonly VirtualPrinterAxis a;private readonly VirtualPrinterThermal h;
 }
}
