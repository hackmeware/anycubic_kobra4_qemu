// SPDX-License-Identifier: MIT
// Passive observation of EVERY genuine coherent TMR8 endpoint. No producer,
// integration, drive, ADC, queued-target, synthetic force or clock mutation.
using System;
using System.Linq;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.PrinterMotor;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.SensorCrossBoard
{
 public sealed class Tmr8PublicSnapshotPublisher : IPeripheral, IGPIOReceiver, IDisposable
 {
  public sealed class Endpoint
  {
   internal Endpoint(ulong time, ulong sequence, double[] velocities)
   { Time=time; Sequence=sequence; this.velocities=(double[])velocities.Clone(); }
   public readonly ulong Time,Sequence;
   public double Velocity(int axis) { return velocities[axis]; }
   private readonly double[] velocities;
  }
  public sealed class Pair
  {
   internal Pair(Endpoint previous,Endpoint current,ulong publication)
   { Previous=previous; Current=current; PublicationTime=publication; }
   public readonly Endpoint Previous,Current;
   public readonly ulong PublicationTime;
  }
  public Tmr8PublicSnapshotPublisher(GenericStepperElectromechanical plant,AT32Timer tmr8)
  {
   if(plant==null || tmr8==null)throw new ArgumentNullException("plant/tmr8");
   this.plant=plant;this.tmr8=tmr8;
   emulation=EmulationManager.Instance.CurrentEmulation;master=emulation.MasterTimeSource;domain=master.Domain;
   IMachine owner;
   if(!emulation.TryGetMachineForPeripheral(plant,out owner))throw new InvalidOperationException("Plant must be registered.");
   SourceMachine=owner;ValidateMembership();RequirePaused();
   ValidateBoundary(master.ElapsedVirtualTime.TotalNanoseconds);
   lastTriggerCount=plant.TriggerCount;
   // Renode GPIO fanout must invoke the existing plant receiver first. At EACH
   // rising event require both its incremented trigger counter and its exact
   // current all-axis integration time. A wrong registration order fails closed.
   tmr8.TriggerOutput.Connect(this,0);connected=true;
   master.SyncHook+=Publish;subscribed=true;
  }
  public IMachine SourceMachine {get;private set;}
  public string Fault {get {lock(gate)return fault;}}
  public bool IsDisposed {get {lock(gate)return disposed;}}
  public bool IsConnected {get {lock(gate)return connected;}}
  public bool IsSubscribed {get {lock(gate)return subscribed;}}
  public ulong Captures {get;private set;}
  public ulong PublishedPairs {get;private set;}
  // More than one capture between boundaries is not lost adjacency: retain
  // the newest adjacent captured pair. Older pairs are visibly superseded.
  public ulong SupersededUnpublishedPairs {get;private set;}
  public ulong LastBoundary {get;private set;}
  public Pair Published {get {lock(gate)return fault==null && !disposed ? published : null;}}
  public ulong? LastCapturedTime {get {lock(gate)return current==null ? (ulong?)null : current.Time;}}
  public string[] RecentDiagnostics {get {lock(gate)return diagnostics.Where(x=>x!=null).ToArray();}}
  public ulong DiagnosticsOverwritten {get;private set;}
  public void OnGPIO(int number,bool value)
  {
   if(number!=0 || !value)return;
   lock(gate)
   {
    if(disposed || fault!=null)return;
    try
    {
     ValidateMembership();var clock=SourceMachine.ClockSource.CurrentValue.TotalNanoseconds;
     // The plant integrates at Machine.ElapsedVirtualTime. During TimePassed,
     // BaseClockSource.Advance can still be at an earlier timer substep. Exact
     // cross-clock equality is required at Publish, after clock fanout completes.
     var now=SourceMachine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds;
     var count=plant.TriggerCount;
     if(count!=checked(lastTriggerCount+1))throw new InvalidOperationException("TMR8 observer must follow exactly one genuine plant callback.");
     var v=new double[3];ulong time=0;
     for(int a=0;a<3;a++)
     {
      var before=plant.GetLastIntegrationTimeSeconds(a);v[a]=plant.GetVelocityRadiansPerSecond(a);var after=plant.GetLastIntegrationTimeSeconds(a);
      RigidTranslationConfiguration.RequireFinite(after);RigidTranslationConfiguration.RequireFinite(v[a]);
      if(before!=after || after<0 || after>=1048576.0)throw new InvalidOperationException("Unstable/out-of-range public endpoint timestamp.");
      var ns=after*1e9;var rounded=Math.Round(ns,MidpointRounding.AwayFromZero);
      if(Math.Abs(ns-rounded)>0.25)throw new InvalidOperationException("Ambiguous sub-nanosecond endpoint.");
      var endpoint=checked((ulong)rounded);
      ValidateCaptureTime(clock,now,endpoint);
      if(a!=0 && endpoint!=time)throw new InvalidOperationException("TMR8 capture must follow coherent all-axis integration at reported elapsed time.");
      time=endpoint;
     }
     if(SourceMachine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds!=now || SourceMachine.ClockSource.CurrentValue.TotalNanoseconds!=clock)
      throw new InvalidOperationException("Motor timing views changed during coherent capture.");
     if(current!=null && (time<=current.Time || time-current.Time>625000))throw new InvalidOperationException("Repeated/regressing/oversized adjacent coherent endpoint interval.");
     if(previous!=null && (published==null || published.Current.Sequence!=current.Sequence))SupersededUnpublishedPairs++;
     previous=current;current=new Endpoint(time,checked(Captures+1),v);lastTriggerCount=count;Captures++;
     Note("capture:"+time);
    }
    catch(Exception e){Latch(e.Message);}
   }
  }
  // Shared with deterministic evidence regressions in this source assembly.
  // Exact endpoint identity is phase-specific, never a numeric tolerance.
  internal static void ValidateCaptureTime(ulong clock,ulong elapsed,ulong endpoint)
  {
   if(clock>elapsed)throw new InvalidOperationException("Motor callback clock is ahead of reported elapsed time.");
   if(endpoint!=elapsed)throw new InvalidOperationException("TMR8 capture must follow coherent all-axis integration at reported elapsed time.");
  }
  private void Publish(TimeInterval time)
  {
   lock(gate)
   {
    if(disposed || fault!=null)return;
    try
    {
     if(!master.IsOnSyncPhaseThread)throw new InvalidOperationException("Only master sync-phase publication is supported.");
     ValidateMembership();var now=time.TotalNanoseconds;ValidateBoundary(now);
     if(now<LastBoundary)throw new InvalidOperationException("Master boundary regressed.");
     LastBoundary=now;
     // No manufactured time-zero baseline and no boot-time stale failure before
     // the FIRST genuine endpoint. After it, strict cadence is always armed.
     if(current==null)return;
     if(current.Time>now || now-current.Time>=625000)throw new InvalidOperationException("Coherent source endpoint stale/future at publication.");
     if(previous==null)return;
     if(published==null || published.Current.Sequence!=current.Sequence)
     { published=new Pair(previous,current,now);PublishedPairs++;Note("publish:"+current.Time+":"+now); }
     // Never retimestamp/re-publish a repeated immutable pair.
    }
    catch(Exception e){Latch(e.Message);}
   }
  }
  public void ValidateAcquisitionMembership(IMachine machine)
  {
   lock(gate)
   {
    if(disposed || fault!=null)throw new InvalidOperationException("Snapshot publisher is unavailable: "+fault);
    ValidateMembership();ValidateMachine(machine);
   }
  }
  public void ValidateAcquisitionBoundary(IMachine machine,ulong now)
  { lock(gate) { ValidateAcquisitionMembership(machine);ValidateBoundary(now);ValidateClock(machine,now); } }
  public void RequirePaused()
  {
   if(emulation.IsStarted || (emulation.Machines.Contains(SourceMachine) && !SourceMachine.IsPaused))throw new InvalidOperationException("Setup/teardown requires paused emulation.");
  }
  private void ValidateMachine(IMachine machine)
  {
   if(machine==null || !emulation.Machines.Contains(machine))throw new InvalidOperationException("Participating machine no longer belongs to the emulation.");
   if(!Object.ReferenceEquals(machine.LocalTimeSource,master) || !Object.ReferenceEquals(machine.LocalTimeSource.Domain,domain) || !Object.ReferenceEquals(machine.ElapsedVirtualTime.Domain,domain))
    throw new InvalidOperationException("Only exact identity-mapped common master/domain is supported.");
  }
  private void ValidateMembership()
  {
   if(!Object.ReferenceEquals(emulation,EmulationManager.Instance.CurrentEmulation))throw new InvalidOperationException("Current emulation changed.");
   if(master.Quantum.TotalNanoseconds!=1000)throw new InvalidOperationException("Exactly 1000 ns master quantum is required.");
   ValidateMachine(SourceMachine);IMachine owner;
   if(!emulation.TryGetMachineForPeripheral(plant,out owner) || !Object.ReferenceEquals(owner,SourceMachine))throw new InvalidOperationException("Registered plant owner changed.");
   if(!emulation.TryGetMachineForPeripheral(tmr8,out owner) || !Object.ReferenceEquals(owner,SourceMachine))throw new InvalidOperationException("TMR8 must remain registered to the plant's motor machine.");
  }
  private void ValidateBoundary(ulong now)
  {
   if(master.ElapsedVirtualTime.TotalNanoseconds!=now)throw new InvalidOperationException("Master boundary timestamp mismatch.");
   ValidateClock(SourceMachine,now);
  }
  private static void ValidateClock(IMachine machine,ulong now)
  { if(machine.ClockSource.CurrentValue.TotalNanoseconds!=now || machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds!=now)throw new InvalidOperationException("Participating clocks must equal the publication boundary."); }
  private void Latch(string reason){if(fault==null){fault=reason;Note("fault:"+reason);}}
  private void Note(string note){if(diagnostics[diagnosticIndex]!=null)DiagnosticsOverwritten++;diagnostics[diagnosticIndex]=note;diagnosticIndex=(diagnosticIndex+1)%diagnostics.Length;}
  // A native reset is never a re-prime or a way to erase source failure.
  public void Reset(){}
  public void Dispose()
  {
   lock(gate)
   {
    if(disposed)return;
    // No clock read is needed even after removal. The caller is responsible
    // for paused disposal before machine destruction; reject an active run.
    RequirePaused();
    if(subscribed){master.SyncHook-=Publish;subscribed=false;}
    if(connected){var endpoints=tmr8.TriggerOutput.Endpoints.Where(x=>Object.ReferenceEquals(x.Receiver,this) && x.Number==0).ToArray();
     foreach(var endpoint in endpoints)tmr8.TriggerOutput.Disconnect(endpoint);
     if(tmr8.TriggerOutput.Endpoints.Any(x=>Object.ReferenceEquals(x.Receiver,this)))throw new InvalidOperationException("Owned TMR8 receiver remains attached.");
     connected=false;}
    published=null;previous=current=null;disposed=true;
   }
  }
  private readonly GenericStepperElectromechanical plant;private readonly AT32Timer tmr8;
  private readonly Emulation emulation;private readonly MasterTimeSource master;private readonly ITimeDomain domain;
  private readonly object gate=new object();private readonly string[] diagnostics=new string[16];private int diagnosticIndex;
  private Endpoint previous,current;private Pair published;private ulong lastTriggerCount;private string fault;private bool connected,subscribed,disposed;
 }
}
