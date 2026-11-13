// Passive evidence capture at sensor-fault PA6 edge, before invalid native read stops execution.
using System;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
namespace Antmicro.Renode.Peripherals.NozzleExperimental
{
 public class Cs1237FailureCapture : IBusPeripheral, IGPIOReceiver
 {
  public Cs1237FailureCapture(IMachine machine,Cs1237NativeGpio port,Cs1237NativeAdapter sensor,Cs1237StepFixture steps,string directory)
  {bus=machine.GetSystemBus(this);this.port=port;this.sensor=sensor;this.steps=steps;this.directory=directory;port.Connections[6].Connect(this,6);}
  public void Reset(){}
  public void OnGPIO(int number,bool level)
  {
   if(number!=6)throw new ArgumentException();
   if(saved || (sensor.Protocol.Errors==0 && sensor.AdapterErrors==0))return;
   saved=true;steps.Mark("fault-edge-before-native-invalid-read");steps.WriteTrace(Path.Combine(directory,"native-state.csv"));steps.WriteStimuli(Path.Combine(directory,"stimuli.csv"));sensor.WriteStatus(Path.Combine(directory,"sensor-status.json"));sensor.WriteTrace(Path.Combine(directory,"sensor.csv"));port.WriteTrace(Path.Combine(directory,"gpio.csv"));File.WriteAllBytes(Path.Combine(directory,"failure-sram.bin"),bus.ReadBytes(0x20000000,0x5000));File.WriteAllText(Path.Combine(directory,"failure-time-ns.txt"),port.Nanoseconds.ToString());
  }
  private readonly IBusController bus;private readonly Cs1237NativeGpio port;private readonly Cs1237NativeAdapter sensor;private readonly Cs1237StepFixture steps;private readonly string directory;private bool saved;
 }
}
