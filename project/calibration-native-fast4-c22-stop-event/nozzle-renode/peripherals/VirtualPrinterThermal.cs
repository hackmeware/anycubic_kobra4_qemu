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
            bool heaterActiveHigh = true, bool fanActiveHigh = true,
            bool useRecoveredNozzleCurve = false)
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
            if(useRecoveredNozzleCurve && (pullResistanceOhms != 4700 || adcMaximum != 4095 || !thermistorToGround))
                throw new ArgumentException("The recovered nozzle profile requires the verified 4700-ohm pullup, 12-bit ADC and ground-connected NTC");
            this.adc = adc; this.channel = channel; power = heaterPowerWatts; capacity = heatCapacityJoulesPerKelvin;
            conductance = conductanceWattsPerKelvin; ambient = ambientCelsius;
            nominalResistance = nominalResistanceOhms; beta = betaKelvin; nominalKelvin = nominalCelsius + 273.15;
            pullResistance = pullResistanceOhms; adcMax = adcMaximum; toGround = thermistorToGround;
            fanConductance = fanConductanceWattsPerKelvin; maximum = maximumCelsius; stopAtMaximum = stopHeaterAtMaximum;
            interval = updateMicroseconds; this.heaterActiveHigh = heaterActiveHigh; this.fanActiveHigh = fanActiveHigh;
            recoveredNozzleCurve = useRecoveredNozzleCurve;
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
        public string SensorCurve { get { return recoveredNozzleCurve ? "NTC ZM3863 HNS112HC4570G0" : "beta"; } }
        // A separate visible diagnostic: neither physical heat nor an injected fault is changed.
        public bool SensorCurveOutOfRange { get { return recoveredNozzleCurve && !RecoveredTemperatureSupported(TemperatureCelsius); } }
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
            if(recoveredNozzleCurve)
            {
                // Unsupported temperatures produce an invalid-reading rail, not a plausible
                // clamped temperature. Native firmware/host checks decide how to respond.
                if(celsius < RecoveredNozzleTable[0, 0]) return adcMax;
                if(celsius > RecoveredNozzleTable[RecoveredNozzleTable.GetLength(0)-1, 0]) return 0;
                for(var i = 0; i < RecoveredNozzleSegments.GetLength(0); i++)
                {
                    var upperResistance = RecoveredNozzleSegments[i, 0];
                    var slope = RecoveredNozzleSegments[i, 1];
                    var intercept = RecoveredNozzleSegments[i, 2];
                    // Original native inverse chooses the first segment whose upper
                    // resistance evaluates to a temperature <= the requested temperature.
                    if(celsius < upperResistance * slope + intercept) continue;
                    var resistance = (celsius - intercept) / slope;
                    if(!Finite(resistance) || resistance <= 0)
                        throw new InvalidOperationException("Invalid recovered nozzle resistance");
                    return (uint)Math.Round(adcMax * resistance / (pullResistance + resistance), MidpointRounding.AwayFromZero);
                }
                throw new InvalidOperationException("Recovered nozzle curve has no matching segment");
            }
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
            var unsupported = SensorCurveOutOfRange;
            if(unsupported && !curveWasOutOfRange)
                this.Log(LogLevel.Warning, "VIRTUAL recovered nozzle sensor is outside its -40..360 C lookup range at {0} C; publishing a fault rail without changing physical temperature", TemperatureCelsius);
            curveWasOutOfRange = unsupported;
            ADCValue = fault == "open" ? (toGround ? adcMax : 0) : fault == "short" ? (toGround ? 0 : adcMax) : ConvertTemperature(TemperatureCelsius);
            adc.SetChannelValue(channel, ADCValue);
        }
        private static bool RecoveredTemperatureSupported(double celsius)
        {
            return celsius >= RecoveredNozzleTable[0, 0] && celsius <= RecoveredNozzleTable[RecoveredNozzleTable.GetLength(0)-1, 0];
        }
        private static bool Finite(double value) { return !double.IsNaN(value) && !double.IsInfinity(value); }
        private static void Positive(double value, string name) { if(!Finite(value) || value <= 0) throw new ArgumentOutOfRangeException(name); }
        private static void Nonnegative(double value, string name) { if(!Finite(value) || value < 0) throw new ArgumentOutOfRangeException(name); }
        private static void Duty(double value) { if(!Finite(value) || value < 0 || value > 1) throw new ArgumentOutOfRangeException("duty"); }
        // Recovered original-host data, not measured physical sensor calibration.
        // Source: evidence/recovered-nozzle-thermal/nozzle-thermal-recovered-evidence.json
        // RAM SHA256: 2d7a9ec5a1d3477c80db01a18104f892e083d502815437b44db34a829e14ace5
        // Keep the complete factory table as provenance and range bounds.
        private static readonly double[,] RecoveredNozzleTable = new double[,]
        {
            { -40.0, 10921079.0 },
            { -25.0, 3970093.0 },
            { -20.0, 2900712.0 },
            { -15.0, 2142047.0 },
            { -10.0, 1597763.0 },
            { -5.0, 1203220.0 },
            { 0.0, 914294.0 },
            { 5.0, 700715.0 },
            { 10.0, 541408.0 },
            { 15.0, 421562.0 },
            { 20.0, 330666.0 },
            { 25.0, 261191.0 },
            { 30.0, 207694.0 },
            { 35.0, 166210.0 },
            { 40.0, 133823.0 },
            { 45.0, 108376.0 },
            { 50.0, 88257.0 },
            { 55.0, 72258.0 },
            { 60.0, 59462.0 },
            { 65.0, 49173.0 },
            { 70.0, 40855.0 },
            { 75.0, 34099.0 },
            { 80.0, 28583.0 },
            { 85.0, 24061.0 },
            { 90.0, 20336.0 },
            { 95.0, 17254.0 },
            { 100.0, 14694.0 },
            { 105.0, 12551.0 },
            { 110.0, 10772.0 },
            { 115.0, 9270.0 },
            { 120.0, 8004.0 },
            { 125.0, 6932.0 },
            { 130.0, 6023.0 },
            { 135.0, 5248.0 },
            { 140.0, 4585.0 },
            { 145.0, 4018.0 },
            { 150.0, 3530.0 },
            { 155.0, 3110.0 },
            { 160.0, 2746.0 },
            { 165.0, 2431.0 },
            { 170.0, 2158.0 },
            { 175.0, 1919.0 },
            { 180.0, 1711.0 },
            { 185.0, 1529.0 },
            { 190.0, 1369.0 },
            { 195.0, 1228.0 },
            { 200.0, 1104.0 },
            { 205.0, 994.60000000000002 },
            { 210.0, 897.70000000000005 },
            { 215.0, 811.79999999999995 },
            { 220.0, 735.5 },
            { 225.0, 667.5 },
            { 230.0, 606.89999999999998 },
            { 235.0, 552.79999999999995 },
            { 240.0, 504.30000000000001 },
            { 245.0, 460.80000000000001 },
            { 250.0, 421.80000000000001 },
            { 255.0, 386.69999999999999 },
            { 260.0, 355.0 },
            { 265.0, 326.5 },
            { 270.0, 300.60000000000002 },
            { 275.0, 277.30000000000001 },
            { 280.0, 256.10000000000002 },
            { 285.0, 236.80000000000001 },
            { 290.0, 219.30000000000001 },
            { 295.0, 203.40000000000001 },
            { 300.0, 188.90000000000001 },
            { 305.0, 175.59999999999999 },
            { 310.0, 163.5 },
            { 315.0, 152.40000000000001 },
            { 320.0, 142.19999999999999 },
            { 325.0, 132.90000000000001 },
            { 330.0, 124.3 },
            { 335.0, 116.5 },
            { 340.0, 109.2 },
            { 345.0, 102.5 },
            { 350.0, 96.400000000000006 },
            { 360.0, 78.0 },
        };
        // Upper resistance breakpoint, temperature slope, temperature intercept.
        // Exact live-native coefficients retain its small floating-point rounding differences.
        private static readonly double[,] RecoveredNozzleSegments = new double[,]
        {
            { 96.400000000000006, -0.54347826086956508, 402.39130434782606 },
            { 102.5, -0.81967233618372592, 429.01641445883189 },
            { 109.2, -0.74626865671641762, 421.49253731343282 },
            { 116.5, -0.68493122051449273, 414.79448718993842 },
            { 124.3, -0.6410256410256413, 409.67948717948724 },
            { 132.90000000000001, -0.58139555514865393, 402.26746927925609 },
            { 142.19999999999999, -0.53763405575722001, 396.45156272867666 },
            { 152.40000000000001, -0.4901959317686993, 389.70586000154975 },
            { 163.5, -0.45045020276307651, 383.64860815176303 },
            { 175.59999999999999, -0.41322314049586795, 377.56198347107443 },
            { 188.90000000000001, -0.37594002214705241, 371.01507018357819 },
            { 203.40000000000001, -0.34482744105795338, 365.13790151118769 },
            { 219.30000000000001, -0.31446528809158469, 358.96223767848454 },
            { 236.80000000000001, -0.28571433553891157, 352.65715465561425 },
            { 256.10000000000002, -0.25906739847725135, 346.3471607500241 },
            { 277.30000000000001, -0.23584912450513273, 340.4009622252733 },
            { 300.60000000000002, -0.21459216225179248, 334.50640397288885 },
            { 326.5, -0.19305023854382808, 328.03090288455985 },
            { 355.0, -0.17543859649122806, 322.28070175438597 },
            { 386.69999999999999, -0.15772870662460572, 315.99369085173504 },
            { 421.80000000000001, -0.14245019199128045, 310.08549098192208 },
            { 460.80000000000001, -0.12820508807683287, 304.07690458580458 },
            { 504.30000000000001, -0.11494249648030695, 297.96550097501881 },
            { 552.79999999999995, -0.10309275755759777, 291.98967637784006 },
            { 606.89999999999998, -0.092421420920680758, 286.09056035676116 },
            { 667.5, -0.082508284065386198, 280.07427961364527 },
            { 735.5, -0.073529411764705885, 274.08088235294116 },
            { 811.79999999999995, -0.065530799475753645, 268.1979030144168 },
            { 897.70000000000005, -0.05820720942331517, 262.25261189931001 },
            { 994.60000000000002, -0.051599593703589804, 256.32095589759041 },
            { 1104.0, -0.04570382892307006, 250.45702713106934 },
            { 1228.0, -0.040322580645161289, 244.51612903225805 },
            { 1369.0, -0.035460992907801421, 238.54609929078015 },
            { 1529.0, -0.03125, 232.78125 },
            { 1711.0, -0.027472527472527472, 227.00549450549451 },
            { 1919.0, -0.02403846153846154, 221.12980769230771 },
            { 2158.0, -0.020920502092050208, 215.14644351464435 },
            { 2431.0, -0.018315018315018316, 209.52380952380952 },
            { 2746.0, -0.015873015873015872, 203.5873015873016 },
            { 3110.0, -0.013736263736263736, 197.71978021978023 },
            { 3530.0, -0.011904761904761904, 192.02380952380952 },
            { 4018.0, -0.010245901639344262, 186.16803278688525 },
            { 4585.0, -0.0088183421516754845, 180.4320987654321 },
            { 5248.0, -0.0075414781297134239, 174.57767722473605 },
            { 6023.0, -0.0064516129032258064, 168.85806451612902 },
            { 6932.0, -0.0055005500550055009, 163.12981298129813 },
            { 8004.0, -0.0046641791044776115, 157.33208955223881 },
            { 9270.0, -0.0039494470774091624, 151.61137440758293 },
            { 10772.0, -0.0033288948069241011, 145.85885486018643 },
            { 12551.0, -0.002810567734682406, 140.27543563799887 },
            { 14694.0, -0.0023331777881474567, 134.28371441903872 },
            { 17254.0, -0.001953125, 128.69921875 },
            { 20336.0, -0.0016223231667748216, 122.99156391953277 },
            { 24061.0, -0.0013422818791946308, 117.29664429530202 },
            { 28583.0, -0.0011057054400707652, 111.60437859354268 },
            { 34099.0, -0.00090645395213923138, 105.90917331399565 },
            { 40855.0, -0.00074008288928359975, 100.23608644168146 },
            { 49173.0, -0.00060110603510459242, 94.558187064198123 },
            { 59462.0, -0.00048595587520653126, 88.895908251530756 },
            { 72258.0, -0.00039074710847139733, 83.234604563926226 },
            { 88257.0, -0.00031251953247077942, 77.582036377273582 },
            { 108376.0, -0.00024852129827526221, 71.93374422187982 },
            { 133823.0, -0.0001964868157346642, 66.294455142059974 },
            { 166210.0, -0.00015438293142310187, 60.659987031833758 },
            { 207694.0, -0.00012052839649021309, 55.033024780638321 },
            { 261191.0, -9.3463184851487005e-05, 49.411742714544744 },
            { 330666.0, -7.1968333933069455e-05, 43.797481108312347 },
            { 421562.0, -5.5007921140644254e-05, 38.189249251892271 },
            { 541408.0, -4.1720207599753015e-05, 32.587654156167083 },
            { 700715.0, -3.1385940354158953e-05, 26.992599195264489 },
            { 914294.0, -2.3410541298535906e-05, 21.404117446003589 },
            { 1203220.0, -1.7305469220492445e-05, 15.822286675480919 },
            { 1597763.0, -1.2672889900467123e-05, 10.248274586040052 },
            { 2142047.0, -9.1863806395190749e-06, 4.6776590897399153 },
            { 2900712.0, -6.5905241443852028e-06, -0.88278752809210947 },
            { 3970093.0, -4.6756020538984702e-06, -6.4374250150320611 },
            { 10921079.0, -2.1579672293973833e-06, -16.432669408340054 },
            { 9999999999999.0, -2.1579672293973833e-06, -16.432669408340054 },
        };
        private readonly AT32ADC adc;
        private readonly int channel;
        private readonly LimitTimer timer;
        private readonly ulong interval;
        private readonly double power, capacity, conductance, ambient, nominalResistance, beta, nominalKelvin, pullResistance, fanConductance, maximum;
        private readonly uint adcMax;
        private readonly bool toGround, stopAtMaximum, heaterActiveHigh, fanActiveHigh, recoveredNozzleCurve;
        private double heaterDuty, fanDuty, heaterIntegral, fanIntegral;
        private ulong lastOffset;
        private bool directHeater, directFan, curveWasOutOfRange;
        private string fault;
    }
}
