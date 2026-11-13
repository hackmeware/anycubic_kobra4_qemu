#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
RUNTIME=${RENODE_RUNTIME:-"$ROOT/../at32-runtime"}
RENODE=${RENODE:-"$RUNTIME/run-renode"}
mkdir -p "$ROOT/tests/results"
SCRIPT=$(mktemp --suffix=.resc)
trap 'rm -f "$SCRIPT"' EXIT
cat > "$SCRIPT" <<SCRIPT
include @$ROOT/peripherals/AT32F403A_IO.cs
include @$ROOT/peripherals/VirtualGPIOTrace.cs
mach create
machine LoadPlatformDescriptionFromString """gpioA: AT32.AT32GPIO @ sysbus 0x40010800
gpioB: AT32.AT32GPIO @ sysbus 0x40010c00
trace1: AT32.VirtualGPIOTrace @ sysbus
    portA: gpioA
    portB: gpioB
trace2: AT32.VirtualGPIOTrace @ sysbus
    portA: gpioA
    portB: gpioB
"""
sysbus.gpioA WriteDoubleWord 0 0x44444443
sysbus.gpioA WriteDoubleWord 12 1
emulation RunFor "0.0025"
sysbus.gpioA WriteDoubleWord 12 0
sysbus.trace1 Mark "after_pulse"
sysbus.trace1 WriteCsv @$ROOT/tests/results/gpio-trace1.csv
sysbus.trace2 WriteCsv @$ROOT/tests/results/gpio-trace2.csv
quit
SCRIPT
"$RENODE" --disable-xwt --console "$SCRIPT" > "$ROOT/tests/results/gpio-trace.log" 2>&1
python3 - "$ROOT/tests/results" <<'PY'
import csv, pathlib, sys
root=pathlib.Path(sys.argv[1])
for i in [1,2]:
    rows=list(csv.DictReader((root/f'gpio-trace{i}.csv').open()))
    edges=[r for r in rows if r['event']=='edge']
    assert edges == [dict(time_us='0',pin='PA0',level='1',configuration_nibble='3',output_latch='1',event='edge'),dict(time_us='2500',pin='PA0',level='0',configuration_nibble='3',output_latch='0',event='edge')], edges
    assert len([r for r in rows if r['event']=='snapshot:trace_attached'])==32
    if i==1:
        assert len([r for r in rows if r['event']=='snapshot:after_pulse' and r['time_us']=='2500'])==32
print('VIRTUAL GPIO TRACE PASS: timestamps, configuration, snapshots, and simultaneous sinks')
PY
