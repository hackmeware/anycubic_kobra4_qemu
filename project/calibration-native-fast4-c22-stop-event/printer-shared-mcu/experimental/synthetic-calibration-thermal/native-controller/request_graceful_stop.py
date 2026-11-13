#!/usr/bin/env python3
"""Publish one atomic graceful intent. Does not send an RPC or stop the emulator."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[4]
INTENT_NAME = 'graceful-stop-request.json'


def publish(directory, reason):
    if type(reason) is not str or not 1 <= len(reason) <= 1000 or any(ord(c) < 32 for c in reason):
        raise ValueError('Reason must be1..1000plain characters without control codes')
    report = json.loads((directory / 'thermal-observation.json').read_text())
    if 'launcher_exit_code' in report or (directory / 'stop-request').exists():
        raise ValueError('Run already ended or immediate stop was requested')
    payload = (json.dumps({'action': 'stop_heating', 'reason': reason}) + '\n').encode()
    fd, name = tempfile.mkstemp(prefix='.graceful-intent-', dir=directory)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic publication without replacement, even with competing callers.
        os.link(temporary, directory / INTENT_NAME)
    finally:
        temporary.unlink(missing_ok=True)
    return directory / INTENT_NAME


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_name')
    parser.add_argument('--reason', required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch('[A-Za-z0-9_-]+', args.run_name):
        parser.error('Invalid run name')
    path = publish(ROOT / 'runs' / args.run_name, args.reason)
    print('Graceful intent published: ' + str(path))
    print('Await controller report. This does not prove zero, heater off, or cooling.')


if __name__ == '__main__':
    main()
