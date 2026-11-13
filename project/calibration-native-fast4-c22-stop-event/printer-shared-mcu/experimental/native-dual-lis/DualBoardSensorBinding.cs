// SPDX-License-Identifier: MIT
// Prepare-only composition; no fixture host, driver, pin stimuli or register writes.
using System;
using System.Linq;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.PrinterMotor;
using MainGpio=Antmicro.Renode.Peripherals.PrinterMain.AT32GPIO;
using NozzleGpio=Antmicro.Renode.Peripherals.PrinterNozzle.AT32GPIO;
using MainBridge=Antmicro.Renode.Peripherals.SensorGpioBridgePrinterMain.GpioMode3Lis2dw12Bridge;
using NozzleBridge=Antmicro.Renode.Peripherals.SensorGpioBridgePrinterNozzle.GpioMode3Lis2dw12Bridge;
namespace Antmicro.Renode.Peripherals.SensorCrossBoard
{
 public sealed class DualBoardSensorBinding : IPeripheral,IDisposable
 {
  public DualBoardSensorBinding(IMachine mainMachine,MainGpio mainGpio,IMachine nozzleMachine,NozzleGpio nozzleGpio,
   GenericStepperElectromechanical motorPlant,AT32Timer motorTmr8,RigidTranslationConfiguration mainMapping,RigidTranslationConfiguration nozzleMapping)
  {
   emulation=EmulationManager.Instance.CurrentEmulation;
   if(emulation.IsStarted || !mainMachine.IsPaused || !nozzleMachine.IsPaused || Object.ReferenceEquals(mainMachine,nozzleMachine))throw new InvalidOperationException("Two distinct paused acquisition machines required.");
   IMachine owner;
   if(!emulation.TryGetMachineForPeripheral(mainGpio,out owner) || !Object.ReferenceEquals(owner,mainMachine) || !emulation.TryGetMachineForPeripheral(nozzleGpio,out owner) || !Object.ReferenceEquals(owner,nozzleMachine))throw new InvalidOperationException("Both GPIOB instances require their actual registered MCU owners.");
   this.mainMachine=mainMachine;this.nozzleMachine=nozzleMachine;
   try
   {
    Publisher=new Tmr8PublicSnapshotPublisher(motorPlant,motorTmr8);
    MainInput=new PublishedSnapshotAccelerationInput(mainMachine,Publisher,mainMapping);
    NozzleInput=new PublishedSnapshotAccelerationInput(nozzleMachine,Publisher,nozzleMapping);
    MainSensor=new TimedLis2dw12(mainMachine,MainInput);NozzleSensor=new TimedLis2dw12(nozzleMachine,NozzleInput);
    mainBridge=new MainBridge(mainGpio,MainSensor);nozzleBridge=new NozzleBridge(nozzleGpio,NozzleSensor);
    motorMachine=Publisher.SourceMachine;
    foreach(var m in new[]{mainMachine,nozzleMachine,motorMachine})m.StateChanged+=OnMachineStateChanged;
    lifecycleHooksAttached=true;
   }
   catch { Dispose();throw; }
  }
  public Tmr8PublicSnapshotPublisher Publisher {get;private set;}
  public PublishedSnapshotAccelerationInput MainInput {get;private set;}
  public PublishedSnapshotAccelerationInput NozzleInput {get;private set;}
  public TimedLis2dw12 MainSensor {get;private set;}
  public TimedLis2dw12 NozzleSensor {get;private set;}
  public bool IsDisposed {get {return disposed;}}
  public bool LifecycleHooksAttached {get {return lifecycleHooksAttached;}}
  public ulong LifecycleTeardowns {get;private set;}
  private void OnMachineStateChanged(IMachine machine,MachineStateChangedEventArgs args)
  {
   if(args.CurrentState!=MachineStateChangedEventArgs.State.Disposed || disposed)return;
   // Verified public Machine lifecycle callback occurs after GPIO disconnect,
   // before its clock is destroyed. No private state or exception suppression.
   disposingMachine=machine;
   try { Dispose();LifecycleTeardowns++; }
   finally { disposingMachine=null; }
  }
  public void Reset()
  {
   if(disposed)return;
   RequirePaused();
   if(mainClockRemoved || nozzleClockRemoved || !emulation.Machines.Contains(mainMachine) || !emulation.Machines.Contains(nozzleMachine))throw new InvalidOperationException("Cannot reset after partial cleanup or machine removal.");
   MainSensor.Reset();NozzleSensor.Reset();
   // No source Reset, driver.Stop, re-prime or fault recovery.
  }
  public void Dispose()
  {
   if(disposed)return;
   RequirePaused();
   // Preferred lifecycle: dispose before destroying clocks. If public
   // Emulation.RemoveMachine already destroyed a machine, membership absence
   // prevents ALL access to that dead clock; remaining owned hooks still detach.
   // Repeated successful disposal never touches a clock.
   if(mainBridge!=null)mainBridge.Dispose();if(nozzleBridge!=null)nozzleBridge.Dispose();
   if(MainSensor!=null && !mainClockRemoved){if(emulation.Machines.Contains(mainMachine) || Object.ReferenceEquals(disposingMachine,mainMachine))RemoveSensorClock(mainMachine,MainSensor);mainClockRemoved=true;}
   if(NozzleSensor!=null && !nozzleClockRemoved){if(emulation.Machines.Contains(nozzleMachine) || Object.ReferenceEquals(disposingMachine,nozzleMachine))RemoveSensorClock(nozzleMachine,NozzleSensor);nozzleClockRemoved=true;}
   if(MainInput!=null)MainInput.Dispose();if(NozzleInput!=null)NozzleInput.Dispose();if(Publisher!=null)Publisher.Dispose();
   if(lifecycleHooksAttached){foreach(var m in new[]{mainMachine,nozzleMachine,motorMachine})m.StateChanged-=OnMachineStateChanged;lifecycleHooksAttached=false;}
   disposed=true;
  }
  private static void RemoveSensorClock(IMachine machine,TimedLis2dw12 sensor)
  {
   var owned=machine.ClockSource.GetAllClockEntries().Where(e=>Object.ReferenceEquals(e.Owner,sensor)).ToArray();
   if(owned.Length==0)return; // Already absent after a partial public-API cleanup.
   // Remove the physical acquisition entry directly. Resetting LimitTimer
   // would request a CPU context and touch a SystemBus already disposed during
   // Machine.Dispose callbacks. Transport was already finished by the bridge.
   foreach(var entry in owned)
    if(!machine.ClockSource.TryRemoveClockEntry(entry.Handler))throw new InvalidOperationException("Owned sensor clock entry removal failed.");
   if(machine.ClockSource.GetAllClockEntries().Any(e=>Object.ReferenceEquals(e.Owner,sensor)))throw new InvalidOperationException("Owned sensor clock entry remains.");
  }
  private void RequirePaused()
  { if(emulation.IsStarted || (emulation.Machines.Contains(mainMachine) && !mainMachine.IsPaused) || (emulation.Machines.Contains(nozzleMachine) && !nozzleMachine.IsPaused) || (motorMachine!=null && emulation.Machines.Contains(motorMachine) && !motorMachine.IsPaused))throw new InvalidOperationException("Pause all machines before sensor reset/disposal."); }
  private readonly Emulation emulation;private readonly IMachine mainMachine,nozzleMachine;
  private IMachine motorMachine,disposingMachine;private MainBridge mainBridge;private NozzleBridge nozzleBridge;private bool disposed,mainClockRemoved,nozzleClockRemoved,lifecycleHooksAttached;
 }
}
