// SPDX-License-Identifier: MIT
// Per-acquisition-machine consumer. Only sync phase transforms immutable captured
// pairs; SampleAt never reads or advances the live remote plant.
using System;
using System.Linq;
using Antmicro.Renode.Core;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.SensorCrossBoard
{
 public sealed class PublishedSnapshotAccelerationInput : IPeripheral,ICausalAccelerationSource,IDisposable
 {
  public PublishedSnapshotAccelerationInput(IMachine acquisitionMachine,Tmr8PublicSnapshotPublisher publisher,RigidTranslationConfiguration configuration)
  {
   if(acquisitionMachine==null || publisher==null || configuration==null)throw new ArgumentNullException("machine/publisher/configuration");
   AcquisitionMachine=acquisitionMachine;this.publisher=publisher;config=configuration;
   emulation=EmulationManager.Instance.CurrentEmulation;master=emulation.MasterTimeSource;
   publisher.ValidateAcquisitionMembership(acquisitionMachine);publisher.RequirePaused();
   if(!acquisitionMachine.IsPaused)throw new InvalidOperationException("Register input while paused.");
   publisher.ValidateAcquisitionBoundary(acquisitionMachine,master.ElapsedVirtualTime.TotalNanoseconds);
   master.SyncHook+=Publish;subscribed=true;
  }
  public IMachine AcquisitionMachine {get;private set;}
  // Fail a premature native enable visibly, but mere boot-time absence while
  // inactive does not create a zero frame or latch an unrelated source fault.
  public bool HasValue {get {lock(gate)return !disposed && fault==null && publisher.Fault==null && !publisher.IsDisposed && force!=null;}}
  public string Fault {get {lock(gate)return fault ?? publisher.Fault;}}
  public bool IsDisposed {get {lock(gate)return disposed;}}
  public bool IsSubscribed {get {lock(gate)return subscribed;}}
  public ulong PublishedDerivatives {get;private set;}
  public ulong OutputSamples {get;private set;}
  public ulong PreviousSourceNanoseconds {get;private set;}
  public ulong LastSourceNanoseconds {get;private set;}
  public ulong LastSourceAgeNanoseconds {get;private set;}
  public ulong LastDerivativeIntervalNanoseconds {get;private set;}
  public ulong LastAcquisitionNanoseconds {get;private set;}
  public ulong LastPublicationNanoseconds {get;private set;}
  public AccelerationVector LastSpecificForceG {get;private set;}
  private void Publish(TimeInterval time)
  {
   lock(gate)
   {
    if(disposed || fault!=null)return;
    try
    {
     if(!master.IsOnSyncPhaseThread)throw new InvalidOperationException("Input publication requires sync phase.");
     var now=time.TotalNanoseconds;publisher.ValidateAcquisitionBoundary(AcquisitionMachine,now);
     var next=publisher.Published;if(next==null)return;
     if(next.PublicationTime>now || next.Current.Time>now || now-next.Current.Time>config.MaximumAge)
      throw new InvalidOperationException("Published source pair is future/stale.");
     if(frame!=null && next.Current.Sequence==frame.Current.Sequence)return;
     var interval=next.Current.Time-next.Previous.Time;
     if(next.Current.Time<=next.Previous.Time || interval>config.MaximumInterval)throw new InvalidOperationException("Invalid adjacent derivative interval.");
     var a=new double[3];
     foreach(var axis in config.Axes)if(axis<0 || axis>2)throw new InvalidOperationException("Invalid selected axis.");
     for(int c=0;c<config.Axes.Length;c++)
     {
      var axis=config.Axes[c];var alpha=(next.Current.Velocity(axis)-next.Previous.Velocity(axis))/(interval*1e-9);
      RigidTranslationConfiguration.RequireFinite(alpha);
      for(int r=0;r<3;r++)a[r]+=config.Jacobian[r,c]*alpha;
     }
     var f=new decimal[3];
     for(int r=0;r<3;r++)
     {
      double value=0;for(int k=0;k<3;k++)value+=config.Rotation[r,k]*(a[k]-config.Gravity[k])/config.G0;
      RigidTranslationConfiguration.RequireFinite(value);f[r]=checked((decimal)value);
     }
     force=new AccelerationVector(f[0],f[1],f[2]);frame=next;derivedAt=now;PublishedDerivatives++;
    }
    catch(Exception e){if(fault==null)fault=e.Message;}
   }
  }
  public AccelerationVector SampleAt(ulong nanoseconds)
  {
   lock(gate)
   {
    try
    {
     if(!HasValue)throw new InvalidOperationException("No healthy published derivative is ready: "+Fault);
     publisher.ValidateAcquisitionMembership(AcquisitionMachine);
     var now=AcquisitionMachine.ClockSource.CurrentValue.TotalNanoseconds;
     if(now!=nanoseconds || now!=AcquisitionMachine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds || (hasRequest && now<=lastRequest))throw new InvalidOperationException("Require strictly newer exact acquisition clock/elapsed instant.");
     if(frame.PublicationTime>now || derivedAt>now || frame.Current.Time>now || now-frame.Current.Time>config.MaximumAge)throw new InvalidOperationException("Published derivative is future/stale at acquisition.");
     if(hasRequest && frame.Current.Time<=lastConsumed)throw new InvalidOperationException("Repeated/regressing source endpoint cannot generate a replacement sample.");
     PreviousSourceNanoseconds=frame.Previous.Time;LastSourceNanoseconds=frame.Current.Time;LastDerivativeIntervalNanoseconds=frame.Current.Time-frame.Previous.Time;
     LastSourceAgeNanoseconds=now-frame.Current.Time;LastAcquisitionNanoseconds=now;LastPublicationNanoseconds=derivedAt;
     LastSpecificForceG=force;OutputSamples++;lastRequest=now;lastConsumed=frame.Current.Time;hasRequest=true;return force;
    }
    catch(Exception e){if(fault==null)fault=e.Message;throw;}
   }
  }
  public void Reset(){} // Source failures/consumption are intentionally never erased.
  public void Dispose()
  {
   lock(gate)
   {
    if(disposed)return;
    publisher.RequirePaused();
    if(emulation.Machines.Contains(AcquisitionMachine) && !AcquisitionMachine.IsPaused)throw new InvalidOperationException("Pause acquisition machine before input disposal.");
    if(subscribed){master.SyncHook-=Publish;subscribed=false;}
    force=null;frame=null;disposed=true;
   }
  }
  private readonly Tmr8PublicSnapshotPublisher publisher;private readonly RigidTranslationConfiguration config;
  private readonly Emulation emulation;private readonly MasterTimeSource master;private readonly object gate=new object();
  private Tmr8PublicSnapshotPublisher.Pair frame;private AccelerationVector force;private string fault;
  private bool disposed,subscribed,hasRequest;private ulong derivedAt,lastRequest,lastConsumed;
 }
}
