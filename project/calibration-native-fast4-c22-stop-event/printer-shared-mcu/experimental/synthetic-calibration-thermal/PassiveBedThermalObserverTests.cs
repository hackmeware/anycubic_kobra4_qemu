// SPDX-License-Identifier: MIT
// CPU-free observer tests. Synthetic actual GPIO register writes, no firmware.
using System;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.ThermalExperimental
{
    public class PassiveBedThermalObserverTests : IPeripheral
    {
        public PassiveBedThermalObserverTests(IMachine machine, AT32GPIO port, AT32GPIO baselinePort,
            VirtualPrinterThermal thermal, VirtualPrinterThermal baseline, PassiveBedThermalObserver observer)
        { this.machine=machine;this.port=port;this.baselinePort=baselinePort;this.thermal=thermal;this.baseline=baseline;this.observer=observer; }
        public void Reset() { }
        private void Check(bool condition,string label) { if(!condition)throw new Exception(label);checks++; }
        private void Same()
        {
            Check(thermal.TemperatureCelsius==baseline.TemperatureCelsius && thermal.Updates==baseline.Updates,"observers never add physics integration");
            Check(thermal.LastHeaterDuty==baseline.LastHeaterDuty && thermal.ADCValue==baseline.ADCValue,"observed and unobserved identical actual GPIO plants");
        }
        private void Write(long offset,uint value) { port.WriteDoubleWord(offset,value);baselinePort.WriteDoubleWord(offset,value); }
        public string Prepare(string directory)
        {
            path=directory;
            Check(port.ReadDoubleWord(0)==0x44444444 && port.ReadDoubleWord(12)==0,"attachment preserves GPIO configuration/latch");
            Check(thermal.TemperatureCelsius==25 && thermal.ADCValue==3911 && thermal.Updates==0,"initial physical/ADC values");
            Check(observer.EdgeCount==0 && observer.RowCount==1,"initial snapshot, no invented edge");
            second=new PassiveBedThermalObserver(machine,port,thermal);
            capped=new PassiveBedThermalObserver(machine,port,thermal,maximumRows:2);
            broken=new PassiveBedThermalObserver(machine,port,thermal,maximumRows:20);
            observer.Start(path+"/live.csv");capped.Start(path+"/capped-live.csv");
            bool failed=false;try{observer.Start(path+"/duplicate.csv");}catch(InvalidOperationException){failed=true;}
            Check(failed,"reject duplicate active stream");
            failed=false;try{observer.WriteCsv(path+"/live.csv");}catch(InvalidOperationException){failed=true;}
            Check(failed,"reject live capture overwrite");
            failed=false;try{observer.OnGPIO(1,true);}catch(ArgumentOutOfRangeException){failed=true;}
            Check(failed,"reject non-PA0 input callback");
            failed=false;try{broken.Start(path);}catch(Exception){failed=true;}
            Check(failed && broken.StreamErrorCount==1 && !broken.Streaming,"failed stream creation exposed, no active writer");
            Write(0,0x44444441);Write(12,1);
            Check(observer.EdgeCount==1 && second.EdgeCount==1 && capped.EdgeCount==1,"actual edge reaches multiple sinks");
            Check(observer.GetCsv().Contains("0,0,edge,PA0,1,1,1,1,25,3911,"),"resolved state/config/latch and exact timestamps");
            Check(capped.StreamRowsWritten==2 && capped.StreamCapacityReached,"hard live stream cap closes writer");
            Same();return "BED OBSERVER PREPARED";
        }
        public string Switch()
        {
            Write(12,0);
            Check(observer.GetCsv().Contains("2500,2500000,edge,PA0,0,0,1,0,"),"2.5ms real-edge timestamp in both local clocks");
            Check(capped.StreamDroppedRows==1 && capped.DroppedRows==2,"separate bounded-buffer/live-stream drops");
            Same();return "BED OBSERVER SWITCHED";
        }
        public string CheckPWM()
        {
            double expected=25+(200*.25/1.5)*(1-Math.Exp(-1.5*.01/600));
            Check(Math.Abs(thermal.TemperatureCelsius-expected)<1e-11 && thermal.LastHeaterDuty==.25,"unchanged plant integrates quarter-window actual GPIO");
            Check(thermal.Updates==1,"one and only one automatic physics tick");
            Same();return "BED OBSERVER PWM PASS";
        }
        public string Finish()
        {
            Check(observer.SampleCount==1 && thermal.Updates==10,"100ms sampling independent of10ms physics updates");
            Check(observer.GetCsv().Contains("100000,100000000,sample,,,0,1,0,"),"precise100ms sample");
            Same();
            Check(!thermal.Overtemperature && !thermal.HeaterLatchedOff && thermal.SensorFault=="none","unchanged normal environmental guards and fault state");
            Check(thermal.LastFanDuty==0,"no invented fan or extra thermal input");
            double heat=thermal.TemperatureCelsius;ulong updates=thermal.Updates;
            observer.Mark("marker,with\nline");observer.Reset();
            Check(thermal.TemperatureCelsius==heat && thermal.Updates==updates,"mark/reset never advances or clears physical state");
            Check(observer.GetCsv().Contains("snapshot:marker;with line"),"CSV-safe marker");
            second.Clear();Check(second.RowCount==1 && second.EdgeCount==0,"clear only observer storage");
            var initialHigh=new PassiveBedThermalObserver(machine,port,thermal);
            Write(12,1);
            var highObserver=new PassiveBedThermalObserver(machine,port,thermal);
            Check(highObserver.EdgeCount==0 && highObserver.GetCsv().Contains("snapshot:observer_attached,,,1,1,1,"),"attach synchronizes actual initial high without inventing edge");
            Write(12,0);Same();
            thermal.SetSensorFault("open");observer.Mark("negative_test_open");
            Check(observer.GetCsv().Contains(",4095,B3950 100k 4700ohm illustrative divider,open,"),"existing open fault exported unchanged");
            thermal.SetSensorFault("short");observer.Mark("negative_test_short");
            Check(observer.GetCsv().Contains(",0,B3950 100k 4700ohm illustrative divider,short,"),"existing short fault exported unchanged");
            Check(thermal.TemperatureCelsius==heat,"negative-only sensor faults preserve stored heat");
            observer.WriteCsv(path+"/buffer.csv");observer.Stop();observer.WriteStreamStatus(path+"/live-status.json");
            capped.WriteCsv(path+"/capped-buffer.csv");capped.Stop();capped.WriteStreamStatus(path+"/capped-status.json");
            broken.WriteStreamStatus(path+"/failed-status.json");
            Check(observer.StreamErrorCount==0 && observer.StreamDroppedRows==0 && !observer.StreamWriteOutcomeUncertain,"complete stream has no lost/uncertain writes");
            File.WriteAllText(path+"/assertions.json","{\"passed\":true,\"assertions\":"+checks+",\"native_firmware_run\":false,\"final_updates\":"+thermal.Updates+"}\n");
            return "PASSIVE BED OBSERVER TESTS PASS: "+checks;
        }
        private readonly IMachine machine;private readonly AT32GPIO port,baselinePort;
        private readonly VirtualPrinterThermal thermal,baseline;private readonly PassiveBedThermalObserver observer;
        private PassiveBedThermalObserver second,capped,broken;private string path;private int checks;
    }
}
