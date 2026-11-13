using System;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.AT32;
namespace Antmicro.Renode.Peripherals.AT32Tests
{
 public class VirtualMotorTmcTests : IDoubleWordPeripheral, IKnownSize
 {
  public VirtualMotorTmcTests(IMachine machine, VirtualMotorTmcGateway gateway) {g=gateway;}
  public long Size {get{return 4;}} public void Reset(){} public uint ReadDoubleWord(long a){return 0;} public void WriteDoubleWord(long a,uint v){}
  private void Check(bool v,string why){if(!v)throw new Exception(why);checks++;}
  private void Feed(byte[] b){foreach(var v in b)g.ReceiveByte(v);}
  private byte[] Frame(byte command,byte[] payload)
  {var b=new byte[payload.Length+6];b[0]=126;b[1]=5;b[2]=command;b[3]=(byte)payload.Length;Array.Copy(payload,0,b,4,payload.Length);var c=VirtualMotorTmcGateway.Crc16(b,b.Length-2);b[b.Length-2]=(byte)c;b[b.Length-1]=(byte)(c>>8);return b;}
  private void Read(byte reg,byte address=3)
  {var a=new byte[]{245,address,reg,0};a[3]=VirtualMotorTmcGateway.Crc8(a,3);Feed(Frame(8,new byte[]{2,a[0],a[1],a[2],a[3]}));}
  private void Write(byte reg,uint v)
  {var a=new byte[]{245,3,(byte)(reg|128),(byte)(v>>24),(byte)(v>>16),(byte)(v>>8),(byte)v,0};a[7]=VirtualMotorTmcGateway.Crc8(a,7);var p=new byte[9];p[0]=2;Array.Copy(a,0,p,1,8);Feed(Frame(8,p));}
  private byte[] Reply(){var s=g.LastReply;var b=new byte[s.Length/2];for(var i=0;i<b.Length;i++)b[i]=Convert.ToByte(s.Substring(i*2,2),16);return b;}
  private uint Value(){var b=Reply();return (uint)b[7]<<24|(uint)b[8]<<16|(uint)b[9]<<8|b[10];}
  public string Run()
  {
   checks=0;g.Reset();Check(VirtualMotorTmcGateway.Crc8(new byte[]{245,3,2},3)==0x25,"captured TMC CRC");
   Feed(new byte[]{126,0,8,5,2,245,3,2,0x25,0xe7,0x14});Check(g.Reads==1,"captured IFCNT read");Check(Value()==0,"initial IFCNT");Check(g.PendingBytes==21,"ACK plus response queued");
   var b=Reply();Check(b[1]==9&&b[3]==2&&b[4]==5&&b[5]==255&&b[6]==2,"OID and TMC response header");
   Check(VirtualMotorTmcGateway.Crc16(b,b.Length-2)==(b[b.Length-2]|b[b.Length-1]<<8),"outer CRC");
   var beforeWrite=g.PendingBytes;Write(0x10,0x12345678);Check(g.Writes==1,"write accepted");Check(g.PendingBytes==beforeWrite+21&&Reply()[1]==9&&Reply()[4]==245&&Reply()[6]==0x90,"write produces original controller echo");Read(0x10);Check(Value()==0x12345678,"register readback");Read(2);Check(Value()==1,"IFCNT increments");
   Read(2,2);Check(Value()==0,"slave bank isolation");Read(1);Check(Value()==0,"original motor GSTAT default");g.InjectGeneralStatus(3,1);Read(1);Check(Value()==1,"injected reset flag");Write(1,1);Read(1);Check(Value()==0,"GSTAT write one clear");
   Read(6);Check(Value()==0,"original motor IOIN default");Read(0x70);Check(Value()==0xc10d0024,"original PWMCONF default");
   var wc=g.Writes;Write(6,123);Check(g.Writes==wc&&Value()==0,"original read-only write returns read value");
   g.DriverFaultStatus=2;Read(0x6f);Check(Value()==2,"fault not masked");
   g.CorruptTmcReplyCrc=true;Read(2);b=Reply();var raw=new byte[8];Array.Copy(b,4,raw,0,8);Check(VirtualMotorTmcGateway.Crc8(raw,7)!=raw[7],"CRC fault injection");
   var n=g.PendingBytes;g.Disconnected=true;Read(2);Check(g.PendingBytes==n,"disconnected no reply");g.Disconnected=false;
   var r=g.RejectedFrames;Feed(new byte[]{126,0,8,5,2,245,3,2,0x25,0xe7,0x15});Check(g.RejectedFrames==r+1,"outer CRC rejection");
   r=g.RejectedFrames;Feed(Frame(8,new byte[]{2,245,3,2,0}));Check(g.RejectedFrames==r+1,"inner CRC rejection");
   var u=g.UnsupportedFrames;n=g.PendingBytes;Feed(Frame(6,new byte[]{1,2}));Check(g.UnsupportedFrames==u+1&&g.PendingBytes==n,"no fake motion acknowledgement");
   u=g.UnsupportedFrames;Read(0x7f);Check(g.UnsupportedFrames==u+1,"unknown register remains unsupported");
   u=g.UnsupportedFrames;n=g.PendingBytes;Feed(Frame(0x22,new byte[0]));Check(g.UnsupportedFrames==u+1&&g.PendingBytes==n,"power-down query disabled by default");
   g.BlankPowerDownRecord=true;Feed(Frame(0x22,new byte[0]));b=Reply();Check(g.PowerDownQueries==1&&b[1]==0x23&&b[2]==12&&b.Length==17,"blank saved-record response shape");
   bool blank=true;for(var i=3;i<15;i++)blank &= b[i]==0;Check(blank,"explicit blank saved-position record");
   u=g.UnsupportedFrames;n=g.PendingBytes;Feed(Frame(0x24,new byte[12]));Check(g.UnsupportedFrames==u+1&&g.PendingBytes==n,"saved-record setter remains unsupported");
   g.BlankPowerDownRecord=false;
   u=g.UnsupportedFrames;n=g.PendingBytes;Feed(Frame(0x17,new byte[]{17}));Check(g.UnsupportedFrames==u+1&&g.PendingBytes==n,"version emulation disabled by default");
   g.EmulateFirmwareVersion=true;Feed(Frame(0x17,new byte[]{17}));b=Reply();Check(g.VersionQueries==1&&b.Length==9&&b[1]==0x18&&b[3]==17&&b[4]==1&&b[5]==6&&b[6]==1,"original firmware version response");
   r=g.RejectedFrames;n=g.PendingBytes;Feed(Frame(0x17,new byte[0]));Check(g.RejectedFrames==r+1&&g.PendingBytes==n,"missing version OID rejected");
   g.EmulateFirmwareVersion=false;
   g.Disconnected=true;g.Reset();Check(g.PendingBytes==0&&g.Reads==0&&g.Writes==0,"reset flushes");
   Check(g.Disconnected&&g.CorruptTmcReplyCrc&&g.DriverFaultStatus==2,"external fault survives reset");g.Disconnected=false;
   for(var i=0;i<256;i++)Write(0x10,(uint)i);Read(2);Check(Value()==0,"IFCNT wraps at 8 bits");
   return "VIRTUAL TMC GATEWAY TESTS PASS: "+checks;
  }
  private readonly VirtualMotorTmcGateway g;private int checks;
 }
}
