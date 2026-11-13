#!/usr/bin/env python3
"""Offline byte checks, original OID9/layout and static instruction-order evidence.
Reads original artifacts only; no emulator execution, RAM writes or live access.
"""
import hashlib,json,pathlib,re,struct
BASE=pathlib.Path(__file__).resolve().parent;ROOT=BASE.parents[2];OUT=BASE/'evidence';OUT.mkdir(exist_ok=True)
EXPECTED='ae09264667ff4a72905706026b1591bdede91e1f250755319fec531328e54e2f'
firmware=ROOT/'inputs/nozzle.bin';b=firmware.read_bytes();assert len(b)==37469 and hashlib.sha256(b).hexdigest()==EXPECTED
asm=ROOT/'evidence/z-probe-sensor-path/original-nozzle-sensor.asm'
lines=asm.read_text().splitlines();checked=0
for line in lines:
 m=re.match(r'^([0-9a-f]{8}) ([0-9a-f]+)\s',line)
 if not m:continue
 addr=int(m[1],16);raw=bytes.fromhex(m[2]);assert b[addr-0x08004000:addr-0x08004000+len(raw)]==raw,line;checked+=1
# Selected exact instructions from the verified image, including GPIO store helper.
required={0x800a394:'4022',0x800a39e:'fbf713f9',0x8009b42:'fb61',0x8009b46:'bc61',0x8009c30:'1a60',0x8009c40:'0b60',0x8009c50:'fb63',0x8009fa0:'fff77afc',0x80098cc:'2561',0x8009faa:'1370',0x8009fb4:'87f82540',0x8009fba:'3b62'}
for addr,raw in required.items():assert b[addr-0x8004000:addr-0x8004000+len(raw)//2].hex()==raw
ram_path=ROOT/'runs/native-xyz-synthetic-z-r1/final-nozzle-sram.bin';ram=ram_path.read_bytes();assert len(ram)==0x5000
u=lambda off:struct.unpack_from('<I',ram,off)[0]
table=u(0x74);count=ram[0x70];assert count>9 and table>=0x20000000 and table+8*count<=0x20005000
ctor=u(table-0x20000000+72);obj=u(table-0x20000000+76);assert ctor==0x0800a391 and obj==0x200006f0
for a,v in {0x1f4:0x40010800,0x1f8:0x80,0x1cc:0x40010800,0x1d0:0x40,0x1d4:0x40010800,0x1d8:0x40,0x1dc:0x40010800,0x1e0:0x20}.items():assert u(a)==v
fields={name:struct.unpack_from('<i',ram,obj-0x20000000+off)[0]for name,off in [('raw',0x18),('average',0x1c),('sensitivity',0x10),('filtered_difference',0x3c),('baseline',0x28),('stored_trigger_difference',0x20)]}
result={'firmware':str(firmware.relative_to(ROOT)),'firmware_sha256':EXPECTED,'firmware_length':len(b),'existing_disassembly_verified_instruction_rows':checked,'original_disassembly_sha256':hashlib.sha256(asm.read_bytes()).hexdigest(),'saved_sram_path':str(ram_path.relative_to(ROOT)),'saved_sram_sha256':hashlib.sha256(ram).hexdigest(),'saved_sram_scope':'Final archived snapshot only; not trigger-time evidence','oid9_constructor':hex(ctor),'oid9_object':hex(obj),'saved_final_fields':fields,'instruction_order':{'before_pa7_write':['average @08009b42','raw @08009b46','slow @08009c30','fast @08009c40','filtered difference @08009c50'],'pa7_high_call':'08009fa0 -> 08009898, resolved GPIO store at 080098cc','after_pa7_write':['trigger latch @08009faa','arm cleanup @08009fb4','stored trigger difference = baseline - raw @08009fba']},'limitations':['Rising edge +0x20 is prior stored trigger difference, not current trigger result.','Falling edge is later native state and not guaranteed filter state at prior rise.','No native runtime is executed by this verifier.']}
(OUT/'original-layout-verification.json').write_text(json.dumps(result,indent=2)+'\n')
# Retain byte-verifiable excerpts. The additional helper sequence is decoded below
# as explicit known ARMv7-M instructions; no dynamic execution hook is needed.
select=[]
for line in lines:
 m=re.match(r'^([0-9a-f]{8}) ',line)
 if m and any(lo<=int(m[1],16)<hi for lo,hi in [(0x800993e,0x800994c),(0x8009b42,0x8009b48),(0x8009c1a,0x8009c68),(0x8009f1a,0x8009f7a),(0x8009f98,0x8009fcc),(0x800a390,0x800a422)]):select.append(line)
helper=['080098be eff31086   mrs      r6, primask','080098c2 72b6       cpsid    i','080098c4 02b9       cbnz     r2, #0x80098c8','080098c6 2d04       lsls     r5, r5, #0x10','080098c8 0022       movs     r2, #0','080098ca 0121       movs     r1, #1','080098cc 2561       str      r5, [r4, #0x10]','080098ce fff7bbfe   bl       #0x8009648','080098d2 86f31088   msr      primask, r6','080098d6 02b0       add      sp, #8','080098d8 70bd       pop      {r4, r5, r6, pc}']
for line in helper:
 addr,raw=line.split()[:2];a=int(addr,16)-0x8004000;assert b[a:a+len(raw)//2].hex()==raw
(OUT/'verified-original-instruction-order.asm').write_text('; Original image SHA256 '+EXPECTED+'\n; All instruction bytes verified against inputs/nozzle.bin. No patch or execution.\n; Extra GPIO helper decoded with Capstone 5.0.9 Thumb + MCLASS.\n'+'\n'.join(helper+select)+'\n')
print(json.dumps(result,indent=2))
