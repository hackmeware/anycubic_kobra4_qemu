// SPDX-License-Identifier: MIT
// No CPU, firmware, GPIO port, clock source or native requests. Synthetic laboratory inputs only.
using System;
using Antmicro.Renode.Peripherals.Bus;
namespace Antmicro.Renode.Peripherals.NozzleExperimental
{
    public class Cs1237ProtocolTests : IDoubleWordPeripheral, IKnownSize
    {
        public long Size { get { return 4; } }
        public void Reset() { }
        public uint ReadDoubleWord(long offset) { return 0; }
        public void WriteDoubleWord(long offset,uint value) { }
        private void Check(bool condition,string description)
        { checks++;if(!condition)throw new Exception(description); }
        private Cs1237Protocol Fresh(int code)
        {
            var d=new Cs1237Protocol(500);d.SetSyntheticCode(code);
            Check(d.Config==0x0c && d.Gain==128 && d.Channel==0 && d.ReferenceOutputEnabled,"documented POR configuration");
            Check(d.NextReadyNanoseconds==302000000 && d.ConversionPeriodNanoseconds==100000000,"t1+t2 POR typical timing");
            d.AdvanceTo(301999999);Check(!d.Ready && d.DeviceDout==true,"no early POR ready");
            d.AdvanceTo(302000000);Check(d.Ready && d.DeviceDout==false && d.ConversionCount==1,"first real synthetic conversion ready");
            return d;
        }
        private bool? Pulse(Cs1237Protocol d)
        {
            var start=d.Now+1000;d.SetSclk(true,start);d.AdvanceTo(start+1000);
            d.SetSclk(false,start+1000);d.AdvanceTo(start+2000);return d.DeviceDout;
        }
        private uint Read24(Cs1237Protocol d)
        {
            uint v=0;for(var i=0;i<24;i++){var b=Pulse(d);Check(b.HasValue,"ADC output driven");v=(v<<1)|(b.Value?1u:0u);}
            Check(d.ReadWordCount>0 && !d.ProtocolFault,"whole signed word read without error");return v;
        }
        private void End27(Cs1237Protocol d,bool written)
        {
            Check(Pulse(d)==written,"clock25 config-written flag");Check(Pulse(d)==false,"clock26 reserved0");
            Check(Pulse(d)==true && d.ClockCount==27,"clock27 forces high");
        }
        private void Command(Cs1237Protocol d,byte cmd)
        {
            Pulse(d);Pulse(d);Check(d.ClockCount==29 && !d.DeviceDout.HasValue,"data line released by clock29");
            for(var bit=6;bit>=0;bit--){d.SetHostDout((cmd&(1<<bit))!=0,d.Now);Pulse(d);}
            d.SetHostDout(null,d.Now);
        }
        private void Write(Cs1237Protocol d,byte value)
        {
            Read24(d);End27(d,d.ConfigUpdated);Command(d,0x65);Pulse(d);
            for(var bit=7;bit>=0;bit--){d.SetHostDout((value&(1<<bit))!=0,d.Now);Pulse(d);}
            d.SetHostDout(null,d.Now);Pulse(d);
        }
        private byte ReadConfig(Cs1237Protocol d)
        {
            Read24(d);End27(d,d.ConfigUpdated);Command(d,0x56);Pulse(d);byte value=0;
            for(var bit=7;bit>=0;bit--){var b=Pulse(d);Check(b.HasValue,"register read bit driven");value=(byte)((value<<1)|(b.Value?1:0));}
            Pulse(d);return value;
        }
        private void Await(Cs1237Protocol d) { d.AdvanceTo(d.NextReadyNanoseconds);Check(d.Ready && !d.ProtocolFault,"next conversion ready"); }
        public string RunAll()
        {
            checks=0;
            var none=new Cs1237Protocol(500);none.AdvanceTo(302000000);
            Check(none.ProtocolFault && !none.Ready && !none.DeviceDout.HasValue,"missing source is visible model error, never implicit zero/readiness");
            foreach(var code in new int[]{-8388608,-8388607,-1200,-1,0,1,0x123456,8388607})
            {
                var d=Fresh(code);Check(Read24(d)==((uint)code&0xffffff),"signed24-bit MSB-first wire result "+code);
                End27(d,false);Check(!d.ProtocolFault,"normal27-clock frame");
            }
            Check(Cs1237Protocol.SaturateIdealCode(long.MaxValue)==8388607,"positive full-scale saturation");
            Check(Cs1237Protocol.SaturateIdealCode(long.MinValue)==-8388608,"negative full-scale saturation");
            Check(Cs1237Protocol.WireBits(-1)==0xffffff && Cs1237Protocol.WireBits(-8388608)==0x800000,"minus one is valid, not disconnected error");
            bool rejected=false;try{new Cs1237Protocol(454);}catch(ArgumentOutOfRangeException){rejected=true;}
            Check(rejected,"no chosen output delay below datasheet minimum");
            rejected=false;try{none.SetSyntheticCode(8388608);}catch(ArgumentOutOfRangeException){rejected=true;}
            Check(rejected,"out-of-range explicit code rejected instead of wrapped");

            var delayed=Fresh(-1);var t=delayed.Now+1000;delayed.SetSclk(true,t);
            delayed.AdvanceTo(t+227);Check(delayed.DeviceDout==false && !delayed.OutputTransition,"old output within documented hold interval");
            delayed.AdvanceTo(t+228);Check(delayed.OutputTransition && !delayed.ResolvedDout.HasValue,"unspecified transition interval is visibly unknown");
            delayed.AdvanceTo(t+499);Check(delayed.OutputTransition && !delayed.DeviceDout.HasValue,"old bit not falsely valid beyond guaranteed hold minimum");
            delayed.AdvanceTo(t+500);Check(delayed.DeviceDout==true,"new MSB appears after explicit500ns laboratory delay");
            delayed.SetSclk(false,t+1000);Check(delayed.DeviceDout==true,"falling edge does not shift a second bit");

            var fast=Fresh(1234);Write(fast,0x3c);
            Check(fast.Config==0x3c && fast.ConfigWrites==1 && fast.ConfigUpdated,"complete46-clock write commits0x3c");
            Check(fast.Gain==128 && fast.Channel==0 && fast.ReferenceOutputEnabled && fast.ConversionPeriodNanoseconds==781250,"recovered0x3c selects1280Hz PGA128 channelA REF on");
            // Commit occurs at46th falling edge; Pulse has advanced another1000ns.
            Check(fast.NextReadyNanoseconds==fast.Now-1000+3125800,"rate-change settle is0.8us plus4 periods");
            fast.AdvanceTo(fast.NextReadyNanoseconds-1);Check(!fast.Ready && fast.DeviceDout==true,"no premature rate-change ready");
            Await(fast);var expectedNext=fast.NextReadyNanoseconds;
            Check(ReadConfig(fast)==0x3c && fast.ConfigReads==1 && !fast.ConfigUpdated,"register readback and written-flag clear");
            Check(fast.NextReadyNanoseconds==expectedNext,"clock46 read does not restart continuous conversion clock");
            Await(fast);Read24(fast);expectedNext=fast.NextReadyNanoseconds;End27(fast,false);
            Check(fast.NextReadyNanoseconds==expectedNext,"clock27 does not restart conversion clock");
            Await(fast);Write(fast,0x3c);Check(fast.ConfigUpdated,"same-value register write is still a write");
            Await(fast);Read24(fast);End27(fast,true);Check(fast.ConfigUpdated,"reading update bit alone does not clear written flag");

            foreach(byte value in new byte[]{0x0c,0x1c,0x2c,0x3c})
            {
                var d=Fresh(0);Write(d,value);var period=new long[]{100000000,25000000,1562500,781250}[(value>>4)&3];
                Check(d.Config==value && d.ConversionPeriodNanoseconds==period,"all documented rates");
                if(value!=0x0c)Check(d.NextReadyNanoseconds==d.Now-1000+800+period*((value&0x20)==0?3:4),"three/four-period digital settling");
            }
            var channel=Fresh(9);Write(channel,0x0f);
            Check(channel.Channel==3 && channel.NextReadyNanoseconds==channel.Now-1000+302000000,"channel change uses2ms+three periods; synthetic source has no analog meaning");

            var continuous=Fresh(2);var due=continuous.NextReadyNanoseconds;
            continuous.AdvanceTo(due-26131);Check(continuous.DeviceDout==false && continuous.Ready,"unread word remains ready before update exclusion");
            continuous.AdvanceTo(due-26130);Check(continuous.DeviceDout==true && !continuous.Ready && continuous.OverwrittenUnreadWords==1,"typical26.13us update interval visibly invalidates previous word");
            continuous.SetSyntheticCode(-7);Await(continuous);
            Check(continuous.LastLatchedSignedCode==-7 && continuous.ConversionCount==2,"free-running conversion latches current explicit source");
            Check(Read24(continuous)==0xfffff9,"new conversion replaces unread old word");
            continuous.AdvanceTo(continuous.NextReadyNanoseconds-26131);Check(continuous.DeviceDout==true,"24-only read holds its LSB until update window");

            var power=Fresh(17);Write(power,0x3c);Await(power);var cfg=power.Config;t=power.Now+1000;
            power.SetSclk(true,t);power.AdvanceTo(t+100000);Check(!power.PoweredDown,"strict more-than100us threshold convention");
            power.AdvanceTo(t+100001);Check(power.PoweredDown && power.PowerDownCount==1 && !power.Ready,"held-high clock enters documented power-down");
            power.SetSclk(false,t+110000);Check(power.Config==cfg && !power.PoweredDown,"wake retains configuration");
            Check(power.NextReadyNanoseconds==power.Now+5125000,"wake2ms+4 periods also exceeds minimum10us low");
            power.AdvanceTo(power.Now+9999);Check(!power.Ready,"no early10us wake success");Await(power);
            Check(Read24(power)==17,"wake returns synthetic conversion, not retained readiness");
            power.PowerOnReset(power.Now+1000);Check(power.Config==0x0c && power.HasSyntheticSample && !power.Ready,"real power-on reset defaults register but not external sample source");

            var early=new Cs1237Protocol(500);early.SetSyntheticCode(1);Pulse(early);
            Check(early.ProtocolFault && early.Config==0x0c && early.ConfigWrites==0,"pre-ready config is not silently accepted");
            var shortHigh=Fresh(1);t=shortHigh.Now+1000;shortHigh.SetSclk(true,t);shortHigh.SetSclk(false,t+454);
            Check(shortHigh.ProtocolFault && shortHigh.LastError.Contains("high phase"),"short-high timing rejected");
            var shortLow=Fresh(1);t=shortLow.Now+1000;shortLow.SetSclk(true,t);shortLow.SetSclk(false,t+1000);shortLow.SetSclk(true,t+1454);
            Check(shortLow.ProtocolFault && shortLow.LastError.Contains("low phase"),"short-low timing rejected");
            var conflict=Fresh(1);conflict.SetHostDout(true,conflict.Now);
            Check(conflict.ProtocolFault && conflict.Errors>0 && !conflict.DeviceDout.HasValue && !conflict.ResolvedDout.HasValue,"electrical drive conflict is visible, not silently overwritten");
            var partial=Fresh(0);for(var i=0;i<7;i++)Pulse(partial);
            partial.AdvanceTo(partial.NextReadyNanoseconds-26130);
            Check(partial.ProtocolFault && partial.LastError.Contains("update exclusion"),"partial transfer across update window rejected");
            var unstable=Fresh(0);Read24(unstable);End27(unstable,false);Pulse(unstable);Pulse(unstable);
            unstable.SetHostDout(true,unstable.Now);t=unstable.Now+1000;unstable.SetSclk(true,t);unstable.SetHostDout(false,t+500);
            Check(unstable.ProtocolFault && unstable.ConfigWrites==0,"ambiguous input bit transition cannot create a valid configuration");
            foreach(byte invalid in new byte[]{0x80,0x0d,0x0e,0x4c})
            {
                var d=Fresh(0);Write(d,invalid);
                Check(d.ProtocolFault && d.ConfigWrites==0 && d.Config==0x0c,"reserved/unspecified analog configuration does not silently succeed");
            }
            var badCommand=Fresh(0);Read24(badCommand);End27(badCommand,false);Command(badCommand,0);
            Check(badCommand.ProtocolFault && badCommand.ConfigWrites==0,"unknown command reported unsupported");
            var removed=Fresh(0);removed.RemoveSyntheticSource();removed.AdvanceTo(removed.NextReadyNanoseconds);
            Check(removed.ProtocolFault && removed.LastError.Contains("synthetic sample"),"removed analog test source cannot manufacture a disconnected code");
            var stuckClock=Fresh(0);stuckClock.AdvanceTo(stuckClock.NextReadyNanoseconds+2*stuckClock.ConversionPeriodNanoseconds);
            Check(stuckClock.ReadWordCount==0 && stuckClock.ConversionCount==4 && stuckClock.OverwrittenUnreadWords==3,"stuck-low clock cannot synthesize consumed samples");
            var holdLast=Fresh(2);Read24(holdLast);t=holdLast.NextReadyNanoseconds;
            holdLast.AdvanceTo(t-26131);Check(holdLast.DeviceDout==false,"24-only read holds low LSB until update interval");
            holdLast.AdvanceTo(t-26130);Check(holdLast.DeviceDout==true && !holdLast.Ready,"update interval distinguishes low LSB from new-ready edge");
            rejected=false;try{holdLast.AdvanceTo(0);}catch(ArgumentOutOfRangeException){rejected=true;}
            Check(rejected,"time cannot run backwards");
            foreach(var lastClock in new int[]{24,27,46})
            {
                var boundary=Fresh(0);
                if(lastClock==46)
                {
                    Read24(boundary);End27(boundary,false);Command(boundary,0x56);Pulse(boundary);
                    for(var i=38;i<=45;i++)Pulse(boundary);
                }
                else for(var i=1;i<lastClock;i++)Pulse(boundary);
                var before=boundary.ReadWordCount;var w=boundary.NextReadyNanoseconds-26130;
                boundary.SetSclk(true,w-100);boundary.AdvanceTo(w);boundary.SetSclk(false,w+1000);
                Check(boundary.ProtocolFault && boundary.ReadWordCount==before,"in-flight final clock cannot complete across data update window "+lastClock);
            }
            foreach(var advance in new long[]{480,500})
            {
                var lowPending=Fresh(0);for(var i=0;i<23;i++)Pulse(lowPending);
                var lowWindow=lowPending.NextReadyNanoseconds-26130;var oldReads=lowPending.ReadWordCount;
                lowPending.SetSclk(true,lowWindow-advance);lowPending.SetSclk(false,lowWindow-advance+455);lowPending.AdvanceTo(lowWindow);
                Check(lowPending.ProtocolFault && lowPending.ReadWordCount==oldReads,"pending24th bit cannot complete after/at update boundary "+advance);
            }
            foreach(byte gainValue in new byte[]{0x00,0x04,0x08,0x0c})
            {
                var g=Fresh(4);Write(g,gainValue);Check(!g.ProtocolFault && g.Gain==new int[]{1,2,64,128}[(gainValue>>2)&3],"all documented PGA selections");
            }
            var temp=Fresh(4);Write(temp,0x02);Check(!temp.ProtocolFault && temp.Channel==2 && temp.Gain==1,"valid temperature configuration does not invent temperature data");
            foreach(var stopAt in new int[]{32,40})
            {
                var inc=Fresh(0);Read24(inc);End27(inc,false);Pulse(inc);Pulse(inc);
                var cmd=0x65;
                for(var bit=6;bit>=0 && inc.ClockCount<stopAt;bit--){inc.SetHostDout((cmd&(1<<bit))!=0,inc.Now);Pulse(inc);}
                if(stopAt>36){Pulse(inc);while(inc.ClockCount<stopAt){inc.SetHostDout(false,inc.Now);Pulse(inc);}}
                inc.SetHostDout(null,inc.Now);inc.AdvanceTo(inc.NextReadyNanoseconds-26130);
                Check(inc.ProtocolFault && inc.ConfigWrites==0,"incomplete command/configuration cannot commit "+stopAt);
            }
            var absentBit=Fresh(0);Read24(absentBit);End27(absentBit,false);Pulse(absentBit);Pulse(absentBit);Pulse(absentBit);
            Check(absentBit.ProtocolFault && absentBit.LastError.Contains("Missing host"),"missing command input is not a zero bit");
            var extra=Fresh(0);ReadConfig(extra);Pulse(extra);Check(extra.ProtocolFault && extra.LastError.Contains("beyond"),"extra clock47 is unsupported");
            var veryDelayed=new Cs1237Protocol(3300000);veryDelayed.SetSyntheticCode(0);veryDelayed.AdvanceTo(veryDelayed.NextReadyNanoseconds);
            for(var n=1;n<=29;n++)
            {
                var rise=veryDelayed.Now+1000;veryDelayed.SetSclk(true,rise);veryDelayed.SetSclk(false,rise+1000);veryDelayed.AdvanceTo(rise+3300000);
            }
            Check(!veryDelayed.ProtocolFault && !veryDelayed.DeviceDout.HasValue,"long explicit delay still permits slow default-rate frame prefix");
            for(var bit=6;bit>=0;bit--){veryDelayed.SetHostDout((0x65&(1<<bit))!=0,veryDelayed.Now);Pulse(veryDelayed);}
            Pulse(veryDelayed);
            for(var bit=7;bit>=0;bit--){veryDelayed.SetHostDout((0x3c&(1<<bit))!=0,veryDelayed.Now);Pulse(veryDelayed);}
            veryDelayed.SetHostDout(null,veryDelayed.Now);Pulse(veryDelayed);veryDelayed.AdvanceTo(veryDelayed.NextReadyNanoseconds);
            Check(veryDelayed.ProtocolFault && veryDelayed.LastError.Contains("overlaps new conversion"),"old delayed force-high cannot overwrite a new ready-low");
            foreach(var stop in new int[]{25,26})
            {
                var incomplete=Fresh(0);for(var i=0;i<stop;i++)Pulse(incomplete);
                incomplete.AdvanceTo(incomplete.NextReadyNanoseconds-26130);
                Check(incomplete.ProtocolFault,"stop at undocumented partial status length "+stop+" remains unsupported");
            }
            var dual=Fresh(0);dual.SetHostDout(false,dual.Now);
            Check(dual.ProtocolFault,"same-level dual drive is unsupported ownership, not success");
            var wakeEarly=Fresh(0);t=wakeEarly.Now+1000;wakeEarly.SetSclk(true,t);wakeEarly.AdvanceTo(t+100001);wakeEarly.SetSclk(false,t+110000);
            wakeEarly.SetSclk(true,wakeEarly.Now+9999);
            Check(wakeEarly.ProtocolFault && wakeEarly.LastError.Contains("Wake low"),"wake low minimum enforced independently of settling");
            var resetHost=Fresh(0);resetHost.SetSclk(true,resetHost.Now+1000);
            rejected=false;try{resetHost.PowerOnReset(resetHost.Now);}catch(InvalidOperationException){rejected=true;}
            Check(rejected && resetHost.Sclk,"chip reset cannot silently reset a host-driven clock");
            var resetDrive=Fresh(0);Read24(resetDrive);End27(resetDrive,false);Pulse(resetDrive);Pulse(resetDrive);resetDrive.SetHostDout(true,resetDrive.Now);
            rejected=false;try{resetDrive.PowerOnReset(resetDrive.Now);}catch(InvalidOperationException){rejected=true;}
            Check(rejected && resetDrive.HostDout==true,"chip reset cannot silently release host data drive");
            return "CS1237 ISOLATED PROTOCOL TESTS PASS: "+checks+" checks; synthetic inputs only; no GPIO/native integration";
        }
        private int checks;
    }
}
