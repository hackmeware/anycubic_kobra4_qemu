// SPDX-License-Identifier: MIT
// Explicit setup-time cross-machine binding. No direct GPIO/firmware access or physics advance.
using System;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.NozzleExperimental;
namespace Antmicro.Renode.Peripherals.PrinterExperimental
{
    public sealed class Cs1237ZForceBinding : IPeripheral
    {
        public Cs1237ZForceBinding(IMachine machine,Cs1237NativeGpio port,Cs1237FunctionalAdapter sensor,string sourceName)
        {
            if(machine==null||port==null||sensor==null)throw new ArgumentNullException();
            this.machine=machine;this.port=port;this.sensor=sensor;
            if(Now!=0||port.Nanoseconds!=0||sensor.Protocol.Now!=0||machine.ClockSource.CurrentValue.TotalNanoseconds!=0)
                throw new InvalidOperationException("Bind ADC source at common zero epoch before any RunFor");
            source=ZForceSourceDirectory.Resolve(sourceName);
            if(Object.ReferenceEquals(source.Machine,machine))throw new InvalidOperationException("Cross-machine binding requires distinct motor and nozzle machines");
            if(source.CurrentNanoseconds!=0)throw new InvalidOperationException("Motor epoch does not match zero ADC epoch");
            source.BindConsumer(provider=>sensor.BindTimedSource(deadline=>
            {
                CallbackCount++;
                LastDeadlineNanoseconds=deadline;LastPortNanoseconds=port.Nanoseconds;
                LastClockSourceNanoseconds=checked((long)machine.ClockSource.CurrentValue.TotalNanoseconds);
                LastMachineNanoseconds=Now;LastMotorNanoseconds=source.CurrentNanoseconds;
                LastPhysicalCaptureNanoseconds=source.History.LatestCaptureNanoseconds;
                LastProtocolNanoseconds=sensor.Protocol.Now;
                if(LastMachineNanoseconds!=LastClockSourceNanoseconds)PublishedBoundaryDifferences++;
                MaximumPublishedBoundaryLeadNanoseconds=Math.Max(MaximumPublishedBoundaryLeadNanoseconds,LastMachineNanoseconds-LastClockSourceNanoseconds);
                // BaseClockSource dispatches sub-quantum timer deadlines before finishing
                // an Advance. Machine.ElapsedVirtualTime can already be its final boundary.
                // The GPIO timer is owned by this exact peripheral clock, not that boundary.
                // Compare exact epochs; never add tolerance, advance time or borrow future state.
                try{consumerClock.Validate(deadline,LastPortNanoseconds,LastClockSourceNanoseconds);}
                catch(InvalidOperationException e){throw Failure(e.Message);}
                return provider(deadline);
            }));
            SourceName=sourceName;Bound=true;
        }
        private InvalidOperationException Failure(string reason)
        {
            if(FirstFailure.Length==0)FirstFailure=reason+"; deadline_ns="+LastDeadlineNanoseconds+" port_ns="+LastPortNanoseconds+" clock_source_ns="+LastClockSourceNanoseconds+" machine_elapsed_ns="+LastMachineNanoseconds+" motor_elapsed_ns="+LastMotorNanoseconds+" latest_capture_ns="+LastPhysicalCaptureNanoseconds+" protocol_ns="+LastProtocolNanoseconds;
            return new InvalidOperationException(FirstFailure);
        }
        public void WriteStatus(string path)
        {
            File.WriteAllText(path,"{\"clock_contract\":\"exact port timer equals its machine.ClockSource.CurrentValue; candidate not future\",\"published_boundary_differences\":"+PublishedBoundaryDifferences+",\"maximum_published_boundary_lead_ns\":"+MaximumPublishedBoundaryLeadNanoseconds+",\"callback_count\":"+CallbackCount+",\"last_deadline_ns\":"+LastDeadlineNanoseconds+",\"last_port_ns\":"+LastPortNanoseconds+",\"last_clock_source_ns\":"+LastClockSourceNanoseconds+",\"last_machine_elapsed_ns\":"+LastMachineNanoseconds+",\"last_motor_elapsed_ns\":"+LastMotorNanoseconds+",\"last_physical_capture_ns\":"+LastPhysicalCaptureNanoseconds+",\"last_protocol_ns\":"+LastProtocolNanoseconds+",\"first_failure\":\""+FirstFailure.Replace("\"","'").Replace("\\","/")+"\"}\n");
        }
        public long CallbackCount { get; private set; }
        public long PublishedBoundaryDifferences { get; private set; }
        public long MaximumPublishedBoundaryLeadNanoseconds { get; private set; }
        public long LastDeadlineNanoseconds { get; private set; }
        public long LastPortNanoseconds { get; private set; }
        public long LastClockSourceNanoseconds { get; private set; }
        public long LastMachineNanoseconds { get; private set; }
        public long LastMotorNanoseconds { get; private set; }
        public long LastPhysicalCaptureNanoseconds { get; private set; }
        public long LastProtocolNanoseconds { get; private set; }
        public string FirstFailure { get; private set; } = "";
        public bool Bound { get; private set; }
        public string SourceName { get; private set; }
        public string ProfileName { get { return sensor.ProfileName; } }
        public long ResetObservations { get; private set; }
        public void Reset(){ResetObservations++;} // A CPU reset neither rebinds nor resets sensor/history.
        private long Now { get { return checked((long)machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds); } }
        private readonly ZConsumerClockGuard consumerClock=new ZConsumerClockGuard();
        private readonly IMachine machine;private readonly Cs1237NativeGpio port;
        private readonly Cs1237FunctionalAdapter sensor;private readonly MotorZForceSource source;
    }
    // Pure validation of captured peripheral-domain timestamps. The history independently
    // checks candidate rollback, source lead and physical-state age against unchanged bounds.
    public sealed class ZConsumerClockGuard
    {
        public void Validate(long deadline,long portNanoseconds,long peripheralNanoseconds)
        {
            if(deadline<0||portNanoseconds<0||peripheralNanoseconds<0)throw new InvalidOperationException("Negative ADC peripheral-domain timestamp");
            if(portNanoseconds!=peripheralNanoseconds)throw new InvalidOperationException("ADC port clock does not match its peripheral clock epoch");
            if(peripheralNanoseconds<lastPeripheralNanoseconds)throw new InvalidOperationException("ADC peripheral clock epoch moved backwards");
            if(deadline>peripheralNanoseconds)throw new InvalidOperationException("ADC requested a future conversion deadline");
            lastPeripheralNanoseconds=peripheralNanoseconds;
        }
        private long lastPeripheralNanoseconds;
    }
}
