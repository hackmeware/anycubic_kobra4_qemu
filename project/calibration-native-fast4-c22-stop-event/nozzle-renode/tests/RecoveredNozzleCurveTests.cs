// SPDX-License-Identifier: MIT
// CPU-free synthetic tests of the actual peripheral. Not native heating proof.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    public class RecoveredNozzleCurveTests : IDoubleWordPeripheral, IKnownSize
    {
        public RecoveredNozzleCurveTests(IMachine machine, AT32ADC adc, VirtualPrinterThermal thermal)
        { this.machine = machine; this.adc = adc; this.thermal = thermal; }
        public long Size { get { return 4; } }
        public void Reset() { }
        public uint ReadDoubleWord(long offset) { return 0; }
        public void WriteDoubleWord(long offset, uint value) { }
        private void Check(bool condition, string label)
        { if(!condition) throw new Exception(label); checks++; }
        private void Near(double actual, double expected, double tolerance, string label)
        { Check(!double.IsNaN(actual) && Math.Abs(actual-expected) <= tolerance, label + ": " + actual + " != " + expected); }
        private void Reject(Action action, string label)
        { try { action(); } catch(ArgumentException) { checks++; return; } throw new Exception(label); }
        private VirtualPrinterThermal Recovered(int channel, double ambient = 25, double maximum = 400, double loss = 0.2)
        {
            var result = new VirtualPrinterThermal(machine, adc, channel, ambientCelsius:ambient,
                maximumCelsius:maximum, conductanceWattsPerKelvin:loss, useRecoveredNozzleCurve:true);
            result.SetAutomaticUpdates(false); return result;
        }
        public string Run()
        {
            checks = 0; thermal.ColdReset(); thermal.SetAutomaticUpdates(false);
            Check(thermal.SensorCurve == "NTC ZM3863 HNS112HC4570G0", "profile selected recovered curve");
            Check(!thermal.SensorCurveOutOfRange, "25C lies inside recovered table");
            Near(thermal.ADCValue, 4023, 0, "calibrated ambient ADC");
            Near(thermal.TemperatureCelsius, 25, 0, "physical ambient not adjusted to ADC quantization");
            for(var i=0; i<RecoveredNozzleCurveVectors.Samples.GetLength(0); i++)
                Near(thermal.ConvertTemperature(RecoveredNozzleCurveVectors.Samples[i,0]),
                    RecoveredNozzleCurveVectors.Samples[i,1], 0, "native conversion vector " + i);
            // Guards remain observable: 320C model input is near firmware upper limit;
            // temperatures above it are not clipped to a permissible ADC reading.
            Check(thermal.ConvertTemperature(325) < 121, "native overtemperature remains out of configured range");
            Check(thermal.ConvertTemperature(-5) > 4074, "native undertemperature remains out of configured range");
            Near(thermal.ConvertTemperature(-41), 4095, 0, "outside table cold fault rail");
            Near(thermal.ConvertTemperature(361), 0, 0, "outside table hot fault rail");
            Reject(()=>thermal.ConvertTemperature(double.NaN), "NaN temperature accepted");
            Reject(()=>thermal.ConvertTemperature(double.PositiveInfinity), "infinite temperature accepted");
            Reject(()=>thermal.ConvertTemperature(-273.15), "absolute zero accepted");
            Reject(()=>new VirtualPrinterThermal(machine,adc,7,pullResistanceOhms:10000,useRecoveredNozzleCurve:true), "unverified pullup accepted");
            Reject(()=>new VirtualPrinterThermal(machine,adc,7,adcMaximum:1023,useRecoveredNozzleCurve:true), "unverified ADC maximum accepted");
            Reject(()=>new VirtualPrinterThermal(machine,adc,7,thermistorToGround:false,useRecoveredNozzleCurve:true), "unverified circuit polarity accepted");
            var legacy = new VirtualPrinterThermal(machine,adc,1); legacy.SetAutomaticUpdates(false);
            Check(legacy.SensorCurve == "beta", "legacy default unchanged");
            Near(legacy.ADCValue,3911,0,"legacy25C"); Near(legacy.ConvertTemperature(100),2447,0,"legacy100C");
            var high = new VirtualPrinterThermal(machine,adc,2,thermistorToGround:false); high.SetAutomaticUpdates(false);
            Near(high.ADCValue,184,0,"legacy high-side ambient");
            high.SetSensorFault("open"); Near(high.ADCValue,0,0,"legacy high-side open");
            high.SetSensorFault("short"); Near(high.ADCValue,4095,0,"legacy high-side short");
            thermal.SetSensorFault("open"); Near(thermal.ADCValue,4095,0,"recovered open rail");
            adc.WriteDoubleWord(0x34,0); adc.WriteDoubleWord(8,0x5E0001);
            Near(adc.ReadDoubleWord(0x4C),4095,0,"open reaches actual ADC0");
            thermal.SetDutyCycle(1); legacy.SetDutyCycle(1);
            thermal.Advance(10); legacy.Advance(10);
            Near(thermal.TemperatureCelsius,legacy.TemperatureCelsius,0,"open sensor does not alter physical heating");
            Near(thermal.ADCValue,4095,0,"open persists while heating");
            thermal.SetSensorFault("short"); Near(thermal.ADCValue,0,0,"recovered short rail");
            thermal.SetFanDutyCycle(1); legacy.SetFanDutyCycle(1);
            thermal.Advance(20); legacy.Advance(20);
            Near(thermal.TemperatureCelsius,legacy.TemperatureCelsius,0,"curve does not alter fan thermal state");
            var warm = thermal.TemperatureCelsius;
            thermal.Reset(); thermal.SetAutomaticUpdates(false);
            Near(thermal.TemperatureCelsius,warm,0,"MCU reset retains heat");
            Check(thermal.SensorFault == "short" && thermal.SensorCurve != "beta", "MCU reset retains fault and selected curve");
            Near(thermal.ADCValue,0,0,"reset does not repair short");
            thermal.SetSensorFault("none"); Near(thermal.ADCValue,thermal.ConvertTemperature(warm),0,"repair senses retained heat");
            var limited = Recovered(3,maximum:50);
            limited.SetDutyCycle(1); limited.Advance(1000);
            Near(limited.TemperatureCelsius,50,0,"existing maximum clamp");
            Check(limited.Overtemperature && limited.HeaterLatchedOff,"existing latch retained");
            limited.SetSensorFault("open"); limited.Advance(100);
            Check(limited.TemperatureCelsius<50,"latched heater cools"); Near(limited.ADCValue,4095,0,"latch cannot conceal open");
            var retained = limited.TemperatureCelsius; limited.Reset(); limited.SetAutomaticUpdates(false);
            Near(limited.TemperatureCelsius,retained,0,"latched reset retains heat");
            Check(limited.HeaterLatchedOff && limited.Overtemperature && limited.SensorFault=="open","latched reset retains all guard state");
            limited.ColdReset(); limited.SetAutomaticUpdates(false);
            Check(!limited.HeaterLatchedOff && !limited.Overtemperature && limited.SensorFault=="none","explicit cold reset clears guard state");
            Near(limited.ADCValue,4023,0,"cold reset retains recovered curve");
            var outside = Recovered(4,loss:0);
            outside.SetDutyCycle(1); outside.Advance(180);
            Near(outside.TemperatureCelsius,385,1e-10,"physical heat is not clamped to table360C");
            Check(outside.SensorCurveOutOfRange && !outside.Overtemperature && !outside.HeaterLatchedOff,"curve diagnostic separate from maximum latch");
            Near(outside.ADCValue,0,0,"hot unsupported state publishes invalid rail");
            outside.Reset(); outside.SetAutomaticUpdates(false);
            Check(outside.SensorCurveOutOfRange,"reset cannot hide unsupported temperature");
            Near(outside.TemperatureCelsius,385,1e-10,"unsupported heat survives reset");
            outside.SetSensorFault("open"); Near(outside.ADCValue,4095,0,"explicit open takes precedence over hot curve rail");
            outside.SetSensorFault("none"); Near(outside.ADCValue,0,0,"fault repair cannot conceal unsupported heat");
            outside.SetDutyCycle(1); outside.Advance(100);
            Check(outside.Overtemperature && outside.HeaterLatchedOff,"original maximum guard still trips beyond curve range");
            Near(outside.TemperatureCelsius,400,0,"original maximum remains400C");
            outside.ColdReset(); outside.SetAutomaticUpdates(false);
            Check(!outside.SensorCurveOutOfRange,"explicit cold reset restores supported physical temperature");
            Near(outside.ADCValue,4023,0,"cold reset repairs unsupported reading only by cooling state");
            var cold = Recovered(5,ambient:-41);
            Check(cold.SensorCurveOutOfRange,"cold curve diagnostic"); Near(cold.TemperatureCelsius,-41,0,"cold physical state retained");
            Near(cold.ADCValue,4095,0,"cold unsupported rail");
            cold.SetDutyCycle(1); cold.Advance(1);
            Check(!cold.SensorCurveOutOfRange && cold.ADCValue<4095,"physical warming back into table restores conversion");
            thermal.ColdReset();
            return "RECOVERED NOZZLE CURVE TESTS PASS: " + checks;
        }
        public string CheckUnconnectedTimer()
        {
            Check(thermal.Updates>=9 && thermal.Updates<=11,"timer updates continue");
            Near(thermal.TemperatureCelsius,25,0,"unconnected profile cannot create heat");
            Near(thermal.LastHeaterDuty,0,0,"no invented heater duty");
            Near(thermal.LastFanDuty,0,0,"no invented fan duty");
            Near(thermal.ADCValue,4023,0,"ambient sensor updates continue");
            return "RECOVERED NOZZLE UNCONNECTED TIMER PASS";
        }
        public string CheckPWM()
        {
            Near(thermal.LastHeaterDuty,0.25,0.0001,"synthetic GPIO PWM integration unchanged");
            Near(thermal.TemperatureCelsius,25+50*(1-Math.Exp(-0.0001)),1e-8,"synthetic PWM thermal response unchanged");
            Near(thermal.ADCValue,thermal.ConvertTemperature(thermal.TemperatureCelsius),0,"timer publishes recovered conversion");
            return "RECOVERED NOZZLE SYNTHETIC PWM PASS";
        }
        private readonly IMachine machine;
        private readonly AT32ADC adc;
        private readonly VirtualPrinterThermal thermal;
        private int checks;
    }
}
