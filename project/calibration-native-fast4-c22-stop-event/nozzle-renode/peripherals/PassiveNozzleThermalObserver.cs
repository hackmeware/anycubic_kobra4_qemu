// SPDX-License-Identifier: MIT
// Passive GPIO sinks and read-only thermal snapshots. No actuator/sensor writes.
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
    public class PassiveNozzleThermalObserver : IPeripheral, IGPIOReceiver, IDisposable
    {
        public PassiveNozzleThermalObserver(IMachine machine, AT32GPIO portB,
            VirtualPrinterThermal thermal, uint sampleMicroseconds = 100000, int maximumRows = 100000)
        {
            if(portB == null) throw new ArgumentNullException("portB");
            if(thermal == null) throw new ArgumentNullException("thermal");
            if(sampleMicroseconds == 0) throw new ArgumentOutOfRangeException("sampleMicroseconds");
            if(maximumRows < 1 || maximumRows > 1000000) throw new ArgumentOutOfRangeException("maximumRows");
            this.portB = portB; this.thermal = thermal; maximum = maximumRows;
            clock = new LimitTimer(machine.ClockSource, 1000000, this, "passive nozzle observer clock", ulong.MaxValue,
                direction:Direction.Ascending, enabled:true, eventEnabled:false);
            sampling = new LimitTimer(machine.ClockSource, 1000000, this, "passive nozzle observer sampling", sampleMicroseconds,
                direction:Direction.Ascending, workMode:WorkMode.Periodic, enabled:true, eventEnabled:true);
            sampling.LimitReached += () => Add("sample", "", "");
            var levels = portB.ReadDoubleWord(8);
            lastPB8 = (levels & (1u << 8)) != 0; lastPB9 = (levels & (1u << 9)) != 0;
            // Multiple-sink connections preserve existing observers. Nothing connects
            // portB to thermal.OnGPIO, and no GPIO level is driven by this observer.
            portB.Connections[8].Connect(this, 8);
            portB.Connections[9].Connect(this, 9);
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
            if(number != 8 && number != 9) throw new ArgumentOutOfRangeException("number");
            lock(sync)
            {
                var previous = number == 8 ? lastPB8 : lastPB9;
                if(previous == value) return;
                if(number == 8) lastPB8 = value; else lastPB9 = value;
                EdgeCount++;
                Add("edge", number == 8 ? "PB8" : "PB9", value ? "1" : "0");
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
            return "{\n  \"time_domain\": \"nozzle Renode microseconds since observer creation; not synchronized host time\",\n"
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
            this.Log(LogLevel.Warning, "Passive nozzle stream failed: {0}", LastStreamError);
        }
        private void Add(string kind, string pin, string value)
        {
            lock(sync)
            {
                if(kind == "sample") SampleCount++;
                if(rows.Count >= maximum && !streamRequested) { DroppedRows++; return; }
                var state = portB.ReadDoubleWord(8);
                var configuration = portB.ReadDoubleWord(4);
                var latch = portB.ReadDoubleWord(12);
                var row = String.Join(",", new[]{
                clock.Value.ToString(CultureInfo.InvariantCulture), kind, pin, value,
                Bit(state,8), Bit(state,9), (configuration & 15).ToString(CultureInfo.InvariantCulture), ((configuration >> 4) & 15).ToString(CultureInfo.InvariantCulture),
                Bit(latch,8), Bit(latch,9), Number(thermal.TemperatureCelsius), thermal.ADCValue.ToString(CultureInfo.InvariantCulture),
                Safe(thermal.SensorCurve), Safe(thermal.SensorFault), Flag(thermal.SensorCurveOutOfRange), Flag(thermal.Overtemperature), Flag(thermal.HeaterLatchedOff),
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
        private readonly AT32GPIO portB;
        private readonly VirtualPrinterThermal thermal;
        private readonly LimitTimer clock, sampling;
        private readonly int maximum;
        private readonly object sync = new object();
        private readonly List<string> rows = new List<string>();
        private bool lastPB8, lastPB9;
        private StreamWriter writer;
        private string streamPath;
        private bool streamRequested;
        private const string Header = "time_us,event,changed_pin,changed_level,pb8_level,pb9_level,pb8_config,pb9_config,pb8_latch,pb9_latch,physical_temperature_c,published_adc_code,sensor_curve,sensor_fault,curve_out_of_range,model_overtemperature,model_heater_latched_off,last_heater_duty,last_fan_duty,thermal_updates";
    }
}
