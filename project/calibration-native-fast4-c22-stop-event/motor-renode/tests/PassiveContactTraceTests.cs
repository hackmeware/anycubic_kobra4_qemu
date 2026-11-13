// SPDX-License-Identifier: MIT
using System;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
 public class PassiveContactTraceTests : IPeripheral
 {
  public PassiveContactTraceTests(GenericStepperElectromechanical plant){p=plant;}
  public void Reset(){}
  void Check(bool v,string s){if(!v)throw new Exception(s);n++;}
  public string Start(string path,int capacity)
  {
   p.ConfigureRelativeContact(0,-0.02,0.02,10,0.01);p.SetLoadTorque(0,-0.02);
   var count=p.IntegrationCalls;var angle=BitConverter.DoubleToInt64Bits(p.GetAngleRadians(0));
   if(capacity>0){p.StartContactTrace(path,capacity,true);Check(p.ContactTraceEnabled,"enabled");}
   Check(p.IntegrationCalls==count,"start never integrates");Check(BitConverter.DoubleToInt64Bits(p.GetAngleRadians(0))==angle,"start does not change state");
   if(capacity>0){bool rejected=false;try{p.StartContactTrace(path,capacity,true);}catch(InvalidOperationException){rejected=true;}Check(rejected,"reject duplicate start");}
   return "CONTACT TEST STARTED";
  }
  public void Sample(int stage)
  {
   var before=p.IntegrationCalls;p.OnGPIO(0,true);Check(p.IntegrationCalls==before+3,"one normal advance per axis");
   before=p.IntegrationCalls;p.OnGPIO(0,true);Check(p.IntegrationCalls==before,"same time no integration");
   if(stage==40)p.SetLoadTorque(0,0.02);
   p.CaptureTrace();
  }
  public string Finish(string physicalPath,string countPath,bool bounded)
  {
   var before=p.IntegrationCalls;p.StopContactTrace();Check(p.IntegrationCalls==before,"stop never integrates");
   Check(p.ContactLastError=="","no observer error");if(bounded)Check(p.ContactDroppedRows>0,"bounded observer reports drops");
   p.WriteCsv(physicalPath);File.WriteAllText(countPath,p.IntegrationCalls.ToString());
   return "PASSIVE CONTACT TESTS PASS: "+n+" rows="+p.ContactRowsWritten+" dropped="+p.ContactDroppedRows;
  }
  GenericStepperElectromechanical p;int n;
 }
}
