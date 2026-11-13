// SPDX-License-Identifier: MIT
// CPU-free tests only. Synthetic GPIO register edges, never temperature/duty injection.
using System;
using System.IO;
using System.Globalization;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
using N = Antmicro.Renode.Peripherals.PrinterNozzle;
using M = Antmicro.Renode.Peripherals.PrinterMain;
namespace Antmicro.Renode.Peripherals.ThermalExperimental
{
    public class AcceleratedFunctionalThermalTests : IPeripheral
    {
        public AcceleratedFunctionalThermalTests(IMachine machine, N.AT32GPIO nozzlePort, M.AT32GPIO bedPort,
            N.AT32ADC nozzleAdc, M.AT32ADC bedAdc, N.VirtualPrinterThermal nozzle,
            M.VirtualPrinterThermal bed, N.NativeNozzleHeaterBinding nozzleBinding,
            ResolvedBedHeaterBinding bedBinding, int accelerationFactor = 4)
        {
            if(accelerationFactor != 1 && accelerationFactor != 2 && accelerationFactor != 4 && accelerationFactor != 10)
                throw new ArgumentOutOfRangeException("accelerationFactor");
            factor=accelerationFactor; nCapacity=20.0/factor; bCapacity=600.0/factor;
            this.machine=machine; np=nozzlePort; bp=bedPort; na=nozzleAdc; ba=bedAdc;
            n=nozzle; b=bed; nb=nozzleBinding; bb=bedBinding;
            quietN=new N.VirtualPrinterThermal(machine,new N.AT32ADC(),0,heaterPowerWatts:60,heatCapacityJoulesPerKelvin:nCapacity,useRecoveredNozzleCurve:true);
            quietB=new M.VirtualPrinterThermal(machine,new M.AT32ADC(),8,heaterPowerWatts:200,heatCapacityJoulesPerKelvin:bCapacity,conductanceWattsPerKelvin:1.5,maximumCelsius:150);
            quietNB=new N.NativeNozzleHeaterBinding(np,quietN); quietBB=new ResolvedBedHeaterBinding(bp,quietB);
            clock=new LimitTimer(machine.ClockSource,1000000,this,"thermal test timestamp",ulong.MaxValue,
                direction:Direction.Ascending,enabled:true,eventEnabled:false);
            pwm=new LimitTimer(machine.ClockSource,1000000,this,"offline GPIO PWM",2500,
                direction:Direction.Ascending,workMode:WorkMode.Periodic,enabled:false,eventEnabled:true);
            pwm.LimitReached+=()=>{phase=(phase+1)%4;if(phase==0)Set(true);else if(phase==1)Set(false);};
            sampler=new LimitTimer(machine.ClockSource,1000000,this,"passive test observation",10000,
                direction:Direction.Ascending,workMode:WorkMode.Periodic,enabled:true,eventEnabled:true);
            sampler.LimitReached+=Observe;
        }
        public void Reset() { }
        private string Passed(string label) { ObservationalInvariant(); passed.Add(label); return label; }
        private void Check(bool value,string label){if(!value)throw new Exception(label);checks++;}
        private void Near(double value,double expected,double tolerance,string label)
        {Check(Math.Abs(value-expected)<=tolerance,label+": "+F(value)+" expected "+F(expected));}
        private static string F(double x){return x.ToString("R",CultureInfo.InvariantCulture);}
        private double Time {get{return clock.Value/1000000.0;}}
        private static double E(double initial,double power,double capacity,double loss,double dt,double duty=1)
        {var eq=25+power*duty/loss;return eq+(initial-eq)*Math.Exp(-loss*dt/capacity);}
        private void Set(bool high)
        {np.WriteDoubleWord(16,1u<<(high?8:24));bp.WriteDoubleWord(16,1u<<(high?0:16));}
        private void SensorMatches()
        {
            Check(n.ADCValue==n.ConvertTemperature(n.TemperatureCelsius),"nozzle sensor follows actual heat");
            Check(b.ADCValue==b.ConvertTemperature(b.TemperatureCelsius),"bed sensor follows actual heat");
            na.WriteDoubleWord(0x34,0);na.WriteDoubleWord(8,0x5e0001);
            ba.WriteDoubleWord(0x34,8);ba.WriteDoubleWord(8,0x5e0001);
            Check(na.ReadDoubleWord(0x4c)==n.ADCValue,"nozzle actual ADC0 delivery");
            Check(ba.ReadDoubleWord(0x4c)==b.ADCValue,"bed actual ADC8 delivery");
        }
        public string Prepare()
        {
            Check(!nb.InitialPB8Level&&!bb.InitialLevel,"fresh resolved pads are low");
            Check(np.ReadDoubleWord(4)==0x44444444&&bp.ReadDoubleWord(0)==0x44444444,"profiles do not configure GPIO");
            Check(np.ReadDoubleWord(12)==0&&bp.ReadDoubleWord(12)==0,"profiles do not write GPIO latches");
            Check(n.TemperatureCelsius==25&&b.TemperatureCelsius==25,"no attachment heat");
            Check(n.ADCValue==4023&&b.ADCValue==3911,"unchanged initial sensor conversions");
            Check(n.SensorCurve=="NTC ZM3863 HNS112HC4570G0"&&!n.SensorCurveOutOfRange,"full recovered nozzle curve selected");
            Check(n.ConvertTemperature(230)==468&&b.ConvertTemperature(60)==3444,"target ADC codes independently verified");
            Check(n.AutomaticUpdates&&b.AutomaticUpdates,"normal automatic integration only");
            bool rejected=false;try{n.Advance(1);}catch(InvalidOperationException){rejected=true;}
            Check(rejected,"nozzle refuses double advance");
            rejected=false;try{b.Advance(1);}catch(InvalidOperationException){rejected=true;}
            Check(rejected,"bed refuses double advance");
            latePort=new M.AT32GPIO(machine);latePort.WriteDoubleWord(0,0x44444441);latePort.WriteDoubleWord(16,1);
            var extraAdc=new M.AT32ADC();
            lateBed=new M.VirtualPrinterThermal(machine,extraAdc,0,heaterPowerWatts:200,heatCapacityJoulesPerKelvin:bCapacity,conductanceWattsPerKelvin:1.5,maximumCelsius:150);
            lateBinding=new ResolvedBedHeaterBinding(latePort,lateBed);
            Check(lateBinding.InitialLevel&&lateBinding.ForwardedEdges==0,"bed already-high resolved pad initializes without fabricated edge");
            var inputPort=new M.AT32GPIO(machine);inputPort.WriteDoubleWord(16,1);
            inputBed=new M.VirtualPrinterThermal(machine,extraAdc,1,heaterPowerWatts:200,heatCapacityJoulesPerKelvin:bCapacity,conductanceWattsPerKelvin:1.5,maximumCelsius:150);
            var inputBinding=new ResolvedBedHeaterBinding(inputPort,inputBed);
            Check(!inputBinding.InitialLevel,"high latch in input mode does not manufacture a resolved high");
            rejected=false;try{inputBinding.OnGPIO(1,true);}catch(ArgumentOutOfRangeException){rejected=true;}
            Check(rejected,"bed binding rejects non-PA0 input numbers");
            var stoppedBed=new M.VirtualPrinterThermal(machine,extraAdc,2);stoppedBed.SetAutomaticUpdates(false);
            rejected=false;try{new ResolvedBedHeaterBinding(new M.AT32GPIO(machine),stoppedBed);}catch(ArgumentException){rejected=true;}
            Check(rejected,"bed binding rejects a disabled physical timer");
            lateNozzlePort=new N.AT32GPIO(machine);lateNozzlePort.WriteDoubleWord(4,0x44444441);lateNozzlePort.WriteDoubleWord(16,1u<<8);
            lateNozzle=new N.VirtualPrinterThermal(machine,new N.AT32ADC(),0,heaterPowerWatts:60,heatCapacityJoulesPerKelvin:nCapacity,useRecoveredNozzleCurve:true);
            lateNozzleBinding=new N.NativeNozzleHeaterBinding(lateNozzlePort,lateNozzle);
            Check(lateNozzleBinding.InitialPB8Level&&lateNozzleBinding.ForwardedEdges==0,"already-high nozzle initializes without fabricated edge");
            var inputNozzlePort=new N.AT32GPIO(machine);inputNozzlePort.WriteDoubleWord(16,1u<<8);
            inputNozzle=new N.VirtualPrinterThermal(machine,new N.AT32ADC(),0,heaterPowerWatts:60,heatCapacityJoulesPerKelvin:nCapacity,useRecoveredNozzleCurve:true);
            var inputNozzleBinding=new N.NativeNozzleHeaterBinding(inputNozzlePort,inputNozzle);
            Check(!inputNozzleBinding.InitialPB8Level,"input-mode PB8 high latch is not a resolved high");
            np.WriteDoubleWord(4,0x44444411);bp.WriteDoubleWord(0,0x44444441);
            np.WriteDoubleWord(16,1u<<9); // PB9 visible high, deliberately not thermally connected.
            phase=0;Set(true);pwm.Enabled=true;Observe();
            return Passed("ACCELERATED FUNCTIONAL THERMAL PREPARED");
        }
        public string EndPwmBeginFull()
        {
            pwm.Enabled=false;Set(false);latePort.WriteDoubleWord(16,1u<<16);lateNozzlePort.WriteDoubleWord(16,1u<<24);
            Near(lateNozzle.TemperatureCelsius,E(25,60,nCapacity,.2,1),1e-8,"already-high nozzle heats from actual resolved level");
            Check(inputNozzle.TemperatureCelsius==25,"input-mode nozzle remains physically cold");
            Near(n.LastHeaterDuty,.25,1e-12,"nozzle actual quarter PWM");
            Near(b.LastHeaterDuty,.25,1e-12,"bed actual quarter PWM");
            Near(n.TemperatureCelsius,E(25,60,nCapacity,.2,1,.25),1e-8,"nozzle actual PWM analytic response");
            Near(b.TemperatureCelsius,E(25,200,bCapacity,1.5,1,.25),1e-8,"bed actual PWM analytic response");
            Check(nb.ForwardedEdges==202&&bb.ForwardedEdges==202,"both bindings receive 202 actual PWM transitions (including boundary rise and final low)");
            Near(lateBed.TemperatureCelsius,E(25,200,bCapacity,1.5,1),1e-8,"late bed attachment uses actual initial level");
            Check(lateBinding.ForwardedEdges==1&&inputBed.TemperatureCelsius==25,"bed initial level semantics");
            Check(n.LastFanDuty==0&&b.LastFanDuty==0,"PB9 high stays thermally unbound");SensorMatches();
            fullStart=Time;startN=n.TemperatureCelsius;startB=b.TemperatureCelsius;watchTargets=true;Set(true);
            return Passed("ACCELERATED FUNCTIONAL THERMAL GPIO PWM PASS");
        }
        public string CheckInitialHeatRate()
        {
            firstRateN=n.TemperatureCelsius-startN;firstRateB=b.TemperatureCelsius-startB;
            Near(n.TemperatureCelsius,E(startN,60,nCapacity,.2,1),1e-8,"full-power first-second nozzle rate");
            Near(b.TemperatureCelsius,E(startB,200,bCapacity,1.5,1),1e-8,"full-power first-second bed rate");
            Check(firstRateN>0&&firstRateN<3*factor&&firstRateB>0&&firstRateB<factor/3.0,"plausible chosen synthetic initial rates");
            return Passed("ACCELERATED FUNCTIONAL THERMAL INITIAL RATE PASS");
        }
        public string EndFullBeginCooling()
        {
            Near(Time-fullStart,150.0/factor,1e-8,"bounded offline full-power interval");
            Near(n.TemperatureCelsius,E(startN,60,nCapacity,.2,150.0/factor),1e-7,"nozzle full-power exponential response");
            Near(b.TemperatureCelsius,E(startB,200,bCapacity,1.5,150.0/factor),1e-7,"bed full-power exponential response");
            var expectedN=-100.0/factor*Math.Log((325-230)/(325-startN));
            var expectedB=-400.0/factor*Math.Log((25+200/1.5-60)/(25+200/1.5-startB));
            Check(crossN>0&&crossB>0,"actual GPIO-driven plants cross both requested target temperatures");
            Near(crossN-fullStart,expectedN,.021,"nozzle threshold crossing measured from actual physical state");
            Near(crossB-fullStart,expectedB,.021,"bed threshold crossing measured from actual physical state");
            Check(!n.Overtemperature&&!b.Overtemperature&&!n.HeaterLatchedOff&&!b.HeaterLatchedOff,"target crossing does not change guards");
            Check(n.LastFanDuty==0&&b.LastFanDuty==0,"unbound fan remains zero at high temperature");SensorMatches();
            warmN=n.TemperatureCelsius;warmB=b.TemperatureCelsius;Set(false);watchTargets=false;
            return Passed("ACCELERATED FUNCTIONAL THERMAL TARGET CROSSING PASS");
        }
        public string CheckCoolingBeginOpen()
        {
            Near(n.TemperatureCelsius,E(warmN,60,nCapacity,.2,20.0/factor,0),1e-7,"nozzle passive cooling after actual low");
            Near(b.TemperatureCelsius,E(warmB,200,bCapacity,1.5,20.0/factor,0),1e-7,"bed passive cooling after actual low");
            Check(n.LastHeaterDuty==0&&b.LastHeaterDuty==0,"both low pads stop input power");SensorMatches();
            faultN=n.TemperatureCelsius;faultB=b.TemperatureCelsius;
            n.SetSensorFault("open");b.SetSensorFault("open");quietN.SetSensorFault("open");quietB.SetSensorFault("open");
            Check(n.ADCValue==4095&&b.ADCValue==4095,"open rails preserved");
            Check(n.TemperatureCelsius==faultN&&b.TemperatureCelsius==faultB,"fault changes sensing only");Set(true);
            return Passed("ACCELERATED FUNCTIONAL THERMAL COOLING PASS");
        }
        public string CheckOpenResetShort()
        {
            Check(n.TemperatureCelsius>faultN&&b.TemperatureCelsius>faultB,"GPIO heat continues independently of open sensing");
            Check(n.ADCValue==4095&&b.ADCValue==4095,"heat does not hide open rails");
            n.SetSensorFault("short");b.SetSensorFault("short");quietN.SetSensorFault("short");quietB.SetSensorFault("short");
            Check(n.ADCValue==0&&b.ADCValue==0,"short rails preserved");
            resetN=n.TemperatureCelsius;resetB=b.TemperatureCelsius;n.Reset();b.Reset();nb.Reset();bb.Reset();quietN.Reset();quietB.Reset();quietNB.Reset();quietBB.Reset();
            Check(n.TemperatureCelsius==resetN&&b.TemperatureCelsius==resetB,"MCU-style reset retains physical heat");
            Check(n.SensorFault=="short"&&b.SensorFault=="short"&&n.ADCValue==0&&b.ADCValue==0,"reset retains faults");
            Check(n.LastHeaterDuty==0&&b.LastHeaterDuty==0&&n.AutomaticUpdates&&b.AutomaticUpdates,"reset clears command duty without disabling physics");
            Check((np.ReadDoubleWord(8)&256)!=0&&(bp.ReadDoubleWord(8)&1)!=0,"binding reset never drives source pads");
            return Passed("ACCELERATED FUNCTIONAL THERMAL FAULT RESET PASS");
        }
        public string CheckResetAndBeginRecovery()
        {
            Check(n.TemperatureCelsius<resetN&&b.TemperatureCelsius<resetB,"reset does not reassert stale high");
            Check(n.LastHeaterDuty==0&&b.LastHeaterDuty==0,"stale high remains inactive until real edges");
            Set(false);n.SetSensorFault("none");b.SetSensorFault("none");quietN.SetSensorFault("none");quietB.SetSensorFault("none");SensorMatches();
            recoveryN=n.TemperatureCelsius;recoveryB=b.TemperatureCelsius;
            // Explicit GPIO-first reset ordering, not a claim about every machine-reset order.
            np.Reset();bp.Reset();n.Reset();b.Reset();nb.Reset();bb.Reset();quietN.Reset();quietB.Reset();quietNB.Reset();quietBB.Reset();
            Check(n.TemperatureCelsius==recoveryN&&b.TemperatureCelsius==recoveryB,"GPIO-first reset sequence retains heat");
            Check(np.ReadDoubleWord(12)==0&&bp.ReadDoubleWord(12)==0,"actual GPIO reset clears output latches");
            Check(n.LastHeaterDuty==0&&b.LastHeaterDuty==0,"GPIO-first reset sequence leaves heater commands off");
            np.WriteDoubleWord(4,0x44444411);bp.WriteDoubleWord(0,0x44444441);np.WriteDoubleWord(16,1u<<9);Set(true);
            return Passed("ACCELERATED FUNCTIONAL THERMAL RESET RECOVERY PREPARED");
        }
        public string CheckRecoveryAndBeginLong()
        {
            Near(n.TemperatureCelsius,E(recoveryN,60,nCapacity,.2,1),1e-7,"fresh actual PB8 edge resumes unlatched heating after reset");
            Near(b.TemperatureCelsius,E(recoveryB,200,bCapacity,1.5,1),1e-7,"fresh actual PA0 edge resumes unlatched heating after reset");
            Check(n.LastHeaterDuty==1&&b.LastHeaterDuty==1,"new actual edges, not stale state, restore demand");SensorMatches();Set(false);
            var adc=new N.AT32ADC();longPort=new N.AT32GPIO(machine);longPort.WriteDoubleWord(4,0x44444441);
            equilibrium=new N.VirtualPrinterThermal(machine,adc,0,heaterPowerWatts:60,heatCapacityJoulesPerKelvin:nCapacity,useRecoveredNozzleCurve:true);
            originalDefault=new N.VirtualPrinterThermal(machine,adc,1,useRecoveredNozzleCurve:true);
            // Separate negative-only no-loss plant; same scaled capacity and original 400C guard.
            noLoss=new N.VirtualPrinterThermal(machine,adc,2,heaterPowerWatts:60,heatCapacityJoulesPerKelvin:nCapacity,conductanceWattsPerKelvin:0,useRecoveredNozzleCurve:true);
            eqBinding=new N.NativeNozzleHeaterBinding(longPort,equilibrium);
            defaultBinding=new N.NativeNozzleHeaterBinding(longPort,originalDefault);
            noLossBinding=new N.NativeNozzleHeaterBinding(longPort,noLoss);
            longBedPort=new M.AT32GPIO(machine);longBedPort.WriteDoubleWord(0,0x44444441);
            longBed=new M.VirtualPrinterThermal(machine,new M.AT32ADC(),8,heaterPowerWatts:200,heatCapacityJoulesPerKelvin:bCapacity,conductanceWattsPerKelvin:1.5,maximumCelsius:150);
            longBedBinding=new ResolvedBedHeaterBinding(longBedPort,longBed);
            longStart=Time;longPort.WriteDoubleWord(16,1u<<8);longBedPort.WriteDoubleWord(16,1);
            return Passed("ACCELERATED FUNCTIONAL THERMAL RESET RECOVERY PASS");
        }
        public string CheckOutOfTable()
        {
            Near(noLoss.TemperatureCelsius,370,1e-6,"separate loss-of-cooling fault has real physical heat");
            Check(noLoss.SensorCurveOutOfRange&&noLoss.ADCValue==0&&noLoss.SensorFault=="none","out-of-table heat is visible invalid rail, not hidden plausible reading");
            Check(!noLoss.HeaterLatchedOff&&!noLoss.Overtemperature,"400C model limit not lowered to sensor range");
            return Passed("ACCELERATED FUNCTIONAL THERMAL OUT OF TABLE PASS");
        }
        public string Finish()
        {
            var elapsed=Time-longStart;
            Near(equilibrium.TemperatureCelsius,E(25,60,nCapacity,.2,elapsed),1e-6,"actual GPIO full-power equilibrium trajectory");
            Near(equilibrium.TemperatureCelsius,325,.002,"new hypothetical equilibrium reached asymptotically");
            Near(originalDefault.TemperatureCelsius,E(25,40,20,.2,elapsed),1e-6,"unchanged default physical trajectory");
            Check(originalDefault.TemperatureCelsius<225&&originalDefault.TemperatureCelsius>25,"default still cannot reach 230");
            Check(noLoss.TemperatureCelsius==400&&noLoss.Overtemperature&&noLoss.HeaterLatchedOff&&noLoss.LastHeaterDuty==0,"unchanged 400C latch catches loss-of-cooling negative");
            Check(longBed.Overtemperature&&longBed.HeaterLatchedOff&&longBed.LastHeaterDuty==0&&longBed.TemperatureCelsius<150,"unchanged 150C bed latch catches sustained-high negative then cools");
            var retained=noLoss.TemperatureCelsius;noLoss.SetSensorFault("open");noLoss.Reset();noLossBinding.Reset();
            Check(noLoss.TemperatureCelsius==retained&&noLoss.HeaterLatchedOff&&noLoss.Overtemperature&&noLoss.ADCValue==4095,"reset preserves hot latch and open fault");
            noLoss.SetSensorFault("short");noLoss.Reset();
            Check(noLoss.HeaterLatchedOff&&noLoss.SensorFault=="short"&&noLoss.ADCValue==0,"short/reset cannot clear thermal latch");
            longPort.WriteDoubleWord(16,1u<<24);longPort.WriteDoubleWord(16,1u<<8);
            Check(noLoss.HeaterLatchedOff,"renewed GPIO activity cannot clear latch");
            var bedRetained=longBed.TemperatureCelsius;longBed.SetSensorFault("open");longBed.Reset();longBedBinding.Reset();
            Check(longBed.TemperatureCelsius==bedRetained&&longBed.HeaterLatchedOff&&longBed.Overtemperature&&longBed.ADCValue==4095,"bed reset retains heat latch and fault");
            longBed.SetSensorFault("short");longBed.Reset();
            longBedPort.WriteDoubleWord(16,1u<<16);longBedPort.WriteDoubleWord(16,1);
            Check(n.LastFanDuty==0&&b.LastFanDuty==0,"PB9 has remained physically unbound");
            Check(n.TemperatureCelsius>25&&b.TemperatureCelsius>25,"long cooling never manufactured a cold reset");
            Check(dropped==0,"bounded observations not dropped");Observe();
            return Passed("ACCELERATED FUNCTIONAL THERMAL LONG NEGATIVES PASS");
        }
        public string CheckPostLatchEdges()
        {
            Check(noLoss.HeaterLatchedOff&&noLoss.Overtemperature&&noLoss.LastHeaterDuty==0,"new actual PB8 edges and a full timer interval cannot reopen the latched heater");
            Check(noLoss.TemperatureCelsius==400&&noLoss.SensorCurveOutOfRange&&noLoss.SensorFault=="short"&&noLoss.ADCValue==0,"hot out-of-range state and short remain visible after latch/reset");
            Check(longBed.HeaterLatchedOff&&longBed.Overtemperature&&longBed.LastHeaterDuty==0,"new actual PA0 edges cannot reopen the latched bed heater");
            Check(longBed.SensorFault=="short"&&longBed.ADCValue==0,"bed short fault survives reset and renewed edges");
            ObservationalInvariant(); return Passed("ACCELERATED FUNCTIONAL THERMAL TESTS PASS: "+checks);
        }
        private void ObservationalInvariant()
        {
            Near(n.TemperatureCelsius,quietN.TemperatureCelsius,1e-10,"passive reads do not alter nozzle thermal trajectory");
            Near(b.TemperatureCelsius,quietB.TemperatureCelsius,1e-10,"passive reads do not alter bed thermal trajectory");
            Check(n.ADCValue==quietN.ADCValue&&b.ADCValue==quietB.ADCValue,"observations do not alter ADC conversion");
            Check(n.LastHeaterDuty==quietN.LastHeaterDuty&&b.LastHeaterDuty==quietB.LastHeaterDuty,"observations do not alter integrated GPIO duty");
            Check(n.HeaterLatchedOff==quietN.HeaterLatchedOff&&b.HeaterLatchedOff==quietB.HeaterLatchedOff,"observations do not alter latch state");
        }
        private void Observe()
        {
            if(watchTargets){if(crossN==0&&n.TemperatureCelsius>=230)crossN=Time;if(crossB==0&&b.TemperatureCelsius>=60)crossB=Time;}
            if(Time-lastRow<.099999&&rows.Count!=0)return;lastRow=Time;
            if(rows.Count>=20000){dropped++;return;}
            rows.Add(String.Join(",",new[]{F(Time),F(n.TemperatureCelsius),n.ADCValue.ToString(),F(n.LastHeaterDuty),F(n.LastFanDuty),n.SensorFault,n.HeaterLatchedOff.ToString(),F(b.TemperatureCelsius),b.ADCValue.ToString(),F(b.LastHeaterDuty),b.SensorFault,b.HeaterLatchedOff.ToString()}));
        }
        public void WriteResults(string path)
        {
            File.WriteAllText(path+".csv","virtual_seconds,nozzle_c,nozzle_adc,nozzle_duty,nozzle_fan_duty,nozzle_fault,nozzle_latch,bed_c,bed_adc,bed_duty,bed_fault,bed_latch\n"+String.Join("\n",rows)+"\n");
            File.WriteAllText(path+".json","{\n\"completed_stages\":[\""+String.Join("\",\"",passed)+"\"],\n\"assertions\":"+checks+",\n\"native_firmware_run\":false,\n\"direct_duty_used\":false,\n\"temperature_injection_used\":false,\n\"full_power_start_s\":"+F(fullStart)+",\n\"nozzle_target_crossing_s\":"+F(crossN)+",\n\"bed_target_crossing_s\":"+F(crossB)+",\n\"nozzle_first_full_second_delta_c\":"+F(firstRateN)+",\n\"bed_first_full_second_delta_c\":"+F(firstRateB)+",\n\"new_nozzle_equilibrium_final_c\":"+F(equilibrium.TemperatureCelsius)+",\n\"unchanged_default_final_c\":"+F(originalDefault.TemperatureCelsius)+",\n\"dropped_rows\":"+dropped+"\n}\n");
        }
        private readonly int factor; private readonly double nCapacity,bCapacity;
        private readonly N.VirtualPrinterThermal quietN; private readonly M.VirtualPrinterThermal quietB;
        private readonly N.NativeNozzleHeaterBinding quietNB; private readonly ResolvedBedHeaterBinding quietBB;
        private readonly IMachine machine;private readonly N.AT32GPIO np;private readonly M.AT32GPIO bp;
        private readonly N.AT32ADC na;private readonly M.AT32ADC ba;private readonly N.VirtualPrinterThermal n;private readonly M.VirtualPrinterThermal b;
        private readonly N.NativeNozzleHeaterBinding nb;private readonly ResolvedBedHeaterBinding bb;private readonly LimitTimer clock,pwm,sampler;
        private N.AT32GPIO lateNozzlePort; private N.VirtualPrinterThermal lateNozzle,inputNozzle; private N.NativeNozzleHeaterBinding lateNozzleBinding;
        private M.AT32GPIO latePort,longBedPort;private N.AT32GPIO longPort;
        private M.VirtualPrinterThermal lateBed,inputBed,longBed;private N.VirtualPrinterThermal equilibrium,originalDefault,noLoss;
        private ResolvedBedHeaterBinding lateBinding,longBedBinding;private N.NativeNozzleHeaterBinding eqBinding,defaultBinding,noLossBinding;
        private int phase,checks,dropped;private bool watchTargets;private double fullStart,startN,startB,crossN,crossB,firstRateN,firstRateB,warmN,warmB,faultN,faultB,resetN,resetB,recoveryN,recoveryB,longStart,lastRow;
        private readonly List<string> rows=new List<string>();
        private readonly List<string> passed=new List<string>();
    }
}
