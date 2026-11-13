// SPDX-License-Identifier: MIT
// Experimental immutable physical snapshots. Never advances a clock or physical state.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
namespace Antmicro.Renode.Peripherals.PrinterExperimental
{
    public sealed class ZForceSnapshot
    {
        public ZForceSnapshot(long stateNanoseconds,long captureNanoseconds,double physicalStateSeconds,
            double torqueNewtonMeters,double forceNewtons,int signedCode,bool saturated,bool enabled)
        {
            if(stateNanoseconds<0||captureNanoseconds<stateNanoseconds||!Finite(physicalStateSeconds)
                ||physicalStateSeconds<0||!Finite(torqueNewtonMeters)||!Finite(forceNewtons)||forceNewtons<0
                ||signedCode < -8388608||signedCode>8388607)throw new ArgumentException("Invalid physical Z snapshot");
            StateNanoseconds=stateNanoseconds;CaptureNanoseconds=captureNanoseconds;PhysicalStateSeconds=physicalStateSeconds;
            TorqueNewtonMeters=torqueNewtonMeters;ForceNewtons=forceNewtons;SignedCode=signedCode;Saturated=saturated;Enabled=enabled;
        }
        public long StateNanoseconds { get; private set; }
        public long CaptureNanoseconds { get; private set; }
        public double PhysicalStateSeconds { get; private set; }
        public double TorqueNewtonMeters { get; private set; }
        public double ForceNewtons { get; private set; }
        public int SignedCode { get; private set; }
        public bool Saturated { get; private set; }
        public bool Enabled { get; private set; }
        private static bool Finite(double x){return !Double.IsNaN(x)&&!Double.IsInfinity(x);}
    }
    public sealed class ZForceHistory
    {
        public ZForceHistory(long maximumStateAgeNanoseconds,long maximumProducerLeadNanoseconds,int capacity=4096,int maximumTraceRows=0)
        {
            if(maximumStateAgeNanoseconds<1||maximumStateAgeNanoseconds>1000000000L
                ||maximumProducerLeadNanoseconds<0||maximumProducerLeadNanoseconds>1000000000L
                ||capacity<2||capacity>1000000||maximumTraceRows<0||maximumTraceRows>1000000)
                throw new ArgumentException("Invalid bounded Z history parameters");
            MaximumStateAgeNanoseconds=maximumStateAgeNanoseconds;MaximumProducerLeadNanoseconds=maximumProducerLeadNanoseconds;
            samples=new ZForceSnapshot[capacity];traceLimit=maximumTraceRows;
        }
        public long MaximumStateAgeNanoseconds { get; private set; }
        public long MaximumProducerLeadNanoseconds { get; private set; }
        public int Count { get { lock(sync)return count; } }
        public int Capacity { get { return samples.Length; } }
        public long LatestCaptureNanoseconds { get { lock(sync)return count==0?-1:At(count-1).CaptureNanoseconds; } }
        public long Captures { get; private set; }
        public long Retired { get; private set; }
        public long SamplesRead { get; private set; }
        public long DroppedTraceRows { get; private set; }
        public long LastDeadlineNanoseconds { get; private set; } = -1;
        public string LastError { get; private set; } = "";
        public bool Faulted { get { return LastError.Length!=0; } }
        public void Add(ZForceSnapshot sample)
        {
            lock(sync)
            {
                Healthy();if(sample==null)throw Fault("Missing physical snapshot");
                // Capture is attached after the plant on its existing trigger. At most one
                // nanosecond is allowed for seconds-to-integer conversion, never future data.
                if(sample.CaptureNanoseconds-sample.StateNanoseconds>1)throw Fault("Motor trigger preceded physical integration");
                if(count!=0)
                {
                    var previous=At(count-1);
                    if(sample.CaptureNanoseconds<previous.CaptureNanoseconds||sample.StateNanoseconds<previous.StateNanoseconds)
                        throw Fault("Motor epoch or physical timestamp moved backwards");
                    if(sample.StateNanoseconds==previous.StateNanoseconds)
                    {
                        if(sample.CaptureNanoseconds!=previous.CaptureNanoseconds||sample.SignedCode!=previous.SignedCode
                            ||sample.TorqueNewtonMeters!=previous.TorqueNewtonMeters||sample.ForceNewtons!=previous.ForceNewtons
                            ||sample.Enabled!=previous.Enabled||sample.Saturated!=previous.Saturated)
                            throw Fault("Ambiguous changed physical state at the same timestamp");
                        return;
                    }
                }
                // Any future permitted deadline d is >= newest_capture - maximum_lead.
                // Therefore state < newest_capture - maximum_lead - maximum_age can
                // never be eligible. Retirement is safe even before the first conversion.
                long cutoff=sample.CaptureNanoseconds-MaximumProducerLeadNanoseconds-MaximumStateAgeNanoseconds;
                while(count!=0&&At(0).StateNanoseconds<cutoff)
                {samples[start]=null;start=(start+1)%samples.Length;count--;Retired++;}
                if(count==samples.Length)throw Fault("Z history capacity exhausted inside still-eligible window");
                samples[(start+count)%samples.Length]=sample;count++;Captures++;
            }
        }
        public ZForceSnapshot ReadAt(long deadlineNanoseconds)
        {
            lock(sync)
            {
                Healthy();if(deadlineNanoseconds<0)throw Fault("Negative ADC deadline");
                if(deadlineNanoseconds<LastDeadlineNanoseconds)throw Fault("ADC deadline epoch moved backwards");
                if(count==0)throw Fault("No motor physical history");
                var latest=At(count-1);
                if(latest.CaptureNanoseconds>deadlineNanoseconds
                    &&latest.CaptureNanoseconds-deadlineNanoseconds>MaximumProducerLeadNanoseconds)
                    throw Fault("Motor/nozzle skew exceeded declared producer lead");
                if(deadlineNanoseconds==LastDeadlineNanoseconds&&lastSelected!=null)return lastSelected;
                ZForceSnapshot selected=null;
                for(int i=count-1;i>=0;i--)if(At(i).StateNanoseconds<=deadlineNanoseconds){selected=At(i);break;}
                if(selected==null)throw Fault("Only future motor history exists for ADC deadline");
                long age=deadlineNanoseconds-selected.StateNanoseconds;
                if(age>MaximumStateAgeNanoseconds)throw Fault("Motor physical state is stale at ADC deadline");
                LastDeadlineNanoseconds=deadlineNanoseconds;lastSelected=selected;SamplesRead++;
                Record(deadlineNanoseconds,selected,age);
                return selected;
            }
        }
        public void LatchFailure(string message)
        {lock(sync){if(!Faulted)LastError=message??"Unspecified source failure";}}
        public void WriteTrace(string path)
        {
            lock(sync)
                File.WriteAllText(path,"deadline_ns,physical_state_ns,capture_ns,physical_state_s,age_ns,contact_torque_nm,force_N,signed_code,saturated,fixture_enabled\n"+String.Join("\n",trace)+"\n");
        }
        private void Record(long deadline,ZForceSnapshot sample,long age)
        {
            if(traceLimit==0)return;
            if(trace.Count>=traceLimit){DroppedTraceRows++;return;}
            var c=CultureInfo.InvariantCulture;
            trace.Add(String.Join(",",new[]{deadline.ToString(c),sample.StateNanoseconds.ToString(c),sample.CaptureNanoseconds.ToString(c),
                sample.PhysicalStateSeconds.ToString("R",c),age.ToString(c),sample.TorqueNewtonMeters.ToString("R",c),sample.ForceNewtons.ToString("R",c),
                sample.SignedCode.ToString(c),sample.Saturated?"1":"0",sample.Enabled?"1":"0"}));
        }
        private void Healthy(){if(Faulted)throw new InvalidOperationException(LastError);}
        private InvalidOperationException Fault(string message){LastError=message;return new InvalidOperationException(message);}
        private ZForceSnapshot At(int index){return samples[(start+index)%samples.Length];}
        private readonly object sync=new object();private readonly ZForceSnapshot[] samples;
        private readonly int traceLimit;private readonly List<string> trace=new List<string>();
        private int start,count;private ZForceSnapshot lastSelected;
    }
}
