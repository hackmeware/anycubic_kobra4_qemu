// SPDX-License-Identifier: MIT
// CPU-free streaming/failure tests. No actuator, thermal or firmware writes.
using System;
using System.IO;
using System.Reflection;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    public class PassiveNozzleStreamingTests : IDoubleWordPeripheral, IKnownSize
    {
        public PassiveNozzleStreamingTests(IMachine machine, AT32GPIO portB, VirtualPrinterThermal thermal, PassiveNozzleThermalObserver observer)
        { this.machine=machine;this.portB=portB;this.thermal=thermal;this.observer=observer; }
        public long Size { get { return 4; } }
        public void Reset() { }
        public uint ReadDoubleWord(long offset) { return 0; }
        public void WriteDoubleWord(long offset,uint value) { }
        private void Check(bool condition,string label) { if(!condition) throw new Exception(label);checks++; }
        private void Reject<T>(Action action,string label) where T:Exception
        {try{action();}catch(T){checks++;return;}throw new Exception(label);}
        private void Unchanged()
        {
            Check(thermal.TemperatureCelsius==25 && thermal.ADCValue==4023,"stream cannot invent physical heat or ADC");
            Check(thermal.LastHeaterDuty==0 && thermal.LastFanDuty==0 && thermal.SensorFault=="none" && !thermal.HeaterLatchedOff && !thermal.Overtemperature,"stream preserves thermal inputs/fault/guards");
        }
        public string Prepare(string directory)
        {
            path=Path.Combine(directory,"stream.csv");secondPath=Path.Combine(directory,"continued.csv");
            var existing=Path.Combine(directory,"existing.csv");File.WriteAllText(existing,"untouched evidence");
            Check(!observer.Streaming && observer.StreamRowsWritten==0 && observer.StreamErrorCount==0,"stream disabled by default");
            Reject<IOException>(()=>observer.Start(existing),"existing file accepted");
            Check(File.ReadAllText(existing)=="untouched evidence" && observer.StreamErrorCount==1 && observer.LastStreamError!="","fresh-file rejection is visible and preserves evidence");
            observer.Start(path);
            Check(observer.Streaming && observer.StreamRowsWritten==1 && observer.StreamErrorCount==0,"new session writes current snapshot and clears prior attempt error");
            Check(File.ReadAllLines(path).Length==2 && File.ReadAllText(path).Contains("snapshot:stream_started"),"header and actual start snapshot readable while open");
            Reject<InvalidOperationException>(()=>observer.Start(secondPath),"active stream replaced");
            Reject<InvalidOperationException>(()=>observer.WriteCsv(path),"export overwrote stream");
            Reject<InvalidOperationException>(()=>observer.WriteStreamStatus(path),"status overwrote stream");
            observer.Mark("phase,one\nmarker");
            Check(File.ReadAllText(path).Contains("snapshot:phase;one marker"),"explicit snapshots are sanitized and flushed");
            portB.WriteDoubleWord(4,0x44444411);portB.WriteDoubleWord(12,0x100);
            Check(observer.StreamRowsWritten==3 && File.ReadAllText(path).Contains("0,edge,PB8,1,"),"actual edge flushed immediately");
            Unchanged();observer.Stop();var length=new FileInfo(path).Length;
            observer.Mark("not_streamed");
            Check(!observer.Streaming && new FileInfo(path).Length==length && observer.StreamDroppedRows==0,"explicit stop does not count intentional excluded events as loss");
            Reject<IOException>(()=>observer.Start(path),"stopped capture overwritten");
            Check(new FileInfo(path).Length==length,"stopped capture preserved");
            observer.Start(secondPath);
            capped=new PassiveNozzleThermalObserver(machine,portB,thermal,maximumRows:2);
            var cap=Path.Combine(directory,"capped.csv");capped.Start(cap);capped.Mark("last_allowed");
            Check(!capped.Streaming && capped.StreamCapacityReached && capped.StreamRowsWritten==2,"stream closes exactly at row bound");
            var capLength=new FileInfo(cap).Length;capped.Mark("dropped");
            Check(capped.StreamDroppedRows==1 && new FileInfo(cap).Length==capLength,"post-cap events explicitly counted without growing file");
            capped.Clear();
            Check(capped.StreamRowsWritten==2 && capped.StreamDroppedRows==2 && capped.StreamCapacityReached,"memory clear cannot reset or evade stream bound");
            capped.WriteStreamStatus(Path.Combine(directory,"capped.status.json"));capped.Stop();
            failed=new PassiveNozzleThermalObserver(machine,portB,thermal);
            failed.Start(Path.Combine(directory,"failed.csv"));
            // Unit-only sink fault: dispose the actual writer, without touching devices.
            var field=typeof(PassiveNozzleThermalObserver).GetField("writer",BindingFlags.Instance|BindingFlags.NonPublic);
            ((StreamWriter)field.GetValue(failed)).Dispose();
            failed.Mark("write_to_failed_sink");
            Check(!failed.Streaming && failed.StreamErrorCount>0 && failed.LastStreamError!="" && failed.StreamWriteOutcomeUncertain,"write failure is explicit and does not escape callback");
            Check(failed.StreamRowsWritten==1 && failed.StreamDroppedRows==1,"unconfirmed write is not claimed as delivered");
            failed.Mark("after_failure");Check(failed.StreamDroppedRows==2,"continued events after I/O failure counted");
            failed.WriteStreamStatus(Path.Combine(directory,"failed.status.json"));failed.Stop();
            var missing=new PassiveNozzleThermalObserver(machine,portB,thermal);
            Reject<DirectoryNotFoundException>(()=>missing.Start(Path.Combine(directory,"absent","capture.csv")),"missing directory accepted");
            Check(!missing.Streaming && missing.StreamErrorCount>0 && missing.LastStreamError!="","explicit start error retains readable diagnostics");
            Unchanged();return "PASSIVE NOZZLE STREAM PREPARED";
        }
        public string Finish(string directory)
        {
            Unchanged();
            Check(observer.Streaming && observer.StreamRowsWritten==2,"periodic actual sample streamed after start snapshot");
            Check(File.ReadAllText(secondPath).Contains("100000,sample,,,1,0,"),"100ms sample visible before stop/export");
            var before=observer.StreamRowsWritten;observer.Clear();observer.Reset();
            Check(observer.StreamRowsWritten==before+2,"clear/reset append snapshots but retain streaming counters");
            Check(File.ReadAllText(secondPath).Contains("snapshot:MCU_reset_observed"),"observer reset remains only a marker");
            Check(portB.ReadDoubleWord(4)==0x44444411 && portB.ReadDoubleWord(12)==0x100,"stream operations never configure/drive GPIO");
            observer.WriteStreamStatus(Path.Combine(directory,"live.status.json"));
            observer.Dispose();Check(!observer.Streaming,"dispose closes only output stream");
            observer.WriteStreamStatus(Path.Combine(directory,"stopped.status.json"));
            Unchanged();return "PASSIVE NOZZLE STREAMING TESTS PASS: "+checks;
        }
        private readonly IMachine machine;private readonly AT32GPIO portB;private readonly VirtualPrinterThermal thermal;private readonly PassiveNozzleThermalObserver observer;
        private PassiveNozzleThermalObserver capped,failed;private string path,secondPath;private int checks;
    }
}
