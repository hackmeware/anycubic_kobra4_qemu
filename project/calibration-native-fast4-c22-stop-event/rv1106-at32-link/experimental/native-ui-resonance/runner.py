#!/usr/bin/env python3
"""Fixed bounded supervision for cold UI resonance identification only.

Use this experiment's outer_guard.py. Host progress is evidence only, not a
resumable snapshot. The fixed 45-second shared-time threshold actively requests stop when sampled
by the unchanged supervisor, not as a strict pre-step cap; no timing/stepping semantics are changed here.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import threading
import time
import types

HERE = Path(__file__).resolve().parent
EXPECTED_PROFILE = HERE.parents[2]
OBSERVER_RELATIVE = 'rv1106-at32-link/experimental/native-ui-resonance/observer.py'
# Intentionally unlaunchable until the final observer is reviewed and pinned.
OBSERVER_SHA256 = 'bcbd9fa184c79b5b3d399882b0eb23c04e3f1d8d03e9ea44093a95bd52fa8013'
PROTOCOL_RELATIVE = 'rv1106-at32-link/experimental/native-homing-completion/protocol.py'
VALIDATOR_RELATIVE = 'rv1106-at32-link/experimental/native-homing-completion/observer.py'
VALIDATOR_SHA256 = 'f559bc324775f03e4610a7488538ef00a66191edcd86a2d42f4ad91945147e75'
PROTOCOL_SHA256 = '5dd5eb50d6e95ce8d8a3cdde13efd4b8d08f27e45a1cadc09b4500857ecab7d6'
MANIFEST_RELATIVE = 'rv1106-at32-link/experimental/native-ui-resonance/execution-manifest.json'
MANIFEST_SHA256 = '764bc5b10df96e6c9e8471649939a435415d6ce8293ce4ab96aa8ff62cf8a423'
MANIFEST_SCOPE = 'native-ui-resonance-execution-source-closure'
READY_REFERENCE_RELATIVE = 'rv1106-at32-link/experimental/sensor30-observation/evidence/ready-baseline.console.txt'
LAUNCHER_RELATIVE = 'rv1106-at32-link/experimental/native-ui-resonance/run_ui_fixture.sh'
PINNED_CONTROLS = {
    'rv1106-at32-link/experimental/native-ui-resonance/guest_startup_encoding.py': '6384232d3e110decf95bfeae8ec7b01ff6dfcee92e7f8e0851a7183c862e6c8f',
    'rv1106-at32-link/experimental/native-ui-resonance/exact_trace_cache.py': '1c357a3b6d212acf52585ab945ab0ad48ef095bc4169569b5167efb5bcc7b8d2',
    'rv1106-at32-link/scripts/z_probe_selection.py': 'e91773e40758f698e5a1ccf81e5d7d4d8d2d7267af23306da436f6e708a95a2d',
    'rv1106-at32-link/experimental/native-ui-resonance/run_ui_fixture.sh': '929527ed62a6278321711a567d7ca381329f88fef19c14f920ccae4f35d150cc',
    'rv1106-at32-link/experimental/native-ui-resonance/native-ui-startup.commands': '22bd4303c6978e6f75ac8dfcee899a8a87225265d2464bc82b465df23ffdef18',
    'rv1106-at32-link/experimental/native-ui-resonance/prepare_capture_commands.py': '69467ccea17d8b9c1d466509dc1e6ddd7b6b7f8e44b40162a36b44ce095ca02f',
    'rv1106-at32-link/experimental/native-homing-completion/physical.py': '7cc99dc7145247cce883b4a8880f2e2aa19bca38f3817b2c83192c1691a707a2',
    'rv1106-at32-link/experimental/sensor30-observation/observer.py': '04311b970f4f1d250cb4d7ac2cc340275a616f1568a7ace9e81108d0d0723db9',
    'rv1106-at32-link/experimental/sensor30-observation/protocol.py': '306495b2a0f714d9114b5c5cd454ef7a5535b6515e5574ec2826965a71893d73',
    'rv1106-at32-link/scripts/bounded_native_supervisor.py': '48abc81b323217ecf6811dec29c865b6b9bf87f470f7c4ec24bae3bd597f4ca7',
    'rv1106-at32-link/scripts/run_native_ready_observation.py': '59d018994fe46282ade656f6e144ece30caf718e427c1bd99ad4f0d7f409b510',
    'rv1106-at32-link/scripts/run_native_event_fixture.sh': 'ff22ddc0992c618c67c88667f3c7acdb20e572e0eaac13679811c10ba8344913',
    'rv1106-at32-link/scripts/run_link.py': '4ca68e99a3aeb8bbf2278f3f1fa40ad7c8bd3eac4190f89bdd9395e2b6da4db7',
    'rv1106-at32-link/experimental/bootstrap-boundaries/outer_guard.py': 'd2f1eb705e1b11311223c3584d578ced1963d2e11de2148306315952a81c1348',
    'rv1106-at32-link/experimental/clock-snapshot/runtime/run-baseline': 'b5c7bb59304db4082d491b9008392c3e5f2af98bab38cb1901831d9e36ecbcd1',
    'rv1106-at32-link/scripts/final_export.py': 'da0ad5431bcc85efe75cdd1d524930581aa4769e17f10420e8c6c324b9c560fa',
    'rv1106-at32-link/experimental/native-ui-resonance/initial_response.py': '2a27d62e88090bb6f7be96f5548019df9efb44b71432c7e44ef7e60d21ba7e41',
    'rv1106-at32-link/experimental/native-ui-resonance/thermal_checkpoint.py': '33d176bacc0c12c3bf916ca55fcc7452beb04320cb7a7ef8d63cbb9815f12573',
    'rv1106-at32-link/experimental/native-ui-resonance/canonical-thermal-profile.json': '4f24b723e18e0c7165731a2df1ee7685a175707b4f030198d376873e5dbf9b6f',
    'rv1106-at32-link/scripts/pid_thermal_profile_selection.py': '457499611c10968356fe025b830798d9361007f50b2aeff90785189539da650d',
    'rv1106-at32-link/scripts/shared_mcu.py': '23cecaaeccaf09efa3b4f41570a50719e8b8c7b12a4d22b7fd414ec7a3eb0c36',
    'rv1106-at32-link/scripts/thermal-pid-contract/source-pins.json': 'bdc41ed66a3513bc3ce166057464f7857c12d12be00eada25cab843eb88043aa',
    'rv1106-at32-link/scripts/thermal-pid-contract/templates/main-final.commands': 'ad283e34d28f529b9ac8928d1577e6fd31484471e0094d26033ef0bd221dcea7',
    'rv1106-at32-link/scripts/thermal-pid-contract/templates/main-setup.commands': 'db20543ae98c2ee97391b75fcd000f13483ab44d6a94c096747ae5eda455d112',
    'rv1106-at32-link/scripts/thermal-pid-contract/templates/motor-setup.commands': 'ad587c91f3111b21303914c1a1a3bf6de0cb6c28d93275a5f98e35177dd9fd34',
    'rv1106-at32-link/scripts/thermal-pid-contract/templates/nozzle-final.commands': '591de3c0313a6dedad9fea231df248500fac73d6b83bd243cd2258f7d21afa8b',
    'rv1106-at32-link/scripts/thermal-pid-contract/templates/nozzle-setup.commands': '103c55a4556e204e9c4a1182c19b77693ca01ccaa2b77b0cc141f1d78797b5db',
    'build-deps/pkgconfig/gio-2.0.pc': '2fcf79c860b31b896d4b8a5e94791317a055bac115cb2a8e633113cd0ff8e2c7',
    'build-deps/pkgconfig/gio-unix-2.0.pc': '58e7ffdbef83b9c23c92201742e605e52193f3f8a7b1527be4bc2d51cf28b74f',
    'build-deps/pkgconfig/glib-2.0.pc': '1e30ecf4649b6937be0d646f79817c9dc12773229626935e32cc06a3c344a7a0',
    'build-deps/pkgconfig/gmodule-2.0.pc': 'b7715cad792c4b2bbed9e7bdeae461859e102e74fbc676e5d88c313c4605bdad',
    'build-deps/pkgconfig/gmodule-export-2.0.pc': 'b7715cad792c4b2bbed9e7bdeae461859e102e74fbc676e5d88c313c4605bdad',
    'build-deps/pkgconfig/gmodule-no-export-2.0.pc': '17ea90d57058a6d8e15462149765633355fbbb370ad58be535b9a5e7ef8a46e7',
    'build-deps/pkgconfig/gobject-2.0.pc': '1292bfec17ef34b93de9af7c5cfd3e7d2743984e905087ee928be23dd0630b83',
    'build-deps/pkgconfig/gthread-2.0.pc': '17a98dccfef5c27828a967e108050e6646db2109595681b4cd648451b42f41fa',
    'build-deps/pkgconfig/libffi.pc': 'c6cbe538f1746e6bd285db14fa229ca3b81c5ebe922d0c8a36f3dd2913bb5a2b',
    'build-deps/pkgconfig/libpcre2-16.pc': 'b9c495f95019f2193375487a613914dc4a0e1992d78aefca8542f97ecb4d6af6',
    'build-deps/pkgconfig/libpcre2-32.pc': '2452bfaa689cef304b41952952923a8271e994f00631107a2c8137d994db7d39',
    'build-deps/pkgconfig/libpcre2-8.pc': 'eabb5bb8077a0d5514165288781f5c907dd45ccf6b35a38b7d1df1fd02daaf98',
    'build-deps/pkgconfig/libpcre2-posix.pc': '6353f7a076b63d8112b11aec12bb115f2ff0187021ca0aedc053353e495f676e',
    'build-deps/pkgconfig/slirp.pc': '21ad04e8ed84dca12e81705174cccf5904944382d74a2b56b06b1ac56afaf2e4',
    'build-deps/pkgconfig/sysprof-capture-4.pc': '46aadf81fd5dd24f0d3f3f9d3dd5c3d245cc53cae45f65de13237e8cd9deecfd',
    'build-deps/pkgconfig/zlib.pc': 'dd274a98a8b77cd088937c3dd8e28927d893b397df391a183206ad52e0d996cf',
    'motor-renode/peripherals/PassivePhysicalStateTrace.cs': '587cb7e27c769dd26448325a84255cd65d9505d0c1f6fcb57a7c736b2e70677a',
    'nozzle-renode/experimental/cs1237-functional/Cs1237FunctionalAdapter.cs': '00622cb3e8cb697191661a1238f889cde597438326e1a213464450811b75f120',
    'printer-shared-mcu/peripherals/PassiveGpioEdgeTrace.cs': '89c9cb03aec7e037474eb5a81cf9562d78593cbe237d82252d818af05f2c9b60',
    'rv1106-at32-link/experimental/native-ui-resonance/checkpoint_run.py': '83b86540de7bfdd826dacd95350d7ec1c22d16734f2b12550fb321e5db9ec9a4',
    'rv1106-at32-link/experimental/native-ui-resonance/final_capture.py': 'caf3762a807dd01d1d5fafb81706f588f184372d2f42d1f9916bcb8930687406',
    'rv1106-at32-link/experimental/native-ui-resonance/gpio-capture-budget.json': 'b752b5db9dd2673681ba228993c7010038f5405ed8acf46825616609e02d3c6b',
    'rv1106-at32-link/experimental/native-ui-resonance/gpio_capture.py': '3948ca7c3e98ea79beed2788f1b8f24abaa4f24026f365482c802775cca7284e',
    'rv1106-at32-link/experimental/native-ui-resonance/job_resources.py': '80e2f44951369747f2c890f0a30b872d02e42dcbae83b9e54a2ee689ce504cb6',
    'rv1106-at32-link/experimental/native-ui-resonance/native_progress.py': '8cba197eb17932849804eea07ceb51655f65f0d19abdd4ecf64895590ba1cdd8',
    'rv1106-at32-link/experimental/native-ui-resonance/observer.py': 'bcbd9fa184c79b5b3d399882b0eb23c04e3f1d8d03e9ea44093a95bd52fa8013',
    'rv1106-at32-link/scripts/native-long-contract/source-delta.json': '3b4bb03ba25481c5f9bde58a380b0f797ec41ba576d1a75072fa64bbe0731fa0',
    'rv1106-at32-link/scripts/native-long-contract/source-pins.json': '5d5c60eab58b0a6d23ea7b75dcc3f1e5d2dc990ed8cf181149decb8598bf4e46',
    'rv1106-at32-link/scripts/native-long-contract/templates/main-final.commands': '7b1118be393f4b51df0d62f1cddea7e156e8a44ca5b93525a4926b06fb5e5914',
    'rv1106-at32-link/scripts/native-long-contract/templates/main-setup.commands': 'a9cdb4020414c50dd09a9d0d466c6e1aac5cb4647318dcda0057272c37750b50',
    'rv1106-at32-link/scripts/native-long-contract/templates/motor-setup.commands': '1340571357a0885c8ea04c5daa79786f676a169484f51cc4d34726950d6dfcba',
    'rv1106-at32-link/scripts/native-long-contract/templates/nozzle-final.commands': '591de3c0313a6dedad9fea231df248500fac73d6b83bd243cd2258f7d21afa8b',
    'rv1106-at32-link/scripts/native-long-contract/templates/nozzle-setup.commands': 'a0a53e1b865bbb05d0d78fe8ceb63603e09f4e1002446b4fa0d09da566747db4',
    'rv1106-at32-link/scripts/run_link.py.orig': 'd75946efdec50c404b0a3bb5c93edbe72f133a9a5248d8fed23f77b08740dc29',
    'rv1106-at32-link/scripts/lockstep_coordinator.py': '43bbfb8eb8b05f7e25e38906f8a6ee0f262cea9aa3d4c300853e8b7578186257',
    'printer-shared-mcu/experimental/synthetic-cartridge-4x/nozzle.repl': 'cb02ed565f21af7f722c71b34ae123bf754f153bd2585619eb6d1d15ff2acd11',
    'printer-shared-mcu/experimental/synthetic-cartridge-4x/parameters.json': '81e2f761874e8e59826f18451fcfc71c4ca67ae08e42fa28e8e810dcee2ac8bb',
    'rv1106-at32-link/scripts/cartridge_thermal_profile_selection.py': '776524fd5c8ad2b4a6a96537bf11ab2f793afcca1070e7408d8700f332827faa',
    'printer-shared-mcu/experimental/native-dual-lis/DualBoardSensorBinding.cs': '2f35d21af06bd209ffddf623cda715ca9997ce470f0b46f05d1da42e6ecdda17',
    'printer-shared-mcu/experimental/native-dual-lis/MECHANICAL-HYPOTHESIS.json': 'decb3c2c430cc29a9080bdec281dcb79fbc1e31fa4c6bbc418d5627b3933e186',
    'printer-shared-mcu/experimental/native-dual-lis/NativeDualSensorAttachment.cs': '56451645a07f2bc98b6495be23834401ed91bbf4eeb42552c3f5bac68c73b158',
    'printer-shared-mcu/experimental/native-dual-lis/PublishedSnapshotAccelerationInput.cs': '0e24352f6d04d3d9c1d4204be3866923bd43d86521ce46a8288a63dbf91ead86',
    'printer-shared-mcu/experimental/native-dual-lis/RigidTranslationConfiguration.cs': '8dae728213dbf56256ae3ba660c4d07ca3a744da21c80875ba793fab7fdc02f0',
    'printer-shared-mcu/experimental/native-dual-lis/SOURCE-PINS.json': '5ae5097704460d59e92b39836cd809e5f2e6620224c7a82052e38a96172318da',
    'printer-shared-mcu/experimental/native-dual-lis/TimedLis2dw12CrossBoard.cs': '32d268d4a3cbbc8305a48e4a2a74ba08a9d17c38e27ac1525c6e0300abc2cce0',
    'printer-shared-mcu/experimental/native-dual-lis/Tmr8PublicSnapshotPublisher.cs': 'be86d307b155dde21ec95f9c8ff4913e08fb6eef8c3c4e52bc8a41c14eca959f',
    'printer-shared-mcu/experimental/native-dual-lis/main/AT32F403A_IO.cs': '81dbd0ddf33d8094912fb310fb8c724b100a803e0f454df4394171d53331459b',
    'printer-shared-mcu/experimental/native-dual-lis/main/GpioMode3Lis2dw12Bridge.cs': 'c3ede1eef58e6090dedeae67673068800c6a628e54a557ec702c4b5ed87f80bf',
    'printer-shared-mcu/experimental/native-dual-lis/nozzle/AT32F403A_IO.cs': 'af51f5d33a585689682ddda8acd8dfe5de5a140bfa5dd1b584b0b106bdd7933e',
    'printer-shared-mcu/experimental/native-dual-lis/nozzle/GpioMode3Lis2dw12Bridge.cs': '7f3cd4e1eeac5eb8cb84309f34ac882ca76ef86d09f1a2abfdeaafc49fae5671',
    'rv1106-at32-link/experimental/native-ui-resonance/sensor_status.py': 'a7227dc3ac258c0e09ee5ef15d2ca0f455636c1739b53959a639e879c81d9a22',
    'rv1106-at32-link/experimental/native-ui-resonance/wlan_stream_review.py': '0e6cca8f19b856f415ed2052d2ffd24a44f58559600ae1cbca6c973ec6f974ee',
    'rv1106-at32-link/scripts/native_dual_lis_selection.py': '486fe7f9c7a47f0599ee2ffc2ffe3ab4c096a8c7fad82ab06bed3b9799056ed5',
    'printer-shared-mcu/experimental/synthetic-cartridge-4x/bed.repl': 'e256be189e00703d74af0824833a7676f0304ee62e3af1a06083bf7fed79a9a4',
    'rv1106-at32-link/scripts/thermal_profile_selection.py': 'd925e594ece01593676d44eb12dcecfcfc4f9162eaa3bda76a8ff975dcb4d95c',
    'rv1106-at32-link/experimental/native-ui-resonance/echo_review.py': '67a3e6b6ff6b9dfd000c708e3094b67bb05331b2c57e27afcd848c27dd42c062',
    'rv1106-at32-link/experimental/native-ui-resonance/native-ui-startup-gate.sh': '4ab69e0bf0648b845a696970f61c4f9690ecec61cda2e41f8d4bc1e275c717b3',
    'rv1106-at32-link/experimental/native-ui-resonance/startup_readiness.py': '2ea0cc41c5416821cdb7da076a6084a80a8aee9821a87055232b991d3a24b2e0',
    'rv1106-at32-link/experimental/native-ui-resonance/test_observer.py': '0706c46bc29aab56d91d415d1901c3b73f919f22f2efde745672914ed328b81e',
    'build-deps/root/usr/lib/python3/dist-packages/mesonbuild/compilers/c.py': '239b8b78cec8b3c23dae477362bdda93e2f05ed9f894608b7d7525363a29a5da',
}
TOTAL_SECONDS = 86380
GRACE_SECONDS = 8
TERM_SECONDS = 2
KILL_SECONDS = 2
ACTIVE_SECONDS = TOTAL_SECONDS - GRACE_SECONDS - TERM_SECONDS - KILL_SECONDS
OUTER_SECONDS = 86400
VIRTUAL_THRESHOLD_NS = 720_000_000_000
PROGRESS_INTERVAL_SECONDS = 1.0
RSS_LIMIT_BYTES = 4 * 1024**3
AVAILABLE_FLOOR_BYTES = 2 * 1024**3
DISK_FLOOR_BYTES = 22 * 1024**3
JOB_RESOURCES_SHA256 = '80e2f44951369747f2c890f0a30b872d02e42dcbae83b9e54a2ee689ce504cb6'
TAIL_BYTES = 2048
JSON_LIMIT_BYTES = 1024 * 1024
HOST_PYTHON_DIR = '/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin'
HOST_PYTHON = str(Path(HOST_PYTHON_DIR) / 'python3')
OBSERVER_WORK_SECONDS = 86360
SHARED_STOP_SECONDS = 720
LOG_NAMES = ('launcher.log', 'renode.log', 'qemu.log', 'console.bin')
Z_PARAMETERS = ('BED_RELATIVE_MM', 'OPPOSITE_STOP_RELATIVE_MM', 'BED_SIDE',
                'STIFFNESS_N_PER_MM', 'DAMPING_NS_PER_MM', 'BASELINE_COUNTS',
                'COUNTS_PER_N', 'SIGNAL_POLARITY', 'HISTORY_CAPACITY', 'QUERY_TRACE_ROWS', 'SENSOR_TRACE_ROWS')


def safe_json(path):
    """Never follow a link or block on a FIFO while reading optional evidence."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Evidence is not a regular file')
        data = stream.read(JSON_LIMIT_BYTES + 1)
    if len(data) > JSON_LIMIT_BYTES:
        raise ValueError('Evidence exceeds the JSON size limit')
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError('Evidence is not a JSON object')
    return value


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def fresh(path):
    return not path.exists() and not path.is_symlink()


def available_memory():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1]) * 1024
    raise RuntimeError('MemAvailable is unavailable')


def group_members(pgid):
    """Observe only; the outer subreaper owns orphan and detached-child tracking."""
    if type(pgid) is not int or pgid <= 0:
        return []
    rows = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            raw = (entry / 'stat').read_text()
            fields = raw[raw.rfind(')') + 2:].split()
            if int(fields[2]) == pgid:
                with (entry / 'cmdline').open('rb') as command:
                    arguments = command.read(4096).split(b'\0')
                rows.append({'pid': int(entry.name), 'ppid': int(fields[1]),
                             'pgid': int(fields[2]), 'session': int(fields[3]),
                             'state': fields[0], 'starttime_ticks': int(fields[19]),
                             'qemu_baseline_process': any(arg.endswith(b'/qemu-baseline') for arg in arguments[:4]),
                             'rss_bytes': int(fields[21]) * os.sysconf('SC_PAGE_SIZE')})
        except (OSError, ValueError, IndexError):
            # Processes may disappear between the directory scan and stat read.
            continue
    return sorted(rows, key=lambda row: row['pid'])


def log_tail(path, previous=None):
    result = {'status': 'missing', 'size_bytes': None, 'tail': ''}
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('Log is not a regular file')
            stream.seek(max(0, info.st_size - TAIL_BYTES))
            data = stream.read(TAIL_BYTES)
        identity = [info.st_dev, info.st_ino]
        result.update(status='observed', size_bytes=info.st_size,
                      identity=identity, mtime_ns=info.st_mtime_ns,
                      tail=data.decode('utf-8', errors='replace'),
                      tail_is_complete_file=info.st_size <= TAIL_BYTES,
                      truncated_since_previous=False, replaced_since_previous=False)
        if previous and previous.get('status') == 'observed':
            replaced = identity != previous.get('identity')
            result['replaced_since_previous'] = replaced
            result['truncated_since_previous'] = not replaced and info.st_size < previous['size_bytes']
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        result.update(status='unavailable', error=str(exc))
    return result


def virtual_progress(path, step_ack=False):
    """A missing bootstrap export means unknown time, never zero or host time."""
    try:
        sample = safe_json(path)
        now = sample.get('virtual_time_ns')
        if type(now) is not int or now < 0:
            raise ValueError('Invalid virtual_time_ns')
        if step_ack and (type(sample.get('step_id')) is not int or sample['step_id'] < 0
                         or type(sample.get('schema')) is not int or sample['schema'] != 1
                         or sample.get('source') != 'renode-shared-mcu-step'
                         or sample.get('enabled') is not True or sample.get('paused') is not True
                         or sample.get('time_went_backwards') is not False
                         or not isinstance(sample.get('epoch'), str) or not sample['epoch']):
            raise ValueError('Invalid paused Renode step acknowledgement')
        answer = {'status': 'observed', 'virtual_time_ns': now,
                  'threshold_reached': now >= VIRTUAL_THRESHOLD_NS}
        for key in ('epoch', 'sequence', 'step_id', 'time_went_backwards'):
            if key in sample and isinstance(sample[key], (str, int, bool, type(None))):
                answer[key] = sample[key]
        return answer
    except FileNotFoundError:
        return {'status': 'missing', 'virtual_time_ns': None}
    except (OSError, ValueError) as exc:
        return {'status': 'unavailable', 'virtual_time_ns': None, 'error': str(exc)}


def environment(profile, pycache_prefix=None):
    host_jit = os.environ.get('RENODE_HOST_JIT', 'default')
    if host_jit not in ('default', 'single-tier'):
        raise ValueError('RENODE_HOST_JIT must be default or single-tier')
    clock_opt_in = os.environ.get('C22_STOP_EVENT_OPT_IN', '0')
    if clock_opt_in not in ('0', '1'):
        raise ValueError('C22_STOP_EVENT_OPT_IN must be 0 or 1')
    clock_client = 'stop-event' if clock_opt_in == '1' else 'scalar'
    if os.environ.get('CLOCK_CLIENT', clock_client) != clock_client:
        raise ValueError('CLOCK_CLIENT conflicts with explicit opt-in')
    return {'GLOBAL_QUANTUM_US': '1', 'NOZZLE_TMC_MODEL': 'autobaud',
            'HEADLESS_READY_ONLY': '1', 'THERMAL_PROFILE': 'synthetic-cartridge-4x', 'Z_PROBE_PROFILE': 'synthetic-functional', 'PASSIVE_MOTOR_TRACE': '0',
            'NATIVE_NOZZLE_HEATER': '0', 'RENODE_HOST_JIT': host_jit, 'CLOCK_CLIENT': clock_client, 'C22_STOP_EVENT_OPT_IN': clock_opt_in, 'ICOUNT_SHIFT': '0',
            'RENODE_BOOTSTRAP': 'legacy', 'PYTHONDONTWRITEBYTECODE': '1',
            **({'PYTHONPYCACHEPREFIX': str(pycache_prefix)} if pycache_prefix is not None else {}),
            'QEMU_BINARY': str(profile / 'rv1106-at32-link/experimental/clock-snapshot/runtime/run-baseline')}


def plan(profile, evidence, name):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        raise ValueError('Invalid run name')
    if Path(profile).absolute() != Path(profile).resolve() or Path(evidence).absolute() != Path(evidence).resolve():
        raise ValueError('Symlinked or noncanonical profile/evidence paths are not accepted')
    profile, evidence = profile.resolve(), evidence.resolve()
    if profile != EXPECTED_PROFILE:
        raise ValueError('Only this exact source profile is accepted')
    run = profile / 'runs' / name
    pycache_prefix = evidence / (name + '-python-cache')
    if pycache_prefix == run or run in pycache_prefix.parents:
        raise ValueError('Derived Python cache prefix must be outside the future run directory')
    paths = {key: evidence / (name + suffix) for key, suffix in (
        ('configuration', '-configuration.json'), ('progress', '-progress.jsonl'),
        ('latest', '-latest.json'), ('supervision', '-supervision.json'),
        ('audit', '-post-audit.json'))}
    command = [HOST_PYTHON, '-I', '-B', '-X', 'pycache_prefix=' + str(pycache_prefix),
               str(profile / OBSERVER_RELATIVE),
               '--run-name', name, '--seconds', str(ACTIVE_SECONDS)]
    configuration = {
        'schema_version': 1, 'profile': str(profile), 'run_name': name, 'run_directory': str(run),
        'evidence_directory': str(evidence), 'command': command,
        'python_cache_prefix': str(pycache_prefix),
        'environment': environment(profile, pycache_prefix),
        'host_environment': {'PATH': HOST_PYTHON_DIR + ':/usr/bin:/bin', 'HOME': str(profile / 'at32-runtime/home'),
                             'LANG': 'C.UTF-8',
                             'TMPDIR': str(profile / 'runtime-private/tmp'),
                             'TMP': str(profile / 'runtime-private/tmp'),
                             'TEMP': str(profile / 'runtime-private/tmp'),
                             'XDG_CONFIG_HOME': str(profile / 'at32-runtime/home/.config'),
                             'XDG_CACHE_HOME': str(profile / 'runtime-private/cache'),
                             'XDG_DATA_HOME': str(profile / 'runtime-private/data'),
                             'XDG_STATE_HOME': str(profile / 'runtime-private/state'),
                             'XDG_RUNTIME_DIR': str(profile / 'runtime-private/xdg-runtime')},
        'budgets_seconds': {'total': TOTAL_SECONDS, 'stop_at': ACTIVE_SECONDS,
                           'graceful': GRACE_SECONDS, 'term': TERM_SECONDS,
                           'kill': KILL_SECONDS, 'planned_outer': OUTER_SECONDS},
        'virtual_threshold_ns': VIRTUAL_THRESHOLD_NS, 'virtual_threshold_is_strict_stepping_cap': False,
        'progress_interval_seconds': PROGRESS_INTERVAL_SECONDS,
        'resource_stop_min_available_bytes': AVAILABLE_FLOOR_BYTES,
        'resource_stop_max_group_rss_bytes': RSS_LIMIT_BYTES,
        'preflight_min_free_disk_bytes': DISK_FLOOR_BYTES,
        'bootstrap_seconds': 1, 'bootstrap_unchanged': True,
        'checkpoint_kind': 'Host progress evidence only; not a resumable VM snapshot',
        'observer_work_host_seconds': OBSERVER_WORK_SECONDS,
        'shared_stop_seconds': SHARED_STOP_SECONDS,
        'request_count': 0, 'identification_only': False, 'initial_thermal_response_only': False, 'full_pid_completion_claimed': False, 'ui_navigation': 'parent observed-frame-gated public framebuffer and file-queue input only',
        'source_hash_pin_pending': any(pin is None for pin in (OBSERVER_SHA256, PROTOCOL_SHA256, VALIDATOR_SHA256, MANIFEST_SHA256, *PINNED_CONTROLS.values())),
        'outer_guard_required': True, 'orphan_tracking_owner': 'outer_guard.py',
        'progress_writes_monitor_commands': False, 'progress_adds_virtual_steps': False,
        'firmware_changes': False, 'heating_commands': False, 'homing_commands': False,
        'print_commands': False, 'motion_commands': False, 'rpc_commands': False, 'gcode_commands': False, 'zero_commands': False, 'physical_completion_proven': False,
        'rss_note': 'Sampled summed process-group RSS may double-count shared mappings and miss peaks.',
        'artifacts': {key: str(path) for key, path in paths.items()},
    }
    return configuration, run, paths


def validate_configuration(configuration, run, paths):
    expected, expected_run, expected_paths = plan(Path(configuration['profile']),
        Path(configuration['evidence_directory']), configuration['run_name'])
    # Runtime evidence is added only after this equality check. No command,
    # environment, budget or destination substitutions are accepted.
    if configuration != expected or run != expected_run or paths != expected_paths:
        raise ValueError('Configuration differs from the fixed homing_completion plan')


def verify_source(path, expected):
    if expected is None or not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('Source hash pin pending review; no child launched: ' + str(path))
    if path.is_symlink() or not path.is_file():
        raise ValueError('Required source is missing or symlinked: ' + str(path))
    checksum = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Required source is not a regular file: ' + str(path))
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    digest = checksum.hexdigest()
    if digest != expected:
        raise ValueError('Source hash mismatch; no child launched: ' + str(path))
    return digest


def verified_source_module(path, expected, module_name):
    """Compile exactly the verified source bytes; never consult bytecode caches."""
    if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('Source hash pin pending review; no child launched: ' + str(path))
    if path.is_symlink() or not path.is_file():
        raise ValueError('Required source is missing or symlinked: ' + str(path))
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Required source is not regular: ' + str(path))
        source = stream.read(JSON_LIMIT_BYTES + 1)
    if len(source) > JSON_LIMIT_BYTES or hashlib.sha256(source).hexdigest() != expected:
        raise ValueError('Source hash mismatch or source exceeds limit: ' + str(path))
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = ''
    module.__cached__ = None
    module.__loader__ = None
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


def validate_pycache_prefix(configuration, *, require_runtime):
    prefix = Path(configuration['python_cache_prefix'])
    expected = Path(configuration['evidence_directory']) / (configuration['run_name'] + '-python-cache')
    if prefix != expected or prefix.absolute() != prefix.resolve():
        raise ValueError('Unexpected Python cache prefix; no child launched')
    if not fresh(prefix):
        raise ValueError('Fresh absent Python cache prefix required; no child launched')
    if (require_runtime and (sys.pycache_prefix != str(prefix)
                             or not sys.flags.dont_write_bytecode or not sys.flags.isolated)):
        raise ValueError('Python runtime cache isolation differs from fixed launch; no child launched')
    if 'PYTHONPYCACHEPREFIX' in os.environ and os.environ['PYTHONPYCACHEPREFIX'] != str(prefix):
        raise ValueError('Unexpected PYTHONPYCACHEPREFIX override; no child launched')


def verify_manifest(profile):
    """Verify reviewed transitive identities without loading code or changing state.

    The manifest excludes the two pin-owning wrappers to avoid circular hashes.
    Outer guard pins runner; runner pins this manifest and its direct modules.
    This proves file identity only, never hardware accuracy or safe calibration.
    """
    manifest = profile / MANIFEST_RELATIVE
    digest = verify_source(manifest, MANIFEST_SHA256)
    document = safe_json(manifest)
    if (type(document.get('schema_version')) is not int or document['schema_version'] != 1
            or document.get('scope') != MANIFEST_SCOPE):
        raise ValueError('Invalid execution manifest schema/scope')
    files = document.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Execution manifest has no source closure')
    mandatory = set(PINNED_CONTROLS) | {OBSERVER_RELATIVE, PROTOCOL_RELATIVE, VALIDATOR_RELATIVE, READY_REFERENCE_RELATIVE}
    if not mandatory <= set(files):
        raise ValueError('Execution manifest omits required controlling sources')
    # Runtime-only projection: retain the full historical manifest separately.
    expected_exclusions = {'printer-shared-mcu/experimental/z-probe-state-trace/evidence/shared/work/test.resc': '6c24c511148651ebfff5f1222b84d36f4ef4412262fa08e9ab09350024d855df', 'printer-shared-mcu/experimental/z-probe-state-trace/evidence/standalone/work/test.resc': 'b3399eaf5a611fe0f75be71bcc71832833bed31f1e7062f56165599421c385f6'}
    if (document.get('manifest_kind') != 'runtime-only'
            or document.get('archive_exclusions') != expected_exclusions
            or document.get('historical_archive_complete') is not False
            or document.get('historical_manifest_sha256') != '5b4edebbea9fce47d3e2ff0dadf935312c18a029c6cb65e4149640fdfe029661'
            or set(expected_exclusions) & set(files)):
        raise ValueError('Invalid runtime-only manifest scope or archive exclusions')
    generator_dirs = tuple(f'{board}/{sub}' for board in ('at32-renode', 'nozzle-renode', 'motor-renode')
                           for sub in ('peripherals', 'platforms', 'scripts'))
    membership = document.get('generator_membership')
    if not isinstance(membership, dict) or set(membership) != set(generator_dirs):
        raise ValueError('Invalid generator membership scope')
    for folder in generator_dirs:
        directory = profile / folder
        expected_names = sorted(relative for relative in files
                                if str(Path(relative).parent) == folder
                                and Path(relative).suffix in ('.cs', '.repl', '.resc'))
        if (membership[folder] != expected_names or directory.resolve() != directory.absolute()
                or not directory.is_dir()):
            raise ValueError('Invalid pinned generator directory membership: ' + folder)
        actual_names = sorted(str(path.relative_to(profile)) for path in directory.iterdir()
                              if path.suffix in ('.cs', '.repl', '.resc'))
        if actual_names != expected_names:
            raise ValueError('Generator input added or removed: ' + folder)
    start = time.monotonic()
    for relative, expected in files.items():
        if not isinstance(relative, str) or not relative or str(Path(relative)) != relative:
            raise ValueError('Invalid execution manifest relative path')
        local = Path(relative)
        path = profile / local
        if local.is_absolute() or '..' in local.parts or path.resolve() != path.absolute():
            raise ValueError('Execution manifest path escapes or follows a symlink')
        if relative in (MANIFEST_RELATIVE, 'rv1106-at32-link/experimental/native-ui-resonance/runner.py',
                        'rv1106-at32-link/experimental/native-ui-resonance/outer_guard.py'):
            raise ValueError('Execution manifest contains a circular pin-owning source')
        verify_source(path, expected)
    symlinks = document.get('symlinks', {})
    if not isinstance(symlinks, dict) or set(symlinks) & set(files):
        raise ValueError('Invalid or overlapping execution manifest symlinks')
    absent = document.get('absent_targets', [])
    if not isinstance(absent, list) or any(not isinstance(value, str) for value in absent):
        raise ValueError('Invalid execution manifest absent targets')
    if len(set(absent)) != len(absent) or set(absent) & (set(files) | set(symlinks)):
        raise ValueError('Duplicate or overlapping execution manifest absent targets')
    for relative in absent:
        local = Path(relative)
        path = profile / local
        if (not relative or str(local) != relative or local.is_absolute()
                or '..' in local.parts or path.resolve() != path.absolute()):
            raise ValueError('Noncanonical or outside execution manifest absent target')
        if path.exists() or path.is_symlink():
            raise ValueError('Execution manifest absent target is newly present or symlinked')
    referenced_absent = set()
    for relative, target in symlinks.items():
        if (not isinstance(relative, str) or not relative or str(Path(relative)) != relative
                or Path(relative).is_absolute() or '..' in Path(relative).parts
                or not isinstance(target, str) or not target or Path(target).is_absolute()):
            raise ValueError('Invalid execution manifest symlink path/target')
        path = profile / relative
        if (not path.is_symlink() or path.parent.resolve() != path.parent.absolute()
                or os.readlink(path) != target):
            raise ValueError('Execution manifest symlink changed or absent')
        resolved = path.resolve()
        try:
            target_relative = str(resolved.relative_to(profile))
        except ValueError as exc:
            raise ValueError('Execution manifest symlink target is outside profile') from exc
        if target_relative in absent:
            if resolved.exists() or resolved.is_symlink():
                raise ValueError('Execution manifest absent symlink target is newly present')
            referenced_absent.add(target_relative)
        elif target_relative not in files or not resolved.is_file():
            raise ValueError('Execution manifest symlink target is not a listed regular file or absent target')
    if referenced_absent != set(absent):
        raise ValueError('Orphan execution manifest absent target has no symlink reference')
    return {'sha256': digest, 'entry_count': len(files), 'symlink_count': len(symlinks),
            'absent_target_count': len(absent),
            'verification_elapsed_host_seconds': time.monotonic() - start,
            'scope': MANIFEST_SCOPE, 'physical_calibration_proven': False}


def validate_environment(profile, pycache_prefix=None):
    if any(key in os.environ for key in ('BASH_ENV', 'ENV', 'PYTHONPATH', 'PYTHONHOME',
                                         'LD_PRELOAD', 'LD_LIBRARY_PATH', 'LD_AUDIT')):
        raise ValueError('Unexpected shell, Python or loader override; use the documented clean launch')
    private = {'HOME': profile / 'at32-runtime/home', 'XDG_CONFIG_HOME': profile / 'at32-runtime/home/.config',
               **{key: profile / 'runtime-private' / name for key, name in (
                   ('TMPDIR', 'tmp'), ('TMP', 'tmp'), ('TEMP', 'tmp'), ('XDG_CACHE_HOME', 'cache'),
                   ('XDG_DATA_HOME', 'data'), ('XDG_STATE_HOME', 'state'), ('XDG_RUNTIME_DIR', 'xdg-runtime'))}}
    for key, path in private.items():
        if key in os.environ and os.environ[key] != str(path):
            raise ValueError('Unexpected private environment override: ' + key)
    expected = environment(profile, pycache_prefix)
    if pycache_prefix is None and 'PYTHONPYCACHEPREFIX' in os.environ:
        raise ValueError('Unexpected PYTHONPYCACHEPREFIX without derived prefix')
    for key, value in expected.items():
        if key in os.environ and os.environ[key] != value:
            raise ValueError('Unexpected environment override: ' + key)
    if any(key.startswith('Z_') and key != 'Z_PROBE_PROFILE' for key in os.environ):
        raise ValueError('Unexpected Z profile parameters; no child launched')
    forbidden = ('RUN_SECONDS', 'PASSIVE_CONTACT_TRACE',
                 'PASSIVE_NOZZLE_TRACE', 'PASSIVE_HOMING_GPIO', 'PASSIVE_TMC_TRACE',
                 'RECOVERED_NOZZLE_NTC', 'ASSUMED_XY_DIAG_CABLE', 'MOTOR_ENABLE_WIRING')
    if any(key in os.environ for key in forbidden):
        raise ValueError('Unexpected launcher environment override; no child launched')



def validate_private_directories(profile):
    """Apply the exact live sampler's ownership/mode guard before any emulator."""
    guard = verified_source_module(
        profile / 'rv1106-at32-link/experimental/native-ui-resonance/job_resources.py',
        JOB_RESOURCES_SHA256, 'preflight_private_directory_guard')
    result = {}
    for relative in ('runtime-private', 'runtime-private/tmp', 'runtime-private/cache',
                     'runtime-private/data', 'runtime-private/state', 'runtime-private/xdg-runtime',
                     'at32-runtime/home', 'at32-runtime/home/.config'):
        path = profile / relative
        if path.absolute() != path.resolve():
            raise ValueError('Aliased private runtime directory; no child launched: ' + relative)
        guard.private_directory(path)
        info = path.stat(follow_symlinks=False)
        result[relative] = {'mode': oct(stat.S_IMODE(info.st_mode)), 'uid': info.st_uid,
                            'runtime_sampler_validator_passed': True}
    return result


def validate_runtime_paths(profile,run,owner):
    guard = verified_source_module(
        profile / 'rv1106-at32-link/experimental/native-ui-resonance/job_resources.py',
        JOB_RESOURCES_SHA256, 'preflight_runtime_publisher_guard')
    return guard.validate_runtime_paths(profile,run,owner)


def preflight(configuration, run, paths):
    validate_configuration(configuration, run, paths)
    profile = Path(configuration['profile'])
    evidence = Path(configuration['evidence_directory'])
    if not evidence.is_dir() or not (profile / 'runs').is_dir():
        raise ValueError('Existing evidence and profile/runs directories are required')
    if sys.version_info[:2] != (3, 12) or Path(sys.executable).resolve() != Path(HOST_PYTHON).resolve():
        raise ValueError('Use the exact Python 3.12 runtime; no child launched')
    if not os.access(Path(HOST_PYTHON_DIR) / 'python3', os.X_OK):
        raise ValueError('The expected Python 3.12 runtime is unavailable; no child launched')
    experiment = profile / 'rv1106-at32-link/experimental/native-ui-resonance'
    if evidence == experiment or experiment in evidence.parents:
        raise ValueError('Run evidence must be outside the source experiment directory')
    candidates = [run, *paths.values(), *(path.with_name(path.name + '.tmp')
                                         for key, path in paths.items() if key != 'progress')]
    if any(not fresh(path) for path in candidates):
        raise ValueError('Fresh run and evidence paths are required')
    validate_environment(profile, configuration['python_cache_prefix'])
    validate_pycache_prefix(configuration, require_runtime=True)
    private_directories = validate_private_directories(profile)
    runtime_paths = validate_runtime_paths(profile,run,evidence)
    available = available_memory()
    disk = {str(directory): shutil.disk_usage(directory).free for directory in (evidence, run.parent)}
    if available < AVAILABLE_FLOOR_BYTES:
        raise ValueError('MemAvailable below 2 GiB; no child launched')
    if any(value < DISK_FLOOR_BYTES for value in disk.values()):
        raise ValueError('Free disk below22GiB admitted job allocation; no child launched')
    required = (OBSERVER_RELATIVE, PROTOCOL_RELATIVE, VALIDATOR_RELATIVE, LAUNCHER_RELATIVE,
                'rv1106-at32-link/scripts/run_native_ready_observation.py',
                'rv1106-at32-link/scripts/bounded_native_supervisor.py',
                'rv1106-at32-link/scripts/run_native_event_fixture.sh',
                'rv1106-at32-link/scripts/run_link.py',
                'rv1106-at32-link/experimental/bootstrap-boundaries/outer_guard.py',
                'rv1106-at32-link/experimental/native-ui-resonance/outer_guard.py',
                'rv1106-at32-link/experimental/clock-snapshot/runtime/run-baseline',
                'rv1106-at32-link/experimental/clock-snapshot/runtime/bin/qemu-baseline',
                'at32-runtime/renode_1.17.0-portable/renode',
                'rv1106-linux-display-128diag/linux-test.elf',
                'inputs/mcu.bin', 'inputs/motor.bin', 'inputs/nozzle.bin', 'inputs/offline-emmc.img')
    for relative in required:
        path = profile / relative
        if not path.is_file() or path.stat().st_size == 0 or not os.access(path, os.R_OK):
            raise ValueError('Missing or unreadable required input: ' + str(path))
    for key in ('HOME', 'TMPDIR', 'TMP', 'TEMP', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR'):
        path = Path(configuration['host_environment'][key])
        if path.resolve() != path.absolute() or not path.is_dir() or not path.is_relative_to(profile):
            raise ValueError('Private runtime directory missing, aliased, or outside profile: ' + key)
    configuration['preflight'] = {'available_memory_bytes': available, 'free_disk_bytes': disk,
                                  'private_directories': private_directories, 'runtime_publisher_paths': runtime_paths}
    configuration['controlling_source_sha256'] = {
        relative: verify_source(profile / relative, digest)
        for relative, digest in PINNED_CONTROLS.items()}
    configuration['observer_sha256'] = verify_source(profile / OBSERVER_RELATIVE, OBSERVER_SHA256)
    configuration['protocol_sha256'] = verify_source(profile / PROTOCOL_RELATIVE, PROTOCOL_SHA256)
    configuration['validator_sha256'] = verify_source(profile / VALIDATOR_RELATIVE, VALIDATOR_SHA256)
    configuration['execution_manifest'] = verify_manifest(profile)
    startup_encoding = verified_source_module(experiment / 'guest_startup_encoding.py',
        PINNED_CONTROLS['rv1106-at32-link/experimental/native-ui-resonance/guest_startup_encoding.py'], 'guest_startup_encoding')
    configuration['decoded_guest_startup'] = startup_encoding.validate(
        (experiment / 'native-ui-startup.commands').read_bytes(),
        (experiment / 'native-ui-startup-gate.sh').read_bytes(), run.name)
    configuration['runner_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def load_supervisor(profile):
    source = profile / 'rv1106-at32-link/scripts/bounded_native_supervisor.py'
    # Compile exact hash-verified bytes. No monkeypatching: all Ready validation
    # and cleanup gates remain unchanged, and no cached helper may substitute.
    return verified_source_module(source,
        PINNED_CONTROLS['rv1106-at32-link/scripts/bounded_native_supervisor.py'],
        'homing_completion_bounded_supervisor')


def read_homing_completion_report(path):
    report = safe_json(path)
    observer_path = EXPECTED_PROFILE / VALIDATOR_RELATIVE
    verify_source(observer_path, VALIDATOR_SHA256)
    verify_source(EXPECTED_PROFILE / PROTOCOL_RELATIVE, PROTOCOL_SHA256)
    observer = verified_source_module(observer_path, VALIDATOR_SHA256, 'homing_completion_final_report_validation')
    observer.validate_final_report(report)
    observer.validate_artifacts(path.parent, report)
    # Explicit wrapper gate: one genuine Ready request alone never passes.
    if (report.get('phase') != 'verified_homing_completion' or type(report.get('request_count')) is not int
            or report['request_count'] != 8 or report.get('final_export_requested') is not True
            or type(report.get('launcher_exit_code')) is not int or report['launcher_exit_code'] != 0
            or report.get('homing_completed') is not True
            or report.get('natural_release_observed') is not True
            or report.get('physical_completion_proven') is not False
            or report.get('calibration_completed') is not False):
        raise ValueError('Homing completion report is not an exact completed eight-request native homing observation')
    return report


class Recorder:
    """One host sampler and one append-only evidence writer; bounded retained state."""
    def __init__(self, run, paths):
        self.run, self.paths = run, paths
        self.stream = paths['progress'].open('x')
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, name='homing_completion-host-progress', daemon=True)
        self.started = time.monotonic()
        self.count = 0
        self.last_sample_time = None
        self.maximum_interval = 0.0
        self.maximum_rss = 0
        self.minimum_available = None
        self.errors = []
        self.resource_guard_triggered = False
        self.pending_stop = False
        self.previous_logs = {}
        self.last_row = None
        self.milestones = {}
        self.maximum_observed_virtual_time_ns = None
        self.last_disk_sample = 0
        self.disk_report = None
        self.disk_guard = verified_source_module(HERE/'job_resources.py',JOB_RESOURCES_SHA256,'c10_job_resources')

    def request_stop(self):
        try:
            with (self.run / 'stop-request').open('x') as stream:
                stream.write('Host progress sampler requests stop; no continuation.\n')
            return 'created'
        except FileExistsError:
            return 'already_present'
        except FileNotFoundError:
            return 'pending_run_directory'

    def sample(self, final=False):
        now = time.monotonic()
        gap = None if self.last_sample_time is None else now - self.last_sample_time
        if gap is not None:
            self.maximum_interval = max(self.maximum_interval, gap)
        self.last_sample_time = now
        try:
            supervision = safe_json(self.paths['supervision'])
        except FileNotFoundError:
            supervision = {}
        pgid = supervision.get('process_group_id')
        rows = group_members(pgid)
        rss, available = sum(row['rss_bytes'] for row in rows), available_memory()
        self.maximum_rss = max(self.maximum_rss, rss)
        self.minimum_available = available if self.minimum_available is None else min(self.minimum_available, available)
        if rss > RSS_LIMIT_BYTES or available < AVAILABLE_FLOOR_BYTES:
            self.resource_guard_triggered = self.pending_stop = True
        if now-self.last_disk_sample >= 10 or final:
            self.disk_report=self.disk_guard.inventory([self.run,self.paths['latest'].parent.parent,EXPECTED_PROFILE/'runtime-private'],owned_processes=rows)
            self.last_disk_sample=now
        logs = {name: log_tail(self.run / name, self.previous_logs.get(name)) for name in LOG_NAMES}
        self.previous_logs = logs
        virtual = virtual_progress(self.run / 'virtual-time.json')
        step = virtual_progress(self.run / 'renode-step.json', step_ack=True)
        virtual_ns = virtual.get('virtual_time_ns')
        if virtual_ns is not None:
            self.maximum_observed_virtual_time_ns = max(self.maximum_observed_virtual_time_ns or 0, virtual_ns)
        observations = {
            'virtual_time_export_observed': virtual['status'] == 'observed',
            'legacy_full_bootstrap_ack_observed': step['status'] == 'observed' and step['virtual_time_ns'] >= 1_000_000_000,
            'post_bootstrap_step_ack_observed': step['status'] == 'observed' and step['virtual_time_ns'] > 1_000_000_000 and step['step_id'] > 0,
            'qemu_baseline_process_observed': any(member['qemu_baseline_process'] for member in rows),
            'nonempty_console_observed': (logs['console.bin'].get('size_bytes') or 0) > 0,
        }
        for name, observed in observations.items():
            if observed and name not in self.milestones:
                self.milestones[name] = {'first_elapsed_seconds': now - self.started}
        stages = supervision.get('stages')
        row = {'schema_version': 1, 'sequence': self.count, 'final_sample': final,
               'elapsed_seconds': now - self.started, 'host_unix_time_ns': time.time_ns(),
               'interval_since_previous_seconds': gap, 'process_group_id': pgid,
               'members': rows, 'group_rss_bytes': rss, 'available_memory_bytes': available,
               'last_supervisor_stage': stages[-1] if isinstance(stages, list) and stages else None,
               'virtual_time': virtual, 'renode_step': step, 'milestones': dict(self.milestones),
               'artifact_budget':self.disk_report, 'logs': logs, 'resource_guard_triggered': self.resource_guard_triggered,
               'resumable_vm_snapshot': False, 'physical_completion_proven': False}
        if self.pending_stop:
            row['stop_request'] = self.request_stop()
        self.write(row)

    def write(self, row):
        self.stream.write(json.dumps(row, allow_nan=False) + '\n')
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.count += 1
        self.last_row = row
        # Keep the latest summary small; detailed tails and process rows stay in JSONL.
        latest = {key: value for key, value in row.items() if key not in ('logs', 'members')}
        latest.update(status='active', success=False, sample_count=self.count,
                      success_scope='Initial thermal response observation and inner cleanup only; unchanged Ready/homing gates and outer guard remain required',
                      outer_guard_verification_pending=True,
                      progress_file=str(self.paths['progress']),
                      checkpoint_kind='Evidence only; not a resumable VM snapshot',
                      logs={key: {k: v for k, v in value.items() if k != 'tail'}
                            for key, value in row.get('logs', {}).items()},
                      process_count=len(row.get('members', [])), sampling_errors=list(self.errors))
        atomic_json(self.paths['latest'], latest)

    def attempt_sample(self, final=False):
        try:
            self.sample(final=final)
        except Exception as exc:
            message = type(exc).__name__ + ': ' + str(exc)
            if message not in self.errors:
                self.errors.append(message)
            self.pending_stop = True
            row = {'schema_version': 1, 'sequence': self.count, 'final_sample': final,
                   'elapsed_seconds': time.monotonic() - self.started,
                   'sampling_error': message, 'resumable_vm_snapshot': False}
            try:
                row['stop_request'] = self.request_stop()
            except OSError as stop_error:
                row['stop_request_error'] = str(stop_error)
            try:
                self.write(row)
            except Exception as write_error:
                message = 'Progress persistence failed: ' + str(write_error)
                if message not in self.errors:
                    self.errors.append(message)

    def loop(self):
        while not self.stop.is_set():
            begin = time.monotonic()
            self.attempt_sample()
            self.stop.wait(max(0, PROGRESS_INTERVAL_SECONDS - (time.monotonic() - begin)))
        self.attempt_sample(final=True)

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=2)
        finished = not self.thread.is_alive()
        if finished:
            self.stream.close()
        return finished


def audit_group(pgid):
    result = {'members': group_members(pgid), 'group_absent_confirmed': False,
              'group_probe_error': None, 'scope': 'Same PID namespace and process group only; outer guard audits all descendants'}
    if type(pgid) is int and pgid > 0:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            result['group_absent_confirmed'] = True
        except OSError as exc:
            result['group_probe_error'] = str(exc)
    return result


def execute(configuration, run, paths):
    preflight(configuration, run, paths)
    with paths['configuration'].open('x') as stream:
        json.dump(configuration, stream, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    supervisor = load_supervisor(Path(configuration['profile']))
    recorder = Recorder(run, paths)
    result = {'success': False, 'errors': ['Supervisor did not return a result']}
    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(configuration['host_environment'])
    os.environ.update(configuration['environment'])
    sampler_started = False
    try:
        recorder.thread.start()
        sampler_started = True
        result = supervisor.supervise(
            configuration['command'], stop_request=run / 'stop-request',
            native_report=run / 'ready-prerequisite.json', evidence=paths['supervision'],
            total_seconds=TOTAL_SECONDS, grace_seconds=GRACE_SECONDS,
            term_seconds=TERM_SECONDS, kill_seconds=KILL_SECONDS,
            virtual_time_file=run / 'virtual-time.json', max_virtual_time_ns=VIRTUAL_THRESHOLD_NS)
    except (Exception, KeyboardInterrupt) as exc:
        result = {'success': False, 'errors': [type(exc).__name__ + ': ' + str(exc)]}
    finally:
        if sampler_started:
            finished = recorder.finish()
        else:
            recorder.stream.close()
            finished = False
        os.environ.clear()
        os.environ.update(previous)
    audit = audit_group(result.get('process_group_id'))
    audit.update(sample_count=recorder.count, sampling_finished=finished,
                 maximum_sampled_group_rss_bytes=recorder.maximum_rss,
                 minimum_sampled_available_memory_bytes=recorder.minimum_available,
                 maximum_sample_interval_seconds=recorder.maximum_interval,
                 progress_interval_over_two_seconds=recorder.maximum_interval > 2,
                 resource_guard_triggered=recorder.resource_guard_triggered,
                 milestones=recorder.milestones,
                 maximum_observed_virtual_time_ns=recorder.maximum_observed_virtual_time_ns,
                 sampling_errors=recorder.errors, resumable_vm_snapshot=False)
    homing_completion_valid = False
    homing_completion_error = None
    try:
        read_homing_completion_report(run / 'homing-completion.json')
        homing_completion_valid = True
    except Exception as exc:
        homing_completion_error = type(exc).__name__ + ': ' + str(exc)
    success = (homing_completion_valid and result.get('success') is True and result.get('native_report_valid') is True
               and result.get('child_exit_code') == 0 and not result.get('forced_signals')
               and audit['group_absent_confirmed'] and not audit['members'] and finished
               and recorder.count > 0 and not recorder.errors and not recorder.resource_guard_triggered
               and recorder.maximum_interval <= 2)
    report = {'success': success, 'identification_only': False, 'initial_thermal_response_only': False, 'full_pid_completion_claimed': False,
              'diagnostic_report': str(run / 'native-calibration-attempt.json'),
              'homing_completion_report_valid': homing_completion_valid,
              'homing_completion_report_error': homing_completion_error,
              'homing_completed': homing_completion_valid, 'natural_release_observed': homing_completion_valid,
              'physical_completion_proven': False, 'calibration_completed': False,
              'success_scope': 'Initial thermal response observation and inner cleanup only; unchanged Ready/homing gates and outer guard remain required',
              'outer_guard_verification_pending': True,
              'resumable_vm_snapshot': False, 'supervision': result, 'post_audit': audit}
    atomic_json(paths['audit'], report)
    if finished:
        latest = safe_json(paths['latest'])
        latest.update(status='finished' if success else 'failed', success=success,
                      success_scope=report['success_scope'], outer_guard_verification_pending=True,
                      post_audit_file=str(paths['audit']), supervision_file=str(paths['supervision']))
        atomic_json(paths['latest'], latest)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--plan', action='store_true', help='Print fixed configuration without writes or child launches')
    args = parser.parse_args(argv)
    try:
        configuration, run, paths = plan(args.profile, args.evidence_dir, args.name)
        if args.plan:
            print(json.dumps(configuration, indent=2))
            return 0
        report = execute(configuration, run, paths)
    except (Exception, KeyboardInterrupt) as exc:
        print(json.dumps({'success': False, 'error': type(exc).__name__ + ': ' + str(exc),
                          'physical_completion_proven': False}), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report['success'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
