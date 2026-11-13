# Preserved console-corruption regression

`status019-raw-dump-region.txt` is an exact byte copy of
`runs/native-nozzle-230-synthetic-r3/safe-stop-r3/status019-raw-dump-region.txt`.
The original run and safe-stop artifacts have not been edited.

SHA256: `b7951d3fab4e0d15afc9547d37ee4f441397bad4596ce02d414b86e92fe6b9fa`.

The first octal address was contaminated by the echoed ELF-upload command from
an externally appended normal-zero batch while the status capture was pending.
The original strict parser correctly rejected the resulting noncontiguous dump.
Unique guest executable names did not prevent shared-TTY echo interference.

`test_control_safety.py` checks both source and copied fixture against this fixed
hash and requires the strict rejection to remain in place. Its other regressions
use mocked launchers, quarter-second clock increments, synthetic thermal test
vectors and multi-poll RPC/log output. They never start firmware, a native client,
an emulator, a socket or a real thermal model. Mock success is orchestration
evidence only, not a native-run or physical-safety claim.

Run from the snapshot root:

```sh
python3 -B -m unittest discover \
  -s printer-shared-mcu/experimental/synthetic-calibration-thermal/native-controller \
  -p test_control_safety.py -v
```
