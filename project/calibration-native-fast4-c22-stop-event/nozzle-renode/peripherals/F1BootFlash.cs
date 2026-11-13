// SPDX-License-Identifier: MIT
// Startup-facing F1-compatible flash registers. Exact physical device is unverified.
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;
namespace Antmicro.Renode.Peripherals.Nozzle
{
 [AllowedTranslations(AllowedTranslation.ByteToDoubleWord | AllowedTranslation.WordToDoubleWord)]
 public class F1BootFlash : IDoubleWordPeripheral, IKnownSize
 {
  public F1BootFlash() { Reset(); }
  public long Size => 0x400;
  public GPIO IRQ { get; } = new GPIO();
  public void Reset() { access=address=status=0;control=0x80;key=0;IRQ.Unset(); }
  public uint ReadDoubleWord(long o)
  { switch(o) {case 0:return access;case 4:case 8:return 0;case 12:return status;case 16:return control;case 20:return address;case 28:return 0x03FFFFFC;case 32:return 0xFFFFFFFF;default:this.LogUnhandledRead(o);return 0;} }
  public void WriteDoubleWord(long o,uint v)
  {
   switch(o)
   {
    case 0:access=v&0x1F;break;
    case 4:if(key==1&&v==0xCDEF89AB){control&=~0x80u;key=0;}else key=v==0x45670123?1:0;break;
    case 12:status&=~(v&0x34);break;
    case 16:
     if((control&0x80)!=0) {control|=v&0x80;break;}
     control=v;
     if((v&0x41)!=0){status|=4;control&=~0x40u;this.Log(LogLevel.Warning,"Nozzle flash program/erase unsupported; PRGMERR set");}break;
    case 20:address=v;break;
    default:this.LogUnhandledWrite(o,v);break;
   }
   IRQ.Set((status&0x14)!=0&&(control&0x400)!=0);
  }
  private uint access,address,status,control;private int key;
 }
}
