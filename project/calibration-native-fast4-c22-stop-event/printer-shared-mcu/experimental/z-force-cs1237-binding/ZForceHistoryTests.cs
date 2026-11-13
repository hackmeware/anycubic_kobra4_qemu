// SPDX-License-Identifier: MIT
using System;
namespace Antmicro.Renode.Peripherals.PrinterExperimental
{
    public sealed class ZForceHistoryTests : IPeripheral
    {
        public void Reset(){}
        private void Check(bool condition,string label){checks++;if(!condition)throw new Exception(label);}
        private void Reject(Action action,string label){bool failed=false;try{action();}catch(ArgumentException){failed=true;}catch(InvalidOperationException){failed=true;}Check(failed,label);}
        private static ZForceSnapshot S(long state,long capture=-1,int code=0)
        {return new ZForceSnapshot(state,capture<0?state:capture,state/1e9,code*0.001,Math.Abs(code)*0.1,code,false,true);}
        public string RunAll()
        {
            checks=0;
            Reject(()=>new ZForceHistory(0,0),"positive freshness bound required");
            Reject(()=>new ZForceHistory(100,-1),"negative skew rejected");
            Reject(()=>new ZForceHistory(100,0,1),"capacity bounded");
            Reject(()=>new ZForceSnapshot(2,1,2e-9,0,0,0,false,true),"future physical state cannot masquerade as past capture");
            var h=new ZForceHistory(100,20,20,2);h.Add(S(0));h.Add(S(50,code:5));h.Add(S(100,code:10));
            Check(h.ReadAt(80).SignedCode==5,"future state skipped within declared producer skew");
            Check(h.ReadAt(100).SignedCode==10,"exact deadline uses exact physical state");
            h.Add(S(120,code:12));Check(h.ReadAt(100).SignedCode==10,"same candidate deadline stable");
            Check(h.ReadAt(200).SignedCode==12,"bounded stale sample selected without extrapolation");
            Check(h.DroppedTraceRows==1,"optional trace bounded without losing functional sample");
            Reject(()=>h.ReadAt(199),"backwards consumer deadline rejected");Check(h.Faulted,"rollback is latched");
            Reject(()=>h.ReadAt(201),"latched source cannot quietly recover");
            var future=new ZForceHistory(100,20);future.Add(S(10));Reject(()=>future.ReadAt(9),"future-only physical data rejected");
            var skew=new ZForceHistory(100,5);skew.Add(S(0));skew.Add(S(10));Reject(()=>skew.ReadAt(4),"excess producer lead rejected");
            var stale=new ZForceHistory(10,0);stale.Add(S(0));Check(stale.ReadAt(10).StateNanoseconds==0,"exact age bound accepted");
            Reject(()=>stale.ReadAt(11),"one beyond age bound rejected");
            var empty=new ZForceHistory(10,0);Reject(()=>empty.ReadAt(0),"missing history rejected");
            var backwards=new ZForceHistory(100,0);backwards.Add(S(100));Reject(()=>backwards.Add(S(99)),"motor epoch rollback rejected");
            var ordering=new ZForceHistory(100,0);Reject(()=>ordering.Add(S(10,12)),"observer before plant integration rejected");
            var ambiguous=new ZForceHistory(100,0);ambiguous.Add(S(10));Reject(()=>ambiguous.Add(S(10,code:1)),"same-time changed physical state rejected");
            var duplicate=new ZForceHistory(100,0);duplicate.Add(S(10));duplicate.Add(S(10));Check(duplicate.Count==1,"identical duplicate trigger coalesced");
            var tight=new ZForceHistory(100,0,2);tight.Add(S(0));tight.Add(S(1));Reject(()=>tight.Add(S(2)),"still-eligible history never silently overwritten");
            var longRun=new ZForceHistory(100,20,20);
            for(int i=0;i<100000;i++)
            {
                long now=i*10;longRun.Add(S(now));
                if(i>0&&i%1000==0)Check(longRun.ReadAt(now).StateNanoseconds==now,"long-run exact sample");
            }
            Check(longRun.Count<=13&&longRun.Retired>99000,"safe retirement before first and between sparse consumers");
            Check(!longRun.Faulted,"long-run history does not inevitably overflow");
            var noTrace=new ZForceHistory(100,20,20,0);var traced=new ZForceHistory(100,20,20,1);
            for(int i=0;i<20;i++){noTrace.Add(S(i*10,code:i));traced.Add(S(i*10,code:i));Check(noTrace.ReadAt(i*10).SignedCode==traced.ReadAt(i*10).SignedCode,"trace on/off selected sample invariance");}
            Check(noTrace.DroppedTraceRows==0&&traced.DroppedTraceRows==19,"trace drops are explicit and independent of functional retention");
            return "Z FORCE HISTORY TESTS PASS: "+checks;
        }
        private int checks;
    }
}
