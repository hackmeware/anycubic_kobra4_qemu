#!/usr/bin/env python3
"""Verify embedded curve and C# expectations against the preserved native evidence."""
import hashlib
import json
import math
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
evidence = root / "evidence/recovered-nozzle-thermal/nozzle-thermal-recovered-evidence.json"
assert hashlib.sha256(evidence.read_bytes()).hexdigest() == "053b132399301dee0a8094caaeb27ab4649ba0e55a21e419e28e5b9a03ad1f46"
data = json.loads(evidence.read_text())
source = (root / "nozzle-renode/peripherals/VirtualPrinterThermal.cs").read_text()

def matrix(text, name):
    match = re.search(r"\b" + name + r"\s*=\s*new double\[,]\s*\{(.*?)\n\s*\};", text, re.S)
    assert match, name
    return [[float(v.strip()) for v in row.split(",")] for row in re.findall(r"\{\s*([^{}]+?)\s*\}", match[1])]

points = data["sensor"]["lookup_table"]
segments = data["live_converter"]["segments"]
assert matrix(source, "RecoveredNozzleTable") == [[p["temperature_celsius"], p["resistance_ohms"]] for p in points]
assert matrix(source, "RecoveredNozzleSegments") == [[s[k] for k in ("resistance_upper_breakpoint_ohms", "temperature_per_ohm", "temperature_intercept_celsius")] for s in segments]
temperatures = set(range(-40, 361))
temperatures.update(p["temperature_celsius"] for p in points)
temperatures.update((a["temperature_celsius"] + b["temperature_celsius"]) / 2 for a, b in zip(points, points[1:]))
expected = []
for t in sorted(temperatures):
    for segment in segments:
        bound, slope, intercept = (segment[k] for k in ("resistance_upper_breakpoint_ohms", "temperature_per_ohm", "temperature_intercept_celsius"))
        if t < bound * slope + intercept:
            continue
        resistance = (t - intercept) / slope
        expected.append([t, math.floor(4095 * resistance / (4700 + resistance) + 0.5)])
        break
    else:
        raise AssertionError(t)
fixtures = (root / "nozzle-renode/tests/RecoveredNozzleCurveVectors.cs").read_text()
assert matrix(fixtures, "Samples") == expected
profile = (root / "nozzle-renode/platforms/virtual-nozzle-recovered-ntc.repl").read_text()
assert "useRecoveredNozzleCurve: true" in profile and "pullResistanceOhms: 4700" in profile
assert "->" not in profile, "optional profile must not bind heater/fan"
old_profile = (root / "nozzle-renode/platforms/virtual-nozzle-ntc.repl").read_text()
assert "useRecoveredNozzleCurve" not in old_profile and "betaKelvin: 3950" in old_profile
print(f"RECOVERED NOZZLE DATA PASS: {len(points)} points, {len(segments)} native segments, {len(expected)} C# vectors; default and disconnected profile checks passed")
