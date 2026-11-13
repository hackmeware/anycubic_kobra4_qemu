// SPDX-License-Identifier: MIT
// Purely virtual heater + NTC environment. No physical outputs or safety guarantees.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.AT32
{
    public class VirtualPrinterThermal : IPeripheral, IGPIOReceiver
    {
        public VirtualPrinterThermal(IMachine machine, AT32ADC adc, int channel,
            double heaterPowerWatts = 40, double heatCapacityJoulesPerKelvin = 20,
            double conductanceWattsPerKelvin = 0.2, double ambientCelsius = 25,
            double nominalResistanceOhms = 100000, double betaKelvin = 3950,
            double nominalCelsius = 25, double pullResistanceOhms = 4700,
            uint adcMaximum = 4095, bool thermistorToGround = true,
            double fanConductanceWattsPerKelvin = 0.3, double maximumCelsius = 400,
            bool stopHeaterAtMaximum = true, uint updateMicroseconds = 10000,
            bool heaterActiveHigh = true, bool fanActiveHigh = true)
        {
            if(adc == null) throw new ArgumentNullException("adc");
            if(channel < 0 || channel > 17) throw new ArgumentOutOfRangeException("channel");
            Positive(heaterPowerWatts, "heaterPowerWatts"); Positive(heatCapacityJoulesPerKelvin, "heatCapacityJoulesPerKelvin");
            Nonnegative(conductanceWattsPerKelvin, "conductanceWattsPerKelvin");
            Nonnegative(fanConductanceWattsPerKelvin, "fanConductanceWattsPerKelvin");
            Positive(nominalResistanceOhms, "nominalResistanceOhms"); Positive(betaKelvin, "betaKelvin");
            Positive(pullResistanceOhms, "pullResistanceOhms");
            Positive(ambientCelsius + 273.15, "ambientCelsius"); Positive(nominalCelsius + 273.15, "nominalCelsius");
            if(!Finite(maximumCelsius) || maximumCelsius <= ambientCelsius) throw new ArgumentOutOfRangeException("maximumCelsius");
            if(adcMaximum == 0 || adcMaximum > 4095 || updateMicroseconds == 0) throw new ArgumentOutOfRangeException("ADC maximum or update period");
            this.adc = adc; this.channel = channel; power = heaterPowerWatts; capacity = heatCapacityJoulesPerKelvin;
            conductance = conductanceWattsPerKelvin; ambient = ambientCelsius;
            nominalResistance = nominalResistanceOhms; beta = betaKelvin; nominalKelvin = nominalCelsius + 273.15;
            pullResistance = pullResistanceOhms; adcMax = adcMaximum; toGround = thermistorToGround;
            fanConductance = fanConductanceWattsPerKelvin; maximum = maximumCelsius; stopAtMaximum = stopHeaterAtMaximum;
            interval = updateMicroseconds; this.heaterActiveHigh = heaterActiveHigh; this.fanActiveHigh = fanActiveHigh;
            timer = new LimitTimer(machine.ClockSource, 1000000, this, "virtual thermal update", interval,
                direction: Direction.Ascending, workMode: WorkMode.Periodic, enabled: true, eventEnabled: true);
            timer.LimitReached += Tick;
            ColdReset();
        }
        public double TemperatureCelsius { get; private set; }
        public uint ADCValue { get; private set; }
        public double LastHeaterDuty { get; private set; }
        public double LastFanDuty { get; private set; }
        public bool Overtemperature { get; private set; }
        public bool HeaterLatchedOff { get; private set; }
        public string SensorFault { get { return fault; } }
        public ulong Updates { get; private set; }
        public bool AutomaticUpdates { get { return timer.Enabled; } }
        // MCU reset does not cool the environment or repair an injected sensor fault.
        public void Reset()
        {
            timer.Reset(); timer.Value = 0; timer.Enabled = true;
            heaterDuty = fanDuty = 0; heaterIntegral = fanIntegral = 0;
            lastOffset = 0; directHeater = directFan = false;
            LastHeaterDuty = LastFanDuty = 0; Publish();
        }
        // Explicit scenario reset, never implied by an MCU reset.
        public void ColdReset()
        {
            TemperatureCelsius = ambient; Overtemperature = HeaterLatchedOff = false;
            fault = "none"; Updates = 0; Reset();
        }
        // Input 0 is the heater, input 1 an optional fan. No board pin identities are assumed.
        public void OnGPIO(int number, bool value)
        {
            if(number != 0 && number != 1) throw new ArgumentOutOfRangeException("number");
            Accumulate(timer.Value);
            if(number == 0 && !directHeater) heaterDuty = value == heaterActiveHigh ? 1 : 0;
            if(number == 1 && !directFan) fanDuty = value == fanActiveHigh ? 1 : 0;
        }
        // Direct mode ignores the corresponding GPIO until UseGPIOInputs or Reset.
        public void SetDutyCycle(double duty) { Duty(duty); Accumulate(timer.Value); directHeater = true; heaterDuty = duty; }
        public void SetFanDutyCycle(double duty) { Duty(duty); Accumulate(timer.Value); directFan = true; fanDuty = duty; }
        public void UseGPIOInputs()
        {
            Accumulate(timer.Value); directHeater = directFan = false; heaterDuty = fanDuty = 0;
            // Inputs remain inactive until the next GPIO callback, avoiding an invented level.
        }
        public void SetSensorFault(string value)
        {
            if(value != "none" && value != "open" && value != "short") throw new ArgumentException("Fault must be none, open, or short");
            fault = value; Publish();
        }
        public void SetAutomaticUpdates(bool enabled)
        {
            if(timer.Enabled == enabled) return;
            // Mode changes intentionally discard the incomplete PWM window.
            timer.Enabled = enabled; timer.Value = 0; lastOffset = 0; heaterIntegral = fanIntegral = 0;
        }
        // Deterministic synthetic experiment API: refuses to double-advance a running timer.
        public void Advance(double seconds)
        {
            if(timer.Enabled) throw new InvalidOperationException("Disable automatic updates before manual Advance");
            Positive(seconds, "seconds"); Integrate(seconds, heaterDuty, fanDuty);
        }
        public uint ConvertTemperature(double celsius)
        {
            Positive(celsius + 273.15, "celsius");
            double logRatio = Math.Log(nominalResistance / pullResistance) + beta * (1 / (celsius + 273.15) - 1 / nominalKelvin);
            // Stable logistic conversion avoids overflow for very cold synthetic inputs.
            double fraction = logRatio >= 0 ? 1 / (1 + Math.Exp(-logRatio)) : Math.Exp(logRatio) / (1 + Math.Exp(logRatio));
            if(!toGround) fraction = 1 - fraction;
            return (uint)Math.Round(adcMax * fraction, MidpointRounding.AwayFromZero);
        }
        private void Accumulate(ulong offset)
        {
            if(offset < lastOffset) return; // Tick handles the wrap boundary.
            var elapsed = offset - lastOffset;
            heaterIntegral += elapsed * heaterDuty; fanIntegral += elapsed * fanDuty; lastOffset = offset;
        }
        private void Tick()
        {
            Accumulate(interval);
            Integrate(interval / 1000000.0, heaterIntegral / interval, fanIntegral / interval);
            lastOffset = 0; heaterIntegral = fanIntegral = 0;
        }
        private void Integrate(double seconds, double heater, double fan)
        {
            LastHeaterDuty = HeaterLatchedOff ? 0 : heater; LastFanDuty = fan;
            var loss = conductance + fanConductance * fan;
            var input = power * LastHeaterDuty;
            double next;
            if(loss == 0) next = TemperatureCelsius + input * seconds / capacity;
            else
            {
                var equilibrium = ambient + input / loss;
                next = equilibrium + (TemperatureCelsius - equilibrium) * Math.Exp(-loss * seconds / capacity);
            }
            if(next >= maximum)
            {
                if(!Overtemperature) this.Log(LogLevel.Warning, "VIRTUAL thermal environment reached {0} C; temperature clamped. This is not a hardware safety model.", maximum);
                Overtemperature = true;
                if(stopAtMaximum) HeaterLatchedOff = true;
                next = maximum;
            }
            TemperatureCelsius = Math.Max(ambient, Math.Min(maximum, next));
            Updates++; Publish();
        }
        private void Publish()
        {
            ADCValue = fault == "open" ? (toGround ? adcMax : 0) : fault == "short" ? (toGround ? 0 : adcMax) : ConvertTemperature(TemperatureCelsius);
            adc.SetChannelValue(channel, ADCValue);
        }
        private static bool Finite(double value) { return !double.IsNaN(value) && !double.IsInfinity(value); }
        private static void Positive(double value, string name) { if(!Finite(value) || value <= 0) throw new ArgumentOutOfRangeException(name); }
        private static void Nonnegative(double value, string name) { if(!Finite(value) || value < 0) throw new ArgumentOutOfRangeException(name); }
        private static void Duty(double value) { if(!Finite(value) || value < 0 || value > 1) throw new ArgumentOutOfRangeException("duty"); }
        private readonly AT32ADC adc;
        private readonly int channel;
        private readonly LimitTimer timer;
        private readonly ulong interval;
        private readonly double power, capacity, conductance, ambient, nominalResistance, beta, nominalKelvin, pullResistance, fanConductance, maximum;
        private readonly uint adcMax;
        private readonly bool toGround, stopAtMaximum, heaterActiveHigh, fanActiveHigh;
        private double heaterDuty, fanDuty, heaterIntegral, fanIntegral;
        private ulong lastOffset;
        private bool directHeater, directFan;
        private string fault;
    }
}
