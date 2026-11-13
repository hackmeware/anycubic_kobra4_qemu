#!/usr/bin/env python3
"""Isolated explicit fixture bootstrap: no MCU peers or native applications."""
import json,os,pathlib,subprocess,sys,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'rv1106-at32-link/scripts'))
from clock_fixture_runner import bootstrap_native_clock
if sys.argv[1:]!=['--enable-diagnostic-instrumentation']:
    raise SystemExit('Pass --enable-diagnostic-instrumentation for emulator-only timer fixture')
with tempfile.TemporaryDirectory() as folder:
    tmp=pathlib.Path(folder);base=tmp/'qmp'
    for suffix in ('.in','.out'):os.mkfifo(str(base)+suffix)
    with (tmp/'console.bin').open('wb') as out,(tmp/'qemu.log').open('wb') as err:
        process=subprocess.Popen([str(ROOT/'rv1106-qemu/bin/qemu-system-arm-display'),'-M','rv1106','-m','128M',
            '-cpu','cortex-a7,has_el3=off','-display','none','-monitor','none','-serial','stdio',
            '-qmp',f'pipe:{base}','-kernel',str(ROOT/'rv1106-linux-display-128diag/linux-test.elf'),
            '-drive',f'if=sd,index=0,file={ROOT}/inputs/offline-emmc.img,format=raw,snapshot=on'],
            stdin=subprocess.PIPE,stdout=out,stderr=err)
        client=None
        try:
            client=bootstrap_native_clock(base,tmp/'console.bin',process,'RV1106_OFFLINE_USERSPACE_READY')
            measured=client.now()
            assert measured>0
            assert client.call('query-status')['status']=='paused'
            print(json.dumps({'result':'RUNNER BOOTSTRAP PASS','native_apps_started':False,'measured_virtual_ns':measured}))
        finally:
            if client:client.close()
            process.terminate();process.wait(timeout=5)
