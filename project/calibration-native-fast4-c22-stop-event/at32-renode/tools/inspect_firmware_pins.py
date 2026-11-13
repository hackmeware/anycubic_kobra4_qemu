#!/usr/bin/env python3
"""Read-only reproduction of known firmware's pin-capability table. No flashing or control."""
import argparse,hashlib,json,struct
from pathlib import Path
EXPECTED='9bd702c8a076f29c0ac019cc7c8ea6c7afa52d13580fea04e977e3dce0a5d517'
BASE=0x08004000
p=argparse.ArgumentParser(description=__doc__);p.add_argument('firmware',type=Path);a=p.parse_args()
b=a.firmware.read_bytes(); digest=hashlib.sha256(b).hexdigest()
if digest!=EXPECTED: raise SystemExit('Different firmware hash: offsets below are not validated for this image. No mappings emitted.')
def block(addr,size):return b[addr-BASE:addr-BASE+size]
# Literal references and table contents validated against Thumb disassembly.
assert struct.unpack('<I',block(0x080065EC,4))[0]==0x0800CD14
assert block(0x0800652A,2)==bytes.fromhex('4068') # ldr r0,[r0,#4], requested pin argument
assert block(0x08006566,4)==bytes.fromhex('c0e90824') # store ADC base + selected index
assert block(0x0800CD14,17)==bytes.fromhex('00 01 02 03 04 05 06 07 10 11 20 21 22 23 24 25 fe')
entries=[]
for channel,pin in enumerate(block(0x0800CD14,17)):
 entries.append({'encoded_pin':pin,'pin':f'P{chr(65+(pin>>4))}{pin&15}' if pin!=254 else 'internal_temperature','adc':'ADC1','channel':channel,'role':'capability only; no heater/bed assignment'})
print(json.dumps({'firmware_sha256':digest,'load_base':hex(BASE),'table_address':'0x0800CD14','adc_config_handler':'0x08006520','pin_encoding':'high nibble port, low nibble pin','adc_capabilities':entries,'fixed_startup_outputs':[{'pin':'PB7','level':1,'meaning':'unknown'},{'pin':'PA8','level':1,'meaning':'unknown'}],'fixed_uarts':{'USART1':{'tx':'PA9','rx':'PA10'},'USART2':{'tx':'PA2','rx':'PA3'}},'automatic_sensor_bindings':[]},indent=2))
