// SPDX-License-Identifier: MIT
// Attach AFTER the electromechanical plant on its EXISTING TMR8 trigger.
using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.AT32;
using Antmicro.Renode.Peripherals.MotorExperimental;
namespace Antmicro.Renode.Peripherals.PrinterExperimental
{
    public sealed class MotorZForceSource : IPeripheral, IGPIOReceiver
    {
        public MotorZForceSource(IMachine machine,VirtualZBedContactFixture fixture,AT32Timer tmr8,
            long maximumStateAgeNanoseconds,long maximumProducerLeadNanoseconds,int capacity=4096,int maximumTraceRows=0)
        {
            if(machine==null||fixture==null||tmr8==null)throw new ArgumentNullException();
            this.machine=machine;this.fixture=fixture;
            if(CurrentNanoseconds!=0)throw new InvalidOperationException("Construct Z source at the shared zero epoch before RunFor");
            History=new ZForceHistory(maximumStateAgeNanoseconds,maximumProducerLeadNanoseconds,capacity,maximumTraceRows);
            Capture();tmr8.TriggerOutput.Connect(this,0);
        }
        public ZForceHistory History { get; private set; }
        public long CurrentNanoseconds { get { return checked((long)machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds); } }
        public IMachine Machine { get { return machine; } }
        public bool Registered { get; private set; }
        public bool Bound { get; private set; }
        public string RegistryName { get; private set; } = "";
        public long ResetObservations { get; private set; }
        public long MinimumCaptureIntervalNanoseconds { get; private set; }
        public long MaximumCaptureIntervalNanoseconds { get; private set; }
        public void Reset(){ResetObservations++;} // MCU reset does not reset physical history/epoch.
        public void OnGPIO(int number,bool value)
        {
            if(number!=0||!value||History.Faulted)return;
            try{Capture();}catch(Exception e){History.LatchFailure(e.Message);}
        }
        public void Register(string sourceName)
        {
            if(Registered||Bound)throw new InvalidOperationException("Z source already registered or bound");
            if(CurrentNanoseconds!=0)throw new InvalidOperationException("Register Z source before RunFor");
            ZForceSourceDirectory.Register(sourceName,this);Registered=true;RegistryName=sourceName;
        }
        public void BindConsumer(Action<Func<long,int>> install)
        {
            lock(bindingLock)
            {
                if(install==null)throw new ArgumentNullException("install");
                if(!Registered||Bound)throw new InvalidOperationException("Missing registration or duplicate Z consumer binding");
                if(CurrentNanoseconds!=0)throw new InvalidOperationException("Bind Z source before RunFor");
                if(History.Faulted)throw new InvalidOperationException(History.LastError);
                // Adapter installation is atomic and must not invoke the provider here.
                // If it rejects an existing owner, this source remains unclaimed.
                install(deadline=>ReadAt(deadline).SignedCode);Bound=true;
            }
        }
        public ZForceSnapshot ReadAt(long deadlineNanoseconds)
        {
            if(!Bound)throw new InvalidOperationException("No exclusive ADC consumer bound to Z source");
            long now=CurrentNanoseconds;
            if(now<History.LatestCaptureNanoseconds)History.LatchFailure("Motor clock epoch moved backwards");
            if(now>deadlineNanoseconds&&now-deadlineNanoseconds>History.MaximumProducerLeadNanoseconds)
                History.LatchFailure("Motor/nozzle current-clock skew exceeded declared producer lead");
            return History.ReadAt(deadlineNanoseconds);
        }
        public void WriteTrace(string path){History.WriteTrace(path);}
        private void Capture()
        {
            long now=CurrentNanoseconds;double seconds=fixture.StateTimeSeconds;
            if(Double.IsNaN(seconds)||Double.IsInfinity(seconds)||seconds<0||seconds>long.MaxValue/1000000000.0)
                throw new InvalidOperationException("Invalid/out-of-range physical timestamp");
            long state=checked((long)Math.Round(seconds*1000000000.0,MidpointRounding.AwayFromZero));
            long previous=History.LatestCaptureNanoseconds;
            History.Add(new ZForceSnapshot(state,now,seconds,fixture.ContactTorqueNewtonMeters,fixture.ReadForceNewtons(),
                fixture.ReadSyntheticAdcSample(),fixture.AdcWouldSaturate,fixture.Enabled));
            if(previous>=0&&now>previous)
            {
                long interval=now-previous;
                if(MinimumCaptureIntervalNanoseconds==0||interval<MinimumCaptureIntervalNanoseconds)MinimumCaptureIntervalNanoseconds=interval;
                if(interval>MaximumCaptureIntervalNanoseconds)MaximumCaptureIntervalNanoseconds=interval;
            }
        }
        private readonly object bindingLock=new object();
        private readonly IMachine machine;private readonly VirtualZBedContactFixture fixture;
    }
    // Scoped by actual Emulation identity; no string-only/process-global stale source reuse.
    // Registration is setup only. Runtime samples use a typed direct reference.
    public static class ZForceSourceDirectory
    {
        public static void Register(string name,MotorZForceSource source)
        {
            if(String.IsNullOrWhiteSpace(name)||source==null)throw new ArgumentException("Explicit source name and instance required");
            var scope=scopes.GetValue(EmulationManager.Instance.CurrentEmulation,_=>new Scope());
            lock(scope.Sources)
            {
                if(scope.Sources.ContainsKey(name))throw new InvalidOperationException("Duplicate Z source name in this emulation");
                scope.Sources.Add(name,source);
            }
        }
        public static MotorZForceSource Resolve(string name)
        {
            if(String.IsNullOrWhiteSpace(name))throw new ArgumentException("Explicit Z source name required");
            Scope scope;MotorZForceSource source;
            if(!scopes.TryGetValue(EmulationManager.Instance.CurrentEmulation,out scope))throw new InvalidOperationException("No Z source registered in this emulation");
            lock(scope.Sources)
            {
                if(!scope.Sources.TryGetValue(name,out source))throw new InvalidOperationException("Named Z source is missing");
                return source;
            }
        }
        private sealed class Scope {public readonly Dictionary<string,MotorZForceSource> Sources=new Dictionary<string,MotorZForceSource>();}
        private static readonly ConditionalWeakTable<Emulation,Scope> scopes=new ConditionalWeakTable<Emulation,Scope>();
    }
}
