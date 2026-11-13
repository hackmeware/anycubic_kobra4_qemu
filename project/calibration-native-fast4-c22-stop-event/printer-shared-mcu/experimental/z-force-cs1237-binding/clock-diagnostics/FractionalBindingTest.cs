// Actual cross-machine bound provider called by a fractional peripheral deadline, no CPUs/firmware.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.NozzleExperimental;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.PrinterExperimental
{
 public sealed class FractionalBindingTest : IPeripheral
 {
  public FractionalBindingTest(IMachine machine)
  {
   this.machine=machine;port=new Cs1237NativeGpio(machine);sensor=new Cs1237FunctionalAdapter(machine,port,0,idealizedElectricalSemantics:true);
   binding=new Cs1237ZForceBinding(machine,port,sensor,"z-traced");
   deadline=new LimitTimer(machine.ClockSource,1000000000,this,"fractional bound callback",1234,direction:Direction.Ascending,workMode:WorkMode.OneShot,enabled:true,eventEnabled:true);
   deadline.LimitReached+=()=>{Calls++;PortTime=port.Nanoseconds;PeripheralTime=(long)machine.ClockSource.CurrentValue.TotalNanoseconds;MachineTime=(long)machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds;try{Code=sensor.TimedSource(1234);}catch(Exception e){Failure=e.Message;}};
  }
  public string Report(bool expectSuccess)
  {
   if(Calls!=1||PortTime!=1234||PeripheralTime!=1234||MachineTime!=2000)throw new Exception("Fractional callback setup did not reproduce expected distinct clocks");
   if(expectSuccess && (Failure!=""||Code!=0))throw new Exception("Exact peripheral-time binding rejected valid callback: "+Failure);
   if(!expectSuccess && !Failure.Contains("does not match nozzle-machine epoch"))throw new Exception("Pre-fix binding unexpectedly accepted known fractional mismatch");
   return "Z FRACTIONAL BINDING TEST "+(expectSuccess?"PASS":"EXPECTED PRE-FIX FAILURE")+": port="+PortTime+" peripheral="+PeripheralTime+" machine="+MachineTime+" code="+Code+" failure="+Failure;
  }
  public void Reset(){}
  public int Calls{get;private set;} public long PortTime{get;private set;} public long PeripheralTime{get;private set;} public long MachineTime{get;private set;} public int Code{get;private set;}
  public string Failure{get;private set;}="";
  private readonly IMachine machine;private readonly Cs1237NativeGpio port;private readonly Cs1237FunctionalAdapter sensor;private readonly Cs1237ZForceBinding binding;private readonly LimitTimer deadline;
 }
}
