#!/usr/bin/env python3
"""Summarize observed integration evidence without claiming printer readiness."""
import argparse,json,re
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('logs',type=Path);a=p.parse_args()
s=(a.logs/'console.bin').read_text(errors='replace')
result={
 'main_mcu_identified':bool(re.search(r"MCU 'mcu' version:.*v1\.3\.3",s)),
 'nozzle_mcu_identified':bool(re.search(r"MCU 'nozzle_mcu' version:.*v1\.2\.9",s)),
 'clock_mismatch_reported':'Frequency mismatch' in s or 'frequency is out of range' in s,
 'startup_exception_reported':'Exception occurred during startup' in s,
 'main_config_commands_completed':'/ # echo MAIN_CONFIG_PROBE_DONE' in s,
 'combined_late_commands_completed':'/ # echo COMBINED_LATE_DONE' in s,
 'printer_ready_established':False,
 'tx_byte_counts':{name:(a.logs/name).stat().st_size for name in ['rv-tx.bin','mcu-tx.bin','rv-nozzle-tx.bin','nozzle-tx.bin'] if (a.logs/name).exists()},
 'note':'Identification and captured traffic do not establish motion, heating, clock synchronization, device accuracy, or printer readiness.'}
print(json.dumps(result,indent=2));(a.logs/'integration-result.json').write_text(json.dumps(result,indent=2)+'\n')
