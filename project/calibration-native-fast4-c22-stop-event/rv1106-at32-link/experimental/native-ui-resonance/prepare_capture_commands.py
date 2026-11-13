#!/usr/bin/env python3
"""Render passive monitor commands only. No emulator launch or execution."""
from pathlib import Path
import hashlib
import argparse,json,re

def commands(profile,run):
    shared=profile/'printer-shared-mcu/peripherals/PassiveGpioEdgeTrace.cs'
    budget=json.loads((profile/"rv1106-at32-link/experimental/native-ui-resonance/gpio-capture-budget.json").read_text())
    setup={};final=[]
    for board,spi_count in (('main',4),('nozzle',2),('motor',4)):
        lines=[f'include @{shared}'] if board=='main' else []
        for n in range(1,spi_count+1):
            name=f'spi{n}'
            lines.append(f'sysbus.{name} StartPassiveByteTrace "{run}/{board}-{name}-bytes.csv" 65536')
        # Each real modeled GPIO port has an independent bound. No CS guessed.
        for port in 'ABCDE':
            name=f'identificationGpio{port}'
            lines.append(f'machine LoadPlatformDescriptionFromString "{name}: PrinterShared.PassiveGpioEdgeTrace @ sysbus {{ maximumRows: 100000 }}"')
            for pin in range(16):
                lines.append(f'sysbus.{name} Observe sysbus.gpio{port} {pin} "{board}_P{port}{pin}"')
            limit=budget["ports"][f"{board}-gpio{port}-edges.csv"]
            lines.append(f'sysbus.{name} ConfigureLongRun {limit["maximum_rows"]} {limit["maximum_bytes"]}')
            lines.append(f'sysbus.{name} Start "{run}/{board}-gpio{port}-edges.csv"')
        setup[board]=lines
        final.append(f'mach set "{board}"')
        for n in range(1,spi_count+1):
            name=f'spi{n}'
            final.extend([f'echo "IDENT_SPI_{board}_{name}_BEGIN"',f'sysbus.{name} StopPassiveByteTrace']+[f'sysbus.{name} {field}' for field in ('PassiveTraceEnabled','PassiveRowsWritten','PassiveDroppedRows','PassiveCapacityReached','PassiveLastError')]+[f'echo "IDENT_SPI_{board}_{name}_END"'])
        for port in 'ABCDE':
            name=f'identificationGpio{port}'
            final.extend([f'echo "IDENT_GPIO_{board}_{port}_BEGIN"',f'sysbus.{name} Stop']+[f'sysbus.{name} {field}' for field in ('Enabled','RowsWritten','DroppedRows','CapacityReached','LastError')]+[f'echo "IDENT_GPIO_{board}_{port}_END"'])
            final.append(f'sysbus.{name} WriteStatus "{run}/{board}-gpio{port}-edges.csv.status.json"')
    final.append('mach set "main"')
    return {**setup,'final':final}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile',type=Path,required=True);p.add_argument('--run-name',required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',a.run_name):p.error('Invalid run name')
    profile=a.profile.resolve()
    if profile.name!='calibration-native-fast4-c22-stop-event':p.error('Only the separate c5 profile is accepted')
    if any(c.isspace() or c in '\"@' for c in str(profile)):p.error('Unsafe monitor path')
    a.output.mkdir(parents=True,exist_ok=False)
    rows=commands(profile,profile/'runs'/a.run_name)
    for name,lines in rows.items():(a.output/(name+'-passive.commands')).write_text('\n'.join(lines)+'\n')
    (a.output/'scope.json').write_text(json.dumps({'native_launch_performed':False,'sensor_attached':False,'bus_count':10,'gpio_ports':15,'gpio_pins':240,'spi_maximum_rows_per_bus':65536,'gpio_maximum_rows_per_port':3000000,'gpio_maximum_bytes_per_port':268435456,'pin_mapping_known':False,'setup_order':'Append main, nozzle, motor to existing corresponding cold setup files before firmware advances. Append final after the existing owner pauses globally.','scope':'Public logical SPI byte exchanges and resolved known modeled GPIO ports only. No memory read, register write, time advance, or response alteration.'},indent=2)+'\n')
    print(a.output)
if __name__=='__main__':main()
