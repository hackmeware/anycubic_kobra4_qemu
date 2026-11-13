// SPDX-License-Identifier: MIT
// CPU-free actual C# peripheral tests. Synthetic GPIO writes, not native firmware proof.
using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.AT32;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
    public class NativeNozzleHeaterBindingTests : IDoubleWordPeripheral, IKnownSize
    {
        public NativeNozzleHeaterBindingTests(IMachine machine, AT32ADC adc, AT32GPIO portB,
            VirtualPrinterThermal thermal, NativeNozzleHeaterBinding binding, PassiveNozzleThermalObserver observer)
        {
            this.machine=machine; this.adc=adc; this.portB=portB; this.thermal=thermal; this.binding=binding; this.observer=observer;
            pwm=new LimitTimer(machine.ClockSource,1000000,this,"test GPIO pulse source",2500,
                direction:Direction.Ascending,workMode:WorkMode.Periodic,enabled:false,eventEnabled:true);
            pwm.LimitReached+=()=>{ phase=(phase+1)%4; if(phase==0) High(portB); else if(phase==1) Low(portB); };
        }
        public long Size { get { return 4; } }
        public void Reset() { }
        public uint ReadDoubleWord(long offset) { return 0; }
        public void WriteDoubleWord(long offset,uint value) { }
        private void Check(bool condition,string label) { if(!condition) throw new Exception(label); checks++; }
        private void Near(double actual,double expected,double tolerance,string label)
        { Check(Math.Abs(actual-expected)<=tolerance,label+": "+actual+" != "+expected); }
        private static void High(AT32GPIO p) { p.WriteDoubleWord(0x10,1u<<8); }
        private static void Low(AT32GPIO p) { p.WriteDoubleWord(0x10,1u<<24); }
        private void SensorMatches()
        {
            Check(thermal.ADCValue==thermal.ConvertTemperature(thermal.TemperatureCelsius),"ADC follows physical heat through recovered curve");
            adc.WriteDoubleWord(0x34,0); adc.WriteDoubleWord(8,0x5E0001);
            Check(adc.ReadDoubleWord(0x4C)==thermal.ADCValue,"published reading reaches ADC0");
        }
        public string Prepare()
        {
            Check(!binding.InitialPB8Level && !binding.PB8Level && binding.ForwardedEdges==0,"initial low resolved without inventing an edge");
            Check(portB.ReadDoubleWord(4)==0x44444444 && portB.ReadDoubleWord(12)==0,"binding did not configure or drive GPIO");
            Check(thermal.TemperatureCelsius==25 && thermal.ADCValue==4023,"binding itself creates no heat");
            latePort=new AT32GPIO(machine);latePort.WriteDoubleWord(4,0x44444411);High(latePort);
            lateThermal=new VirtualPrinterThermal(machine,adc,1,useRecoveredNozzleCurve:true);
            lateBinding=new NativeNozzleHeaterBinding(latePort,lateThermal);
            Check(lateBinding.InitialPB8Level && lateBinding.PB8Level && lateBinding.ForwardedEdges==0,"late attachment reads already-high pad without fabricated transition");
            latchedInputPort=new AT32GPIO(machine);High(latchedInputPort);
            latchedInputThermal=new VirtualPrinterThermal(machine,adc,3,useRecoveredNozzleCurve:true);
            latchedInputBinding=new NativeNozzleHeaterBinding(latchedInputPort,latchedInputThermal);
            Check((latchedInputPort.ReadDoubleWord(12)&(1u<<8))!=0 && !latchedInputBinding.InitialPB8Level,"input-mode high latch is not a resolved high pad");
            // Shortened synthetic ceiling exercises the unchanged latch quickly.
            limitedPort=new AT32GPIO(machine);limitedPort.WriteDoubleWord(4,0x44444411);
            limited=new VirtualPrinterThermal(machine,adc,2,maximumCelsius:25.05,useRecoveredNozzleCurve:true);
            limitedBinding=new NativeNozzleHeaterBinding(limitedPort,limited);High(limitedPort);
            portB.WriteDoubleWord(4,0x44444411);portB.WriteDoubleWord(0x10,1u<<9);
            Check(binding.ForwardedEdges==0 && observer.EdgeCount==1,"PB9 observed but not forwarded to heater");
            phase=0;High(portB);pwm.Enabled=true;
            return "NATIVE NOZZLE GPIO BINDING PREPARED";
        }
        public string EndPWM()
        {
            pwm.Enabled=false;Low(portB);Low(latePort);
            Near(thermal.LastHeaterDuty,0.25,1e-9,"actual GPIO edges integrated as quarter-duty PWM");
            Near(thermal.TemperatureCelsius,25+50*(1-Math.Exp(-0.01)),1e-8,"40W/20J-K/0.2W-K physical response from one second PWM");
            Check(thermal.ADCValue<4023,"heating changes ADC without temperature injection");SensorMatches();
            Near(thermal.LastFanDuty,0,0,"PB9 high cannot activate unmodeled fan coupling");
            Check(binding.ForwardedEdges>=200 && observer.EdgeCount==binding.ForwardedEdges+1,"observer and actuator both receive actual PB8 edges");
            Check(lateThermal.TemperatureCelsius>26.9 && lateBinding.ForwardedEdges==1,"initial resolved high creates full GPIO-driven heat before its first falling edge");
            Check(latchedInputThermal.TemperatureCelsius==25 && latchedInputThermal.LastHeaterDuty==0,"unresolved high latch cannot invent physical heat");
            Check(limited.Overtemperature && limited.HeaterLatchedOff,"GPIO heating trips existing maximum latch");
            Check(limited.LastHeaterDuty==0 && limited.TemperatureCelsius<=25.05,"latch inhibits sustained GPIO high");
            warm=thermal.TemperatureCelsius;limitedWarm=limited.TemperatureCelsius;
            limited.SetSensorFault("open");limited.Reset();limitedBinding.Reset();
            Check(limited.TemperatureCelsius==limitedWarm && limited.Overtemperature && limited.HeaterLatchedOff && limited.SensorFault=="open" && limited.ADCValue==4095,"reset retains heat/latch/open fault");
            Low(limitedPort);High(limitedPort);
            return "NATIVE NOZZLE GPIO PWM/INITIAL-HIGH/LATCH PASS";
        }
        public string CheckCoolingAndBeginFault()
        {
            Near(thermal.LastHeaterDuty,0,0,"low GPIO clears heat input");
            Near(thermal.TemperatureCelsius,25+(warm-25)*Math.Exp(-0.1),1e-8,"ten seconds of ordinary passive cooling");
            Check(thermal.TemperatureCelsius<warm && thermal.TemperatureCelsius>25,"cooling retains physical thermal state");SensorMatches();
            Check(thermal.LastFanDuty==0,"PB9 still high but fan cooling remains unbound");
            Check(limited.HeaterLatchedOff && limited.Overtemperature && limited.LastHeaterDuty==0 && limited.TemperatureCelsius<limitedWarm,"renewed actual GPIO edges cannot clear latch");
            Check(limited.SensorFault=="open" && limited.ADCValue==4095,"open fault remains visible across latch and cooling");
            faultWarm=thermal.TemperatureCelsius;thermal.SetSensorFault("open");
            Check(thermal.TemperatureCelsius==faultWarm && thermal.ADCValue==4095,"open sensor changes reading, not physical temperature");
            High(portB);
            return "NATIVE NOZZLE GPIO COOLING PASS";
        }
        public string CheckFaultAndReset()
        {
            Check(thermal.TemperatureCelsius>faultWarm && thermal.ADCValue==4095 && thermal.SensorFault=="open","physical GPIO heat and open fault are independent");
            thermal.SetSensorFault("short");Check(thermal.ADCValue==0,"short sensor rail preserved");
            resetWarm=thermal.TemperatureCelsius;thermal.Reset();binding.Reset();
            Check(thermal.TemperatureCelsius==resetWarm && thermal.SensorFault=="short" && thermal.ADCValue==0,"MCU-style reset retains heat and short fault");
            Check(thermal.LastHeaterDuty==0 && thermal.AutomaticUpdates,"reset clears duty, keeps normal physical timer");
            Check((portB.ReadDoubleWord(8)&(1u<<8))!=0,"binding reset does not drive the source pin");
            return "NATIVE NOZZLE GPIO SENSOR/RESET PASS";
        }
        public string Finish()
        {
            Check(thermal.TemperatureCelsius<resetWarm && thermal.LastHeaterDuty==0,"binding reset does not resurrect a pre-reset high level");
            Check(thermal.SensorFault=="short" && thermal.ADCValue==0,"short remains visible after reset timer update");
            Low(portB);thermal.SetSensorFault("none");SensorMatches();
            Check(thermal.TemperatureCelsius>25 && !thermal.HeaterLatchedOff && !thermal.Overtemperature,"repair exposes retained warm temperature without invented reset cooling");
            Check(thermal.LastFanDuty==0,"fan is still unbound at completion");
            Check(limited.HeaterLatchedOff && limited.Overtemperature,"all repeated GPIO activity leaves maximum latch intact");
            Check(observer.DroppedRows==0,"observer retained real GPIO evidence alongside binding");
            return "NATIVE NOZZLE HEATER BINDING TESTS PASS: "+checks;
        }
        private readonly IMachine machine;
        private readonly AT32ADC adc;
        private readonly AT32GPIO portB;
        private readonly VirtualPrinterThermal thermal;
        private readonly NativeNozzleHeaterBinding binding;
        private readonly PassiveNozzleThermalObserver observer;
        private readonly LimitTimer pwm;
        private AT32GPIO latePort,limitedPort,latchedInputPort;
        private VirtualPrinterThermal lateThermal,limited,latchedInputThermal;
        private NativeNozzleHeaterBinding lateBinding,limitedBinding,latchedInputBinding;
        private int phase,checks;
        private double warm,faultWarm,resetWarm,limitedWarm;
    }
}
