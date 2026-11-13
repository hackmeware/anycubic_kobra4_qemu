// Independent analytic checks running against the actual Renode peripheral.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    public class VirtualThermalTests : IDoubleWordPeripheral, IKnownSize
    {
        public VirtualThermalTests(IMachine machine, AT32ADC adc, VirtualPrinterThermal thermal)
        { this.machine = machine; this.adc = adc; this.thermal = thermal; }
        public long Size { get { return 4; } }
        public void Reset() { }
        public uint ReadDoubleWord(long offset) { return 0; }
        public void WriteDoubleWord(long offset, uint value) { }
        private void Near(double value, double expected, double error, string label)
        { if(double.IsNaN(value) || Math.Abs(value-expected) > error) throw new Exception(label + ": " + value + " != " + expected); checks++; }
        private void True(bool value, string label) { if(!value) throw new Exception(label); checks++; }
        private void Reject(Action action, string label)
        { try { action(); } catch(ArgumentException) { checks++; return; } throw new Exception(label); }
        public string Run()
        {
            checks=0; thermal.ColdReset(); Near(thermal.TemperatureCelsius,25,0,"ambient reset");
            Near(thermal.ADCValue,3911,0,"100k 4700 divider");
            thermal.SetAutomaticUpdates(false); thermal.SetDutyCycle(1); thermal.Advance(100);
            Near(thermal.TemperatureCelsius,25+200*(1-Math.Exp(-1)),1e-10,"analytic time constant");
            thermal.Advance(10000); Near(thermal.TemperatureCelsius,225,1e-8,"full equilibrium");
            True(thermal.ADCValue < thermal.ConvertTemperature(25),"NTC decreasing ADC");
            thermal.SetDutyCycle(0.5); thermal.Advance(10000); Near(thermal.TemperatureCelsius,125,1e-8,"half equilibrium");
            thermal.SetFanDutyCycle(1); thermal.Advance(10000); Near(thermal.TemperatureCelsius,65,1e-8,"fan equilibrium");
            thermal.SetDutyCycle(0); thermal.SetFanDutyCycle(0); thermal.Advance(100);
            Near(thermal.TemperatureCelsius,25+40*Math.Exp(-1),1e-8,"cooling");
            thermal.Advance(10000); Near(thermal.TemperatureCelsius,25,1e-8,"ambient floor");
            thermal.SetSensorFault("open"); Near(thermal.ADCValue,4095,0,"open high");
            adc.WriteDoubleWord(0x34,1); adc.WriteDoubleWord(8,0x5E0001); Near(adc.ReadDoubleWord(0x4C),4095,0,"fault reaches ADC");
            thermal.SetSensorFault("short"); Near(thermal.ADCValue,0,0,"short low");
            thermal.SetSensorFault("none"); Near(thermal.ADCValue,3911,0,"sensor recovery");
            Near(thermal.ConvertTemperature(100),2447,0,"beta at 100C");
            Reject(()=>thermal.SetDutyCycle(-0.1),"negative duty accepted"); Reject(()=>thermal.SetDutyCycle(double.NaN),"NaN accepted");
            Reject(()=>thermal.SetSensorFault("unknown"),"invalid fault accepted"); Reject(()=>thermal.Advance(0),"zero duration accepted");
            var high = new VirtualPrinterThermal(machine,adc,2,thermistorToGround:false);
            high.SetAutomaticUpdates(false); Near(high.ADCValue,184,0,"high-side divider");
            high.SetSensorFault("open"); Near(high.ADCValue,0,0,"high-side open");
            high.SetSensorFault("short"); Near(high.ADCValue,4095,0,"high-side short");
            var limited = new VirtualPrinterThermal(machine,adc,3,maximumCelsius:50);
            limited.SetAutomaticUpdates(false); limited.SetDutyCycle(1); limited.Advance(1000);
            Near(limited.TemperatureCelsius,50,0,"bounded temperature"); True(limited.Overtemperature && limited.HeaterLatchedOff,"visible trip");
            limited.SetSensorFault("open"); limited.Advance(100); Near(limited.ADCValue,4095,0,"trip cannot conceal open fault");
            True(limited.TemperatureCelsius < 50,"latched heater cools");
            var beforeReset = limited.TemperatureCelsius;
            limited.Reset(); limited.SetAutomaticUpdates(false);
            Near(limited.TemperatureCelsius,beforeReset,0,"MCU reset retains heat");
            True(limited.SensorFault == "open" && limited.HeaterLatchedOff && limited.Overtemperature,"MCU reset retains fault and trip");
            limited.ColdReset(); limited.SetAutomaticUpdates(false); True(!limited.HeaterLatchedOff,"cold reset clears latch");
            var insulated = new VirtualPrinterThermal(machine,adc,4,conductanceWattsPerKelvin:0);
            insulated.SetAutomaticUpdates(false); insulated.SetDutyCycle(0.5); insulated.Advance(10);
            Near(insulated.TemperatureCelsius,35,1e-10,"zero-loss linear heating");
            thermal.ColdReset(); thermal.SetDutyCycle(1);
            return "VIRTUAL THERMAL TESTS PASS: " + checks;
        }
        public string CheckTimer()
        {
            True(thermal.Updates >= 9 && thermal.Updates <= 11,"virtual timer update count");
            Near(thermal.TemperatureCelsius,25+200*(1-Math.Exp(-(double)thermal.Updates*0.0001)),1e-9,"virtual timer dynamics");
            return "VIRTUAL THERMAL TIMER PASS";
        }
        public string CheckPWM()
        {
            Near(thermal.LastHeaterDuty,0.25,0.0001,"GPIO PWM duty");
            Near(thermal.TemperatureCelsius,25+50*(1-Math.Exp(-0.0001)),1e-8,"GPIO PWM heating");
            return "VIRTUAL THERMAL PWM PASS";
        }
        private readonly IMachine machine;
        private readonly AT32ADC adc;
        private readonly VirtualPrinterThermal thermal;
        private int checks;
    }
}
