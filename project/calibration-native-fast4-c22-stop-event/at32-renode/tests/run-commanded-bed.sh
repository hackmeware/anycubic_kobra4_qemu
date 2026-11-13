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
include @$ROOT/peripherals/AT32F403A_System.cs
include @$ROOT/peripherals/VirtualPrinterThermal.cs
mach create
machine LoadPlatformDescriptionFromString """gpioA: AT32.AT32GPIO @ sysbus 0x40010800
adc1: AT32.AT32ADC @ sysbus 0x40012400
"""
machine LoadPlatformDescription @$ROOT/platforms/virtual-bed-ntc.repl
machine LoadPlatformDescription @$ROOT/platforms/virtual-commanded-bed.repl
sysbus.gpioA WriteDoubleWord 0 0x44444441
sysbus.gpioA WriteDoubleWord 12 1
emulation RunFor "1.5"
sysbus.gpioA WriteDoubleWord 12 0
sysbus.virtualBedNTC TemperatureCelsius
sysbus.virtualBedNTC LastHeaterDuty
sysbus.virtualBedNTC SetSensorFault "open"
emulation RunFor "0.01"
sysbus.virtualBedNTC ADCValue
sysbus.virtualBedNTC LastHeaterDuty
quit
SCRIPT
"$RENODE" --disable-xwt --console "$SCRIPT" > "$ROOT/tests/results/commanded-bed.log" 2>&1
python3 - "$ROOT/tests/results/commanded-bed.log" <<'PY'
import re,sys,math
s=open(sys.argv[1]).read();s=re.sub(r'\x1b\[[0-9;]*m','',s)
nums=[int(v,16) if v.startswith('0x') else float(v) for v in re.findall(r'^(0x[0-9A-Fa-f]+|[0-9]+(?:\.[0-9]+)?)\s*$',s,re.M)]
assert len(nums)==4,nums
expected=25+(200/1.5)*(1-math.exp(-1.5*1.5/600))
assert abs(nums[0]-expected)<1e-8,(nums,expected)
assert nums[1:]==[1,4095,0],nums
print('COMMANDED BED WIRING PASS: GPIO heating, off transition, preserved open fault')
PY
