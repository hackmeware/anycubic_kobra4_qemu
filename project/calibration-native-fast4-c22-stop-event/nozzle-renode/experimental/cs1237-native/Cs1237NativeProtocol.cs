// SPDX-License-Identifier: MIT
// Isolated CS1237 protocol-conformance core. NOT a native GPIO binding or force model.
// Chipsea Rev1.1: pp12-18. Strict test contracts for unspecified timing are in README.
using System;
namespace Antmicro.Renode.Peripherals.NozzleExperimental
{
    public sealed class Cs1237NativeProtocol
    {
        public Cs1237NativeProtocol(long outputDelayNanoseconds, bool allowHostPriorityOverlap = false)
        {
            // Datasheet t6 has a MINIMUM of455ns, not a maximum. The test must choose
            // this latency explicitly; it is not a verified silicon maximum/default.
            if(outputDelayNanoseconds < 455) throw new ArgumentOutOfRangeException("outputDelayNanoseconds");
            allowOverlap=allowHostPriorityOverlap;outputDelay=outputDelayNanoseconds; PowerOnReset(0);
        }
        // Exact deadline introspection only; digital event semantics remain from frozen core.
        public long NextEventNanoseconds { get { return Math.Min(Sclk && !PoweredDown ? CheckedAdd(highAt,100001) : Never, Math.Min(invalidateAt,Math.Min(pendingAt,Math.Min(windowAt,nextReady)))); } }
        public long HostPriorityOverlapObservations { get; private set; }
        public string LastOverlap { get; private set; }
        public long Now { get; private set; }
        public byte Config { get; private set; }
        public bool? DeviceDout { get; private set; }
        public bool? HostDout { get; private set; }
        public bool OutputTransition { get; private set; }
        public bool Sclk { get; private set; }
        public bool PoweredDown { get; private set; }
        public bool ProtocolFault { get; private set; }
        public string LastError { get; private set; }
        public long Errors { get; private set; }
        public long ConversionCount { get; private set; }
        public long ReadWordCount { get; private set; }
        public long OverwrittenUnreadWords { get; private set; }
        public long ConfigWrites { get; private set; }
        public long ConfigReads { get; private set; }
        public long PowerDownCount { get; private set; }
        public int ClockCount { get; private set; }
        public bool ConfigUpdated { get; private set; }
        public bool HasSyntheticSample { get; private set; }
        public bool Ready { get; private set; }
        public long NextReadyNanoseconds { get { return nextReady; } }
        public long ConversionPeriodNanoseconds { get { return Period(Config); } }
        public int Gain { get { return new int[]{1,2,64,128}[(Config>>2)&3]; } }
        public int Channel { get { return Config&3; } }
        public bool ReferenceOutputEnabled { get { return (Config&0x40)==0; } }
        public int LastLatchedSignedCode { get; private set; }
        public bool? ResolvedDout
        {
            get
            {
                if(ProtocolFault || OutputTransition) return null;
                if(DeviceDout.HasValue && HostDout.HasValue && DeviceDout.Value!=HostDout.Value) return null;
                return DeviceDout ?? HostDout;
            }
        }
        // Explicit laboratory source only: no physical voltage, force, bed or nozzle claim.
        public void SetSyntheticCode(int signedCode)
        {
            if(signedCode < -8388608 || signedCode > 8388607) throw new ArgumentOutOfRangeException("signedCode");
            synthetic=signedCode; HasSyntheticSample=true;
        }
        public void RemoveSyntheticSource() { HasSyntheticSample=false; }
        public static int SaturateIdealCode(long signedIdealCode)
        { return signedIdealCode>8388607 ? 8388607 : signedIdealCode < -8388608 ? -8388608 : (int)signedIdealCode; }
        public static uint WireBits(int code)
        {
            if(code < -8388608 || code > 8388607) throw new ArgumentOutOfRangeException("code");
            return (uint)code&0xffffff;
        }
        // Actual power-on reset, not an MCU reset hook. Keeps the external synthetic
        // source and diagnostic counters. Clears register to documented POR0x0c.
        public void PowerOnReset(long now)
        {
            if(now<Now) throw new ArgumentOutOfRangeException("now");
            if(Sclk || HostDout.HasValue) throw new InvalidOperationException("Laboratory POR requires caller-supplied idle-low SCLK and released host DOUT");
            Now=now;Config=0x0c;PoweredDown=false;
            ProtocolFault=false;LastError="";ConfigUpdated=false;ClockCount=0;Ready=false;
            highAt=Never;lastFall=Never;pendingAt=Never;invalidateAt=Never;windowAt=Never;wakeLowUntil=0;command=0;writeValue=0;OutputTransition=false;
            inputPulse=false;earlyPulse=false;pendingWordComplete=false;DeviceDout=true;
            nextReady=CheckedAdd(now,2000000+Settling(Config));
        }
        public void SetHostDout(bool? level,long now)
        {
            AdvanceTo(now);
            if(inputPulse && level!=hostAtRise) { Fail("Host data changed during a sampled high phase; capture edge is unspecified"); }
            HostDout=level;
            CheckContention();
        }
        public void SetSclk(bool level,long now)
        {
            AdvanceTo(now);
            if(level==Sclk) return;
            if(level)
            {
                if(now<wakeLowUntil) Fail("Wake low hold below10us minimum");
                if(lastFall!=Never && now-lastFall<455) Fail("SCLK low phase below455ns minimum");
                Sclk=true;highAt=now;
                if(ProtocolFault || PoweredDown) return;
                if(!Ready) { earlyPulse=true;return; } // Long high may legitimately request power-down.
                ClockCount++;
                if(ClockCount>46) { Fail("Clock beyond documented46-clock frame");return; }
                hostAtRise=HostDout;inputPulse=InputClock(ClockCount);
                if(inputPulse && !HostDout.HasValue) { Fail("Missing host-driven command/register bit");return; }
                if(ClockCount<=24) Schedule((WireBits(LastLatchedSignedCode)&(1u<<(24-ClockCount)))!=0);
                else if(ClockCount==25) Schedule(ConfigUpdated);
                else if(ClockCount==26) Schedule(false);
                else if(ClockCount==27 || ClockCount==28) Schedule(true);
                else if(ClockCount==29) Schedule(null); // Ownership released by completion of29.
                else if(ClockCount==37 && command==0x56) Schedule(true); // Non-data turnaround level is a test convention.
                else if(ClockCount>=38 && ClockCount<=45 && command==0x56)
                    Schedule((Config&(1<<(45-ClockCount)))!=0);
                else if(ClockCount==46) Schedule(true);
            }
            else
            {
                var highDuration=now-highAt;Sclk=false;highAt=Never;lastFall=now;
                if(PoweredDown)
                {
                    PoweredDown=false;ProtocolFault=false;LastError="";inputPulse=false;earlyPulse=false;pendingWordComplete=false;
                    Ready=false;ClockCount=0;pendingAt=invalidateAt=Never;windowAt=Never;DeviceDout=true;OutputTransition=false;wakeLowUntil=CheckedAdd(now,10000);
                    // Retains Config across power-down, as expressly documented onp12.
                    nextReady=CheckedAdd(now,2000000+Settling(Config));CheckContention();return;
                }
                if(ProtocolFault) return;
                if(highDuration<455) { Fail("SCLK high phase below455ns minimum");return; }
                if(earlyPulse) { earlyPulse=false;Fail("Clock before conversion-ready; pre-ready configuration is unspecified");return; }
                if(inputPulse)
                {
                    inputPulse=false;
                    if(HostDout!=hostAtRise) { Fail("Input not stable over whole high phase");return; }
                    // Conformance contract: bit must cover BOTH clock edges. No claim
                    // about which undocumented silicon input edge performs the capture.
                    var bit=HostDout.Value?1:0;
                    if(ClockCount<=36) command=(byte)((command<<1)|bit);
                    else writeValue=(byte)((writeValue<<1)|bit);
                }
                if(ClockCount==24)
                {
                    if(pendingAt==Never) ReadWordCount++;else pendingWordComplete=true;
                }
                if(ClockCount==36 && command!=0x65 && command!=0x56) { Fail("Undocumented command");return; }
                if(ClockCount==46)
                {
                    if(command==0x65)
                    {
                        if((writeValue&0x80)!=0 || (writeValue&3)==1 || ((writeValue&3)==2 && (writeValue&12)!=0))
                        { Fail("Reserved/unsupported configuration encoding");return; }
                        var old=Config;
                        if(((old^writeValue)&0x40)!=0) { Fail("REF output switching analog settling is unspecified");return; }
                        Config=writeValue;ConfigUpdated=true;ConfigWrites++;
                        if((old&3)!=(Config&3)) BeginSettle(2000000);
                        else if((old&0x3c)!=(Config&0x3c)) BeginSettle(800);
                    }
                    else { ConfigUpdated=false;ConfigReads++; }
                    // Completed framing remains high until the next actual conversion.
                }
            }
        }
        public void AdvanceTo(long now)
        {
            if(now<Now) throw new ArgumentOutOfRangeException("now");
            while(true)
            {
                var powerAt=Sclk && !PoweredDown ? CheckedAdd(highAt,100001) : Never;
                var at=Math.Min(powerAt,Math.Min(invalidateAt,Math.Min(pendingAt,Math.Min(windowAt,nextReady))));
                if(at==Never || at>now) break;
                Now=at;
                if(powerAt==at)
                {
                    PoweredDown=true;PowerDownCount++;Ready=false;inputPulse=false;earlyPulse=false;pendingWordComplete=false;
                    pendingAt=invalidateAt=windowAt=nextReady=Never;DeviceDout=true;OutputTransition=false;CheckContention();continue;
                }
                // Exclusion/new-conversion boundaries win ties over pending output.
                // A bit becoming valid exactly at exclusion was never sampleable before it.
                if((windowAt==at || nextReady==at) && (pendingAt!=Never || invalidateAt!=Never || inputPulse))
                { Fail(windowAt==at ? "Transaction crosses ADC update exclusion window" : "Pending transaction output overlaps new conversion");continue; }
                if(invalidateAt==at)
                {
                    invalidateAt=Never;OutputTransition=true;DeviceDout=null;CheckContention();continue;
                }
                if(pendingAt==at)
                {
                    DeviceDout=pendingLevel;OutputTransition=false;pendingAt=Never;CheckContention();
                    if(pendingWordComplete && !ProtocolFault) { ReadWordCount++;pendingWordComplete=false; }
                    continue;
                }
                if(windowAt==at)
                {
                    windowAt=Never;
                    if(pendingAt!=Never || invalidateAt!=Never || (Sclk && ClockCount>0) || (ClockCount>0 && ClockCount!=24 && ClockCount!=27 && ClockCount!=46))
                    { Fail("Transaction crosses ADC update exclusion window");continue; }
                    if(Ready && ClockCount==0) OverwrittenUnreadWords++;
                    Ready=false;DeviceDout=true;OutputTransition=false;pendingAt=invalidateAt=Never;CheckContention();continue;
                }
                if(nextReady==at)
                {
                    if(pendingAt!=Never || invalidateAt!=Never || inputPulse) { Fail("Pending transaction output overlaps new conversion");continue; }
                    if(!HasSyntheticSample) { Fail("No explicitly configured synthetic sample source");continue; }
                    LastLatchedSignedCode=synthetic;ConversionCount++;Ready=true;ClockCount=0;
                    command=writeValue=0;inputPulse=false;DeviceDout=false;
                    nextReady=CheckedAdd(at,Period(Config));windowAt=nextReady-26130;CheckContention();continue;
                }
            }
            Now=now;
        }
        private bool InputClock(int n) { return (n>=30 && n<=36) || (n>=38 && n<=45 && command==0x65); }
        private void BeginSettle(long analog)
        {
            Ready=false;windowAt=Never;nextReady=CheckedAdd(Now,analog+Settling(Config));
        }
        private void Schedule(bool? level)
        {
            if(pendingAt!=Never) { Fail("New output edge precedes explicitly chosen propagation delay");return; }
            pendingLevel=level;pendingAt=CheckedAdd(Now,outputDelay);
            // t7 guarantees only227.5ns minimum hold. Integer-nanosecond
            // tests expose the transition as unknown from228ns until chosen t6.
            if(DeviceDout.HasValue && level.HasValue && DeviceDout!=level)
                invalidateAt=CheckedAdd(Now,228);
        }
        private void CheckContention()
        {
            // EXPLICIT VIRTUAL ELECTRICAL ASSUMPTION, disabled by default. The host's
            // push-pull pad dominates while it is output; contention is recorded,
            // not represented as a valid sensor reading or silicon guarantee.
            if(allowOverlap && HostDout.HasValue && (DeviceDout.HasValue || OutputTransition))
            { HostPriorityOverlapObservations++; LastOverlap=OutputTransition ? "host versus transitioning device" : DeviceDout==HostDout ? "same-level dual drive" : "conflicting drive"; return; }

            if(OutputTransition && HostDout.HasValue)
                Fail("Host drives DOUT during unknown device output transition");
            else if(DeviceDout.HasValue && HostDout.HasValue)
                Fail(DeviceDout.Value!=HostDout.Value ? "DOUT conflicting host/device drive" : "DOUT dual drive outside documented host ownership");
        }
        private void Fail(string reason)
        {
            Errors++;ProtocolFault=true;LastError=reason;Ready=false;DeviceDout=null;
            nextReady=windowAt=pendingAt=invalidateAt=Never;inputPulse=false;earlyPulse=false;pendingWordComplete=false;OutputTransition=false;
        }
        private static long Period(byte config) { return new long[]{100000000,25000000,1562500,781250}[(config>>4)&3]; }
        private static long Settling(byte config) { return Period(config)*(((config>>4)&3)<2?3:4); }
        private static long CheckedAdd(long a,long b) { return checked(a+b); }
        private const long Never=long.MaxValue;
        private readonly long outputDelay;
        private readonly bool allowOverlap;
        private long highAt,lastFall,pendingAt,invalidateAt,windowAt,nextReady,wakeLowUntil;
        private bool? pendingLevel,hostAtRise;
        private bool inputPulse,earlyPulse,pendingWordComplete;
        private int synthetic;
        private byte command,writeValue;
    }
}
