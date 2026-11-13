#!/usr/bin/env python3
"""Prepare privately supplied firmware; no firmware included in this package."""
from pathlib import Path
import runpy,sys
root=Path(__file__).resolve().parent/'tools/swu'
sys.path.insert(0,str(root))
runpy.run_path(str(root/'prepare_swu.py'),run_name='__main__')
