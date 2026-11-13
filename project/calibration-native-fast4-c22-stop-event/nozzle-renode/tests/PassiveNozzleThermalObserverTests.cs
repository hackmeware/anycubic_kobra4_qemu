// SPDX-License-Identifier: MIT
// Synthetic GPIO output writes only. No thermal actuation, fault or temperature injection.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    public class PassiveNozzleThermalObserverTests : IDoubleWordPeripheral, IKnownSize
    {
        public PassiveNozzleThermalObserverTests(IMachine machine, AT32GPIO portB,
            VirtualPrinterThermal thermal, PassiveNozzleThermalObserver observer)
        { this.machine = machine; this.portB = portB; this.thermal = thermal; this.observer = observer; }
        public long Size { get { return 4; } }
        public void Reset() { }
        public uint ReadDoubleWord(long offset) { return 0; }
        public void WriteDoubleWord(long offset, uint value) { }
        private void Check(bool condition, string label)
        { if(!condition) throw new Exception(label); checks++; }
        private void UnchangedThermal()
        {
            Check(thermal.TemperatureCelsius == 25 && thermal.ADCValue == 4023, "observer/GPIO activity did not change physical temperature or ADC");
            Check(thermal.LastHeaterDuty == 0 && thermal.LastFanDuty == 0, "no actuator connection or invented duty");
            Check(thermal.SensorFault == "none" && !thermal.SensorCurveOutOfRange && !thermal.Overtemperature && !thermal.HeaterLatchedOff, "observer did not modify model guard/fault state");
        }
        public string Prepare()
        {
            checks = 0;
            Check(portB.ReadDoubleWord(4) == 0x44444444 && portB.ReadDoubleWord(12) == 0, "profile attachment did not configure GPIO");
            Check(observer.EdgeCount == 0 && observer.RowCount == 1, "attachment snapshot is not a GPIO transition");
            second = new PassiveNozzleThermalObserver(machine,portB,thermal);
            capped = new PassiveNozzleThermalObserver(machine,portB,thermal,maximumRows:2);
            UnchangedThermal();
            portB.WriteDoubleWord(4,0x44444411);
            Check(observer.EdgeCount == 0,"configuration-only change did not invent edges");
            portB.WriteDoubleWord(12,0x100);
            Check(observer.EdgeCount == 1 && second.EdgeCount == 1 && capped.EdgeCount == 1,"simultaneous passive sinks receive actual PB8 rise");
            Check(observer.GetCsv().Contains("0,edge,PB8,1,1,0,1,1,1,0,25,4023,"),"actual rise/config/latch/thermal timestamp captured");
            UnchangedThermal();
            return "PASSIVE NOZZLE OBSERVER PREPARED";
        }
        public string SwitchOutputs()
        {
            portB.WriteDoubleWord(12,0x200);
            Check(observer.EdgeCount==3 && second.EdgeCount==3,"PB8 fall and PB9 rise both recorded");
            var csv=observer.GetCsv();
            Check(csv.Contains("2500,edge,PB8,0,") && csv.Contains("2500,edge,PB9,1,"),"independent edge timestamps retained");
            portB.WriteDoubleWord(12,0x200);
            Check(observer.EdgeCount==3,"unchanged GPIO output does not create transitions");
            Check(capped.RowCount==2 && capped.CapacityReached && capped.DroppedRows==2,"bounded trace reports lost rows");
            portB.WriteDoubleWord(12,0x300);
            Check(observer.EdgeCount==4 && second.EdgeCount==4,"continued simultaneous sink observation");
            UnchangedThermal();
            return "PASSIVE NOZZLE OBSERVER OUTPUTS SWITCHED";
        }
        public string Finish()
        {
            UnchangedThermal();
            Check(thermal.Updates>=10,"physical thermal timer continued independently");
            Check(observer.SampleCount==1,"default 100ms periodic snapshot occurred");
            Check(observer.GetCsv().Contains("100000,sample,,,1,1,1,1,1,1,25,4023,"),"periodic sample observes both outputs high but no heating");
            Check(observer.GetCsv()==second.GetCsv(),"adding observers preserves every original sink event");
            var configuration=portB.ReadDoubleWord(4);var latch=portB.ReadDoubleWord(12);
            observer.Mark("native_probe,phase\nmarker");observer.Reset();
            Check(observer.GetCsv().Contains("snapshot:native_probe;phase marker"),"markers cannot corrupt CSV rows");
            Check(observer.GetCsv().Contains("snapshot:MCU_reset_observed"),"observer reset is only an observation marker");
            Check(configuration==portB.ReadDoubleWord(4) && latch==portB.ReadDoubleWord(12),"mark/reset cannot change GPIO state");
            UnchangedThermal();
            var before=observer.EdgeCount;
            second.Clear();
            Check(second.EdgeCount==0 && second.RowCount==1 && second.GetCsv().Contains("102500,snapshot:observer_cleared"),"clear only resets observer storage; clock retained");
            Check(observer.EdgeCount==before,"clearing one sink does not affect another");
            UnchangedThermal();
            return "PASSIVE NOZZLE OBSERVER TESTS PASS: " + checks;
        }
        public void WriteCappedCsv(string path) { capped.WriteCsv(path); }
        private readonly IMachine machine;
        private readonly AT32GPIO portB;
        private readonly VirtualPrinterThermal thermal;
        private readonly PassiveNozzleThermalObserver observer;
        private PassiveNozzleThermalObserver second, capped;
        private int checks;
    }
}
