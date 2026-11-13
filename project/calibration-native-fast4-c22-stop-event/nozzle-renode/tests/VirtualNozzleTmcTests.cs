using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Nozzle;
using Antmicro.Renode.Peripherals.AT32;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.NozzleTests {
 public class VirtualNozzleTmcTests:IDoubleWordPeripheral,IKnownSize {
  public VirtualNozzleTmcTests(IMachine machine,VirtualNozzleTmc2209 tmc, AT32GPIO gpio){t=tmc;g=gpio;wave=new LimitTimer(machine.ClockSource,40000,this,"test GPIO waveform",1,direction:Direction.Ascending,workMode:WorkMode.Periodic,enabled:false,eventEnabled:true);wave.LimitReached+=WaveBit;capture=new LimitTimer(machine.ClockSource,160000,this,"test reply sampler",1,direction:Direction.Ascending,workMode:WorkMode.Periodic,enabled:false,eventEnabled:true);capture.LimitReached+=CaptureBit;}
  public long Size{get{return 4;}}public void Reset(){}public uint ReadDoubleWord(long o){return 0;}public void WriteDoubleWord(long o,uint v){}
  void Check(bool b,string s){if(!b)throw new Exception(s);n++;}
  void Feed(byte[] a){foreach(var b in a)t.ReceiveByte(b);}
  void Read(byte r,byte addr=0){var a=new byte[]{5,addr,r,0};a[3]=VirtualNozzleTmc2209.Crc8(a,3);Feed(a);}
  void Write(byte r,uint v){var a=new byte[]{5,0,(byte)(r|128),(byte)(v>>24),(byte)(v>>16),(byte)(v>>8),(byte)v,0};a[7]=VirtualNozzleTmc2209.Crc8(a,7);Feed(a);}
  byte[] Reply(){var parts=t.LastReply.Split('-');var a=new byte[parts.Length];for(var i=0;i<a.Length;i++)a[i]=Convert.ToByte(parts[i],16);return a;}
  uint Value(){var b=Reply();return (uint)b[3]<<24|(uint)b[4]<<16|(uint)b[5]<<8|b[6];}
  public string Run(){n=0;t.Reset();Read(6);Check(Value()==0x21000000,"TMC2209 version");Read(1);Check(Value()==1,"reset status");Write(1,1);Read(1);Check(Value()==0,"W1C");
   Write(0,0x1c0);Read(0);Check(Value()==0x1c0,"GCONF readback");Read(2);Check(Value()==2,"IFCNT");
   var writes=t.Writes;Write(6,0);Check(t.Writes==writes,"read only rejected");var reads=t.Reads;Read(2,1);Check(t.Reads==reads,"wrong slave ignored");
   Feed(new byte[]{5,0,2,0});Check(t.Reads==reads,"bad request CRC ignored");Read(0x7f);Check(t.Reads==reads,"unknown register ignored");
   t.DriverFaultStatus=2;Read(0x6f);Check(Value()==0x80000002,"driver fault visible");Read(1);Check((Value()&2)!=0,"GSTAT driver fault visible");
   t.CorruptReplyCrc=true;Read(2);var reply=Reply();Check(VirtualNozzleTmc2209.Crc8(reply,7)!=reply[7],"corrupt reply");
   reads=t.Reads;t.Disconnected=true;Read(2);Check(t.Reads==reads,"disconnect");t.Reset();Check(t.Disconnected&&t.CorruptReplyCrc&&t.DriverFaultStatus==2,"faults persist reset");
   t.Disconnected=false;t.CorruptReplyCrc=false;t.DriverFaultStatus=0;for(var i=0;i<256;i++)Write(0,(uint)i);Read(2);Check(Value()==0,"IFCNT wraps");
   t.Reset();Check(t.Reads==0&&t.Writes==0&&t.ReceivedBytes==0,"reset clears transport");return "NOZZLE TMC TESTS PASS: "+n;}
  public void StartWaveform(){t.Reset();g.WriteDoubleWord(0xc,8);g.WriteDoubleWord(0,0x44441444);waveIndex=0;captureCount=0;captureBit=-1;captureValue=0;capture.Value=0;capture.Enabled=true;wave.Value=0;wave.Enabled=true;}
  void WaveBit(){if(waveIndex==40){g.WriteDoubleWord(0,0x44444444);wave.Enabled=false;return;}var data=new byte[]{0xf5,0,2,0xc8};int bit=waveIndex%10;bool value=bit==9||(bit>0&&(data[waveIndex/10]&(1<<(bit-1)))!=0);g.WriteDoubleWord(0xc,value?8u:0u);waveIndex++;}
  void CaptureBit(){if(wave.Enabled)return;bool level=(g.ReadDoubleWord(8)&8)!=0;if(captureBit<0){if(level)return;captureBit=0;captureWait=5;captureValue=0;return;}if(captureWait-->0)return;if(captureBit<8){if(level)captureValue|=(byte)(1<<captureBit);captureBit++;captureWait=3;return;}if(!level)throw new Exception("reply stop bit");captured[captureCount++]=captureValue;captureBit=-1;if(captureCount==8)capture.Enabled=false;}
  public string CheckWaveform(){Check(t.ReceivedBytes==4,"GPIO decoded all bytes");Check(t.Reads==1,"GPIO decoded valid read");Check(t.LastRequest=="F5-00-02-C8","GPIO request identity");Check(t.LastReply.StartsWith("05-FF-02-"),"GPIO response identity");Check(captureCount==8,"eight reply bytes on GPIO");Check(captured[0]==5&&captured[1]==255&&captured[2]==2,"GPIO reply decoded");Check(VirtualNozzleTmc2209.Crc8(captured,7)==captured[7],"GPIO reply CRC");return "NOZZLE GPIO WAVEFORM PASS";}
  readonly VirtualNozzleTmc2209 t;readonly AT32GPIO g;readonly LimitTimer wave,capture;readonly byte[] captured=new byte[8];byte captureValue;int captureCount,captureBit,captureWait;int waveIndex;int n;
 }
}
