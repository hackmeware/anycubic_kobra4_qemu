#!/usr/bin/env python3
"""Real-emulator integration checks, including a deliberately wrong response."""
import pathlib, subprocess, sys, tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
launcher=[sys.executable,str(ROOT/'scripts/run_link.py'),'--test','--timeout','15']
subprocess.run([sys.executable,str(ROOT/'firmware/make_test.py')],check=True)
for n in range(2):
    subprocess.run(launcher+['--log-dir',str(ROOT/f'test-results/roundtrip-{n+1}')],check=True)
    log=ROOT/f'test-results/roundtrip-{n+1}'
    assert (log/'rv-tx.bin').read_bytes()==bytes(range(256))
    assert (log/'mcu-tx.bin').read_bytes()==bytes(x^0x5a for x in range(256))
subprocess.run(launcher+['--pace-rv-byte','0.005','--log-dir',str(ROOT/'test-results/paced-roundtrip')],check=True)
with tempfile.TemporaryDirectory(prefix='uart-negative-') as tmp:
    data=(ROOT/'firmware/at32-test.bin').read_bytes()
    # Last literal is the independent MCU reply transformation constant.
    assert data[-4:]==b'\x5a\x00\x00\x00'
    wrong=pathlib.Path(tmp)/'wrong.bin';wrong.write_bytes(data[:-4]+b'\x5b\x00\x00\x00')
    result=subprocess.run(launcher+['--mcu-image',str(wrong),'--log-dir',str(ROOT/'test-results/wrong-response')],capture_output=True,text=True)
    console=(ROOT/'test-results/wrong-response/console.bin').read_bytes()
    assert result.returncode!=0 and b'FAIL: UART response mismatch' in console,(result,console)
    print('PASS: deliberately wrong MCU response is rejected')
print('PASS: UART integration checks (two direct 256-byte round trips, one paced round trip, one negative control)')
