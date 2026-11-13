// SPDX-License-Identifier: MIT
// Passive export only. Does not sample the ADC provider, integrate or modify GPIO/firmware.
using System;
using System.Globalization;
using System.IO;
using System.Collections.Generic;
using Antmicro.Renode.Peripherals.MotorExperimental;
namespace Antmicro.Renode.Peripherals.PrinterExperimental
{
    public sealed class SyntheticZProfileEvidence : IPeripheral
    {
        public SyntheticZProfileEvidence(MotorZForceSource source, VirtualZBedContactFixture fixture)
        { this.source=source ?? throw new ArgumentNullException("source"); this.fixture=fixture ?? throw new ArgumentNullException("fixture"); }
        public void Reset() { }
        public void WriteStatus(string path)
        {
            var h=source.History; var rows=new List<string>();
            Add(rows,"profile","synthetic-functional"); Add(rows,"physical_timing_fidelity",false);
            Add(rows,"query_trace_scope","accepted conversion candidates, not every producer capture or necessarily committed conversions");
            Add(rows,"now_ns",source.CurrentNanoseconds); Add(rows,"registered",source.Registered); Add(rows,"bound",source.Bound);
            Add(rows,"captures",h.Captures); Add(rows,"retired",h.Retired); Add(rows,"retained",h.Count); Add(rows,"capacity",h.Capacity);
            Add(rows,"samples_read",h.SamplesRead); Add(rows,"last_deadline_ns",h.LastDeadlineNanoseconds);
            Add(rows,"latest_capture_ns",h.LatestCaptureNanoseconds); Add(rows,"dropped_query_trace_rows",h.DroppedTraceRows);
            Add(rows,"maximum_state_age_ns",h.MaximumStateAgeNanoseconds); Add(rows,"maximum_producer_lead_ns",h.MaximumProducerLeadNanoseconds);
            Add(rows,"minimum_capture_interval_ns",source.MinimumCaptureIntervalNanoseconds); Add(rows,"maximum_capture_interval_ns",source.MaximumCaptureIntervalNanoseconds);
            Add(rows,"faulted",h.Faulted); Add(rows,"last_error",h.LastError); Add(rows,"source_reset_observations",source.ResetObservations);
            Add(rows,"fixture_enabled",fixture.Enabled); Add(rows,"current_physical_state_s",fixture.StateTimeSeconds);
            Add(rows,"current_relative_z_mm",fixture.RelativeTravelMillimeters); Add(rows,"current_contact_torque_nm",fixture.ContactTorqueNewtonMeters);
            Add(rows,"current_force_n",fixture.ReadForceNewtons()); Add(rows,"current_synthetic_code",fixture.ReadSyntheticAdcSample());
            Add(rows,"current_adc_would_saturate",fixture.AdcWouldSaturate);
            File.WriteAllText(path,"{\n  "+String.Join(",\n  ",rows)+"\n}\n");
        }
        private static void Add(List<string> rows,string key,object value)
        {
            string text=value is string ? Quote((string)value) : value is bool ? ((bool)value?"true":"false") : Convert.ToString(value,CultureInfo.InvariantCulture);
            rows.Add(Quote(key)+": "+text);
        }
        private static string Quote(string value){return "\""+value.Replace("\\","\\\\").Replace("\"","\\\"").Replace("\r","\\r").Replace("\n","\\n").Replace("\t","\\t")+"\"";}
        private readonly MotorZForceSource source; private readonly VirtualZBedContactFixture fixture;
    }
}
