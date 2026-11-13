from pathlib import Path
root=Path(__file__).resolve().parents[2];pkg=root/'printer-shared-mcu'
for quantum in ['default','10us']:
 base=(pkg/'generated/shared-load.resc').read_text()
 if quantum=='default':base='\n'.join(line for line in base.splitlines() if 'SetGlobalQuantum' not in line)+'\n'
 boot=pkg/'tests'/f'rx-bootstrap-{quantum}.resc';boot.write_text(base)
 s=f'include @{boot}\n'
 if quantum!='default':s+='emulation SetGlobalQuantum "0.00001"\n'
 for board in ['main','motor','nozzle']:
  s+=f'mach set "{board}"\nsysbus LoadBinary @{root}/at32-renode/tests/serial-wire-test.bin 0x08000000\ncpu VectorTableOffset 0x08000000\n'
 s+='mach set "main"\nmachine LoadPlatformDescriptionFromString "serialWire: PrinterMain.AT32VirtualSerialWire @ sysbus { uart: usart1; baud: 576000 }"\nemulation RunFor "0.001"\n'
 for b in range(64):s+=f'sysbus.serialWire WriteChar {b}\n'
 s+='emulation RunFor "0.005"\nlog "RX_COUNT"\nsysbus ReadDoubleWord 0x20000100\nlog "RX_STATUS"\nsysbus ReadDoubleWord 0x40013800\nlog "WIRE_COUNT"\nsysbus.serialWire DeliveredBytes\nlog "RX BURST COMPLETE"\nquit\n'
 (pkg/'tests'/f'rx-{quantum}.resc').write_text(s)
