// SPDX-License-Identifier: MIT
// Optional passive resolved PA0 sink and read-only thermal snapshots.
// No actuator/sensor/clock writes, CPU synchronization, or extra physics calls.
// time_us is the existing observer-local 1MHz clock; virtual_time_ns is the
// source machine elapsed epoch read without SyncTime (no host-time comparison).
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.AT32
{
    public class PassiveBedThermalObserver : IPeripheral, IGPIOReceiver, IDisposable
    {
        public PassiveBedThermalObserver(IMachine machine, AT32GPIO portA,
            VirtualPrinterThermal thermal, uint sampleMicroseconds = 100000, int maximumRows = 100000)
        {
            if(portA == null) throw new ArgumentNullException("portA");
            if(thermal == null) throw new ArgumentNullException("thermal");
            if(sampleMicroseconds == 0) throw new ArgumentOutOfRangeException("sampleMicroseconds");
            if(maximumRows < 1 || maximumRows > 1000000) throw new ArgumentOutOfRangeException("maximumRows");
            this.portA = portA; this.thermal = thermal; maximum = maximumRows; this.machine = machine;
            clock = new LimitTimer(machine.ClockSource, 1000000, this, "passive bed observer clock", ulong.MaxValue,
                direction:Direction.Ascending, enabled:true, eventEnabled:false);
            sampling = new LimitTimer(machine.ClockSource, 1000000, this, "passive bed observer sampling", sampleMicroseconds,
                direction:Direction.Ascending, workMode:WorkMode.Periodic, enabled:true, eventEnabled:true);
            sampling.LimitReached += () => Add("sample", "", "");
            var levels = portA.ReadDoubleWord(8);
            lastPA0 = (levels & 1) != 0;
            // Multiple-sink connections preserve existing observers. Nothing connects
            // portA to thermal.OnGPIO, and no GPIO level is driven by this observer.
            portA.Connections[0].Connect(this, 0);
            Mark("observer_attached");
        }
        public int RowCount { get { lock(sync) return rows.Count; } }
        public ulong EdgeCount { get; private set; }
        public ulong SampleCount { get; private set; }
        public ulong DroppedRows { get; private set; }
        public bool CapacityReached { get { return DroppedRows != 0; } }
        public bool Streaming { get { lock(sync) return writer != null; } }
        public ulong StreamRowsWritten { get; private set; }
        public ulong StreamDroppedRows { get; private set; }
        public bool StreamCapacityReached { get; private set; }
        public ulong StreamErrorCount { get; private set; }
        public string LastStreamError { get; private set; } = "";
        public bool StreamWriteOutcomeUncertain { get; private set; }
        public void Start(string path)
        {
            lock(sync)
            {
                if(streamRequested) throw new InvalidOperationException("Stop the previous observer stream before starting another");
                var destination = Path.GetFullPath(path);
                try
                {
                    // CreateNew cannot replace prior evidence. Shared reads permit live inspection.
                    writer = new StreamWriter(new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.Read), new UTF8Encoding(false));
                    writer.WriteLine(Header); writer.Flush();
                }
                catch(Exception error)
                {
                    StreamFailure(error, false); CloseWriter(); throw;
                }
                streamPath = destination;
                StreamRowsWritten = StreamDroppedRows = StreamErrorCount = 0;
                LastStreamError = ""; StreamCapacityReached = StreamWriteOutcomeUncertain = false;
                streamRequested = true;
                Mark("stream_started"); // Actual current state, not a replay of old buffered rows.
            }
        }
        public void Stop()
        {
            lock(sync) { streamRequested = false; CloseWriter(); }
        }
        public void Dispose() { Stop(); }
        public void WriteStreamStatus(string path)
        {
            lock(sync)
            {
                RejectStreamOverwrite(path);
                File.WriteAllText(path, GetStatusJson());
            }
        }
        public void Reset() { Mark("MCU_reset_observed"); }
        public void Clear()
        {
            lock(sync)
            {
                rows.Clear(); EdgeCount = SampleCount = DroppedRows = 0;
                Mark("observer_cleared"); // The observation clock and all device states are retained.
            }
        }
        public void OnGPIO(int number, bool value)
        {
            if(number != 0) throw new ArgumentOutOfRangeException("number");
            lock(sync)
            {
                var previous = lastPA0;
                if(previous == value) return;
                lastPA0 = value;
                EdgeCount++;
                Add("edge", "PA0", value ? "1" : "0");
            }
        }
        public void Mark(string label) { Add("snapshot:" + Safe(label), "", ""); }
        public string GetCsv()
        {
            lock(sync)
                return Header + "\n"
                    + String.Join("\n", rows) + "\n";
        }
        public void WriteCsv(string path)
        {
            string csv, status;
            lock(sync)
            {
                RejectStreamOverwrite(path);
                RejectStreamOverwrite(path + ".status.json");
                csv = GetCsv();
                status = GetStatusJson();
            }
            File.WriteAllText(path, csv);
            File.WriteAllText(path + ".status.json", status);
        }
        private string GetStatusJson()
        {
            return "{\n  \"time_domain\": \"bed Renode microseconds since observer creation; not synchronized host time\",\n"
                + "  \"rows\": " + RowCount + ",\n  \"observed_edges\": " + EdgeCount
                + ",\n  \"observed_periodic_samples\": " + SampleCount + ",\n  \"dropped_rows\": " + DroppedRows
                + ",\n  \"capacity_reached\": " + (CapacityReached ? "true" : "false")
                + ",\n  \"last_export_time_us\": " + clock.Value.ToString(CultureInfo.InvariantCulture)
                + ",\n  \"firmware_guard_state_recorded\": false,\n  \"actuator_connection_created\": false,\n"
                + "  \"streaming\": " + JsonFlag(writer != null) + ",\n  \"stream_requested\": " + JsonFlag(streamRequested)
                + ",\n  \"stream_rows_written\": " + StreamRowsWritten + ",\n  \"stream_dropped_rows\": " + StreamDroppedRows
                + ",\n  \"stream_capacity_reached\": " + JsonFlag(StreamCapacityReached)
                + ",\n  \"stream_error_count\": " + StreamErrorCount + ",\n  \"last_stream_error\": " + JsonString(LastStreamError)
                + ",\n  \"stream_write_outcome_uncertain\": " + JsonFlag(StreamWriteOutcomeUncertain) + "\n}\n";
        }
        private void RejectStreamOverwrite(string path)
        {
            if(streamPath != null && Path.GetFullPath(path) == streamPath)
                throw new InvalidOperationException("Do not overwrite a streaming capture; use a separate export/status path");
        }
        private void StreamRow(string row)
        {
            if(!streamRequested) return;
            if(writer == null) { StreamDroppedRows++; return; }
            try
            {
                writer.WriteLine(row); writer.Flush();
                StreamRowsWritten++;
                if(StreamRowsWritten >= (ulong)maximum)
                {
                    StreamCapacityReached = true; CloseWriter();
                    // Keep counting subsequent uncaptured events until explicit Stop.
                }
            }
            catch(Exception error)
            {
                StreamDroppedRows++; StreamFailure(error, true); CloseWriter();
            }
        }
        private void CloseWriter()
        {
            if(writer == null) return;
            var closing = writer; writer = null;
            try { closing.Dispose(); }
            catch(Exception error) { StreamFailure(error, true); }
        }
        private void StreamFailure(Exception error, bool uncertain)
        {
            StreamErrorCount++; LastStreamError = error.GetType().Name + ": " + error.Message;
            StreamWriteOutcomeUncertain |= uncertain;
            // File failures must not change firmware execution or device state.
            this.Log(LogLevel.Warning, "Passive bed stream failed: {0}", LastStreamError);
        }
        private void Add(string kind, string pin, string value)
        {
            lock(sync)
            {
                if(kind == "sample") SampleCount++;
                if(rows.Count >= maximum && !streamRequested) { DroppedRows++; return; }
                var state = portA.ReadDoubleWord(8);
                var configuration = portA.ReadDoubleWord(0);
                var latch = portA.ReadDoubleWord(12);
                var row = String.Join(",", new[]{
                clock.Value.ToString(CultureInfo.InvariantCulture), machine.ElapsedVirtualTime.TimeElapsed.TotalNanoseconds.ToString(CultureInfo.InvariantCulture), kind, pin, value,
                Bit(state,0), (configuration & 15).ToString(CultureInfo.InvariantCulture), Bit(latch,0), Number(thermal.TemperatureCelsius), thermal.ADCValue.ToString(CultureInfo.InvariantCulture),
                "B3950 100k 4700ohm illustrative divider", Safe(thermal.SensorFault), Flag(thermal.Overtemperature), Flag(thermal.HeaterLatchedOff),
                Number(thermal.LastHeaterDuty), Number(thermal.LastFanDuty), thermal.Updates.ToString(CultureInfo.InvariantCulture)
                });
                if(rows.Count >= maximum) DroppedRows++; else rows.Add(row);
                StreamRow(row);
            }
        }
        private static string Number(double value) { return value.ToString("R", CultureInfo.InvariantCulture); }
        private static string Bit(uint value, int bit) { return ((value >> bit) & 1).ToString(CultureInfo.InvariantCulture); }
        private static string Flag(bool value) { return value ? "1" : "0"; }
        private static string JsonFlag(bool value) { return value ? "true" : "false"; }
        private static string JsonString(string value)
        {
            var result = new StringBuilder("\"");
            foreach(var c in value)
            {
                if(c == '"' || c == '\\') result.Append('\\').Append(c);
                else if(c < 32) result.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                else result.Append(c);
            }
            return result.Append('"').ToString();
        }
        private static string Safe(string value) { return (value ?? "").Replace(',', ';').Replace('\r', ' ').Replace('\n', ' '); }
        private readonly AT32GPIO portA;
        private readonly VirtualPrinterThermal thermal;
        private readonly LimitTimer clock, sampling;
        private readonly int maximum;
        private readonly object sync = new object();
        private readonly List<string> rows = new List<string>();
        private bool lastPA0;
        private readonly IMachine machine;
        private StreamWriter writer;
        private string streamPath;
        private bool streamRequested;
        private const string Header = "time_us,virtual_time_ns,event,changed_pin,changed_level,pa0_level,pa0_config,pa0_latch,physical_temperature_c,published_adc_code,sensor_curve,sensor_fault,model_overtemperature,model_heater_latched_off,last_heater_duty,last_fan_duty,thermal_updates";
    }
}
