#!/usr/bin/env python3
"""Run the private emulator diagnostic; pass --execute to start processes."""
from pathlib import Path
import runpy,sys
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'tools/starter'))
sys.argv[1:1]=['--project',str(root/'project/calibration-native-fast4-c22-stop-event'),'--qemu-runtime',str(root/'runtime/qemu'),'--renode',str(root/'runtime/renode/renode'),'--network-helper',str(root/'tools/network/baseline_network.py')]
runpy.run_path(str(root/'tools/starter/start_diagnostic.py'),run_name='__main__')
