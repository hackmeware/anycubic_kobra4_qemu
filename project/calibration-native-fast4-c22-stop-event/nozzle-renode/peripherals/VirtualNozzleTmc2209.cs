// SPDX-License-Identifier: MIT
// External diagnostic TMC2209 UART device, not MCU firmware or a motion model.
using System;
using System.Collections.Generic;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;
namespace Antmicro.Renode.Peripherals.Nozzle
{
 public class VirtualNozzleTmc2209 : IDoubleWordPeripheral, IKnownSize, IGPIOReceiver
 {
  public VirtualNozzleTmc2209(IMachine machine, AT32.AT32GPIO port, int pin=3, uint baud=40000, byte address=0)
  {
   this.port=port;this.pin=pin;this.address=address;
   rx=new LimitTimer(machine.ClockSource,baud*2,this,"TMC RX sample",3,direction:Direction.Ascending,workMode:WorkMode.Periodic,enabled:false,eventEnabled:true);
   tx=new LimitTimer(machine.ClockSource,baud*2,this,"TMC TX bit",2,direction:Direction.Ascending,workMode:WorkMode.Periodic,enabled:false,eventEnabled:true);
   rx.LimitReached+=Sample;tx.LimitReached+=Transmit;Reset();
  }
  public long Size {get{return 0x20;}}
  public bool Disconnected {get;set;}
  public bool CorruptReplyCrc {get;set;}
  public uint DriverFaultStatus {get;set;}
  public uint Reads {get;private set;}
  public uint Writes {get;private set;}
  public uint RejectedFrames {get;private set;}
  public uint ReceivedBytes {get;private set;}
  public string LastRequest {get;private set;}
  public string LastReply {get;private set;}
  public void Reset()
  {
   rx.Reset();tx.Reset();rx.Enabled=tx.Enabled=false;input.Clear();output.Clear();registers.Clear();
   foreach(byte r in new byte[]{0,1,2,3,6,7,0x10,0x11,0x12,0x13,0x14,0x22,0x40,0x41,0x42,0x6a,0x6b,0x6c,0x6f,0x70,0x71,0x72}) registers[r]=0;
   registers[0x6f]=0x80000000; // standstill: no motion plant is attached
   registers[0]=0x101;registers[1]=1;registers[6]=0x21000000;registers[0x11]=20;registers[0x6c]=0x10000053;registers[0x70]=0xc10d0024;
   Reads=Writes=RejectedFrames=ReceivedBytes=0;LastRequest=LastReply="";line=true;driving=false;port.OnGPIO(pin,true);
  }
  public uint ReadDoubleWord(long offset){switch(offset){case 0:return Reads;case 4:return Writes;case 8:return RejectedFrames;case 12:return ReceivedBytes;default:return 0;}}
  public void WriteDoubleWord(long offset,uint value){}
  public void OnGPIO(int number,bool value)
  {
   var old=line;line=value;
   if(driving || rx.Enabled || !old || value) return;
   bit=0;current=0;rx.Limit=3;rx.Value=0;rx.Enabled=true;
  }
  private void Sample()
  {
   if(bit<8){if(line)current|=(byte)(1<<bit);bit++;rx.Limit=2;return;}
   rx.Enabled=false;
   if(!line){RejectedFrames++;input.Clear();return;}
   ReceiveByte(current);
  }
  public void ReceiveByte(byte value)
  {
   ReceivedBytes++;
   if(input.Count==0 && (value&15)!=5)return;
   input.Add(value);if(input.Count<3)return;
   var write=(input[2]&128)!=0;var count=write?8:4;
   if(input.Count<count)return;
   var request=input.ToArray();input.Clear();LastRequest=BitConverter.ToString(request);
   if(request[1]!=address || Crc8(request,count-1)!=request[count-1]){RejectedFrames++;return;}
   if(Disconnected)return;
   var reg=(byte)(request[2]&127);
   if(write)
   {
    if(!Writable(reg)){RejectedFrames++;return;}
    var v=(uint)request[3]<<24|(uint)request[4]<<16|(uint)request[5]<<8|request[6];
    if(reg==1)registers[1]&=~(v&7);else registers[reg]=v;
    registers[2]=(registers[2]+1)&255;Writes++;return; // silicon writes have no reply
   }
   uint result;if(!registers.TryGetValue(reg,out result)){RejectedFrames++;return;}
   if(reg==0x6f)result|=DriverFaultStatus;
   if(reg==1 && DriverFaultStatus!=0)result|=2;
   Reads++;
   var response=new byte[]{5,255,reg,(byte)(result>>24),(byte)(result>>16),(byte)(result>>8),(byte)result,0};
   response[7]=Crc8(response,7);if(CorruptReplyCrc)response[7]^=1;
   LastReply=BitConverter.ToString(response);
   foreach(var b in response){output.Enqueue(false);for(var i=0;i<8;i++)output.Enqueue((b&(1<<i))!=0);output.Enqueue(true);}
   tx.Limit=16+((registers[3]>>8)&15)*16;tx.Value=0;tx.Enabled=true;
  }
  private void Transmit()
  {
   if(output.Count==0){tx.Enabled=false;driving=false;port.OnGPIO(pin,true);return;}
   driving=true;port.OnGPIO(pin,output.Dequeue());tx.Limit=2;
  }
  public void InjectGeneralStatus(uint bits){registers[1]|=bits&7;}
  private static bool Writable(byte r){switch(r){case 0:case 1:case 3:case 7:case 0x10:case 0x11:case 0x13:case 0x14:case 0x22:case 0x40:case 0x42:case 0x6c:case 0x70:return true;default:return false;}}
  public static byte Crc8(byte[] data,int count){byte crc=0;for(var i=0;i<count;i++){var b=data[i];for(var j=0;j<8;j++){crc=(byte)(((crc>>7)^(b&1))!=0?(crc<<1)^7:crc<<1);b>>=1;}}return crc;}
  private readonly AT32.AT32GPIO port;private readonly int pin;private readonly byte address;
  private readonly LimitTimer rx,tx;private bool line,driving;private byte current;private int bit;
  private readonly List<byte> input=new List<byte>();private readonly Queue<bool> output=new Queue<bool>();
  private readonly Dictionary<byte,uint> registers=new Dictionary<byte,uint>();
 }
}
