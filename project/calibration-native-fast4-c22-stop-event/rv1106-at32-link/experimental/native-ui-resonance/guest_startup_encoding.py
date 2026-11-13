"""Pure byte-level startup generation/validation. Never executes guest commands."""
import hashlib
import re

PRINTF = re.compile(r"printf '((?:\\[0-7]{3})+)' (>>?) (/tmp/[A-Za-z0-9_.-]+)")
DIAGNOSTIC_SHA256 = '22c545b0a83c7f5edf974e4e89d139b4e6177d309b1c3d36a6b4b16636f620ad'
MARKERS = (b'C18_UI_GATE_BEGIN run=%s', b'C18_UI_STARTUP_ABORT run=%s',
           b'C18_UI_BACKEND_VERIFIED run=%s', b'C18_UI_LAUNCH_BEGIN run=%s',
           b'C18_UI_LAUNCHED run=%s', b'COLD_UI_STARTUP_COMMANDS_DONE')

def decode(commands):
    files = {}
    for line in commands.decode('ascii').splitlines():
        if not line.startswith('printf '):
            continue
        match = PRINTF.fullmatch(line)
        if match is None:
            raise ValueError('Unsupported guest printf encoding')
        encoded, mode, path = match.groups()
        if mode == '>' and path in files or mode == '>>' and path not in files:
            raise ValueError('Repeated or unordered guest file creation')
        payload = bytes(int(part, 8) for part in re.findall(r'\\([0-7]{3})', encoded))
        files[path] = files.get(path, b'') + payload
    return files

def identity(run_name):
    match = re.fullmatch(r'native-fast4-86400s-(c[1-9][0-9]*)', run_name)
    if not match:
        raise ValueError('Unsupported guest run identity')
    return match[1]

def validate(commands, gate, run_name):
    tag = identity(run_name)
    path = '/tmp/' + tag + '-native-ui-startup.sh'
    files = decode(commands)
    if set(files) != {'/tmp/diagnostic-touch', path} or files[path] != gate:
        raise ValueError('Decoded guest startup differs from canonical gate')
    if hashlib.sha256(files['/tmp/diagnostic-touch']).hexdigest() != DIAGNOSTIC_SHA256:
        raise ValueError('Guest diagnostic executable changed')
    text = commands.decode('ascii')
    if text.splitlines()[-1] != '/bin/sh ' + path or text.count('/bin/sh ' + path) != 1:
        raise ValueError('Guest gate invocation differs')
    if re.findall(rb'^RUN=(.+)$', gate, re.M) != [run_name.encode()]:
        raise ValueError('Decoded guest run identity differs')
    if re.findall(rb'^D=(.+)$', gate, re.M) != [('/tmp/' + tag + '-ui-startup').encode()]:
        raise ValueError('Decoded guest temporary directory differs')
    for data in (commands, *files.values()):
        if any(found.decode() != tag for found in re.findall(rb'(c[0-9]+)-(?:native-ui-startup|ui-startup)', data)):
            raise ValueError('Old guest temporary identity')
        if any(found.decode() != run_name for found in re.findall(rb'native-fast4-86400s-c[0-9]+', data)):
            raise ValueError('Other-run guest identity')
    if any(gate.count(marker) != 1 for marker in MARKERS):
        raise ValueError('Missing or repeated guest protocol marker')
    return {'run_name': run_name, 'guest_path': path,
            'decoded_gate_sha256': hashlib.sha256(gate).hexdigest(),
            'diagnostic_sha256': DIAGNOSTIC_SHA256, 'decoded_gate_bytes': len(gate)}

def generate(template, gate, run_name):
    # Preserve every non-gate command and the diagnostic ELF byte stream.
    identity(run_name)
    lines = template.decode('ascii').splitlines()
    old_paths = [path for path in decode(template) if path.endswith('-native-ui-startup.sh')]
    if len(old_paths) != 1:
        raise ValueError('Expected one template gate')
    old = old_paths[0]
    if lines[-1] != '/bin/sh ' + old:
        raise ValueError('Unexpected template gate invocation')
    prefix = []
    for line in lines[:-1]:
        match = PRINTF.fullmatch(line)
        if match and match[3] == old:
            continue
        prefix.append(line)
    path = '/tmp/' + identity(run_name) + '-native-ui-startup.sh'
    for offset in range(0, len(gate), 192):
        encoded = ''.join('\\%03o' % b for b in gate[offset:offset+192])
        prefix.append("printf '" + encoded + "' " + ('>' if offset == 0 else '>>') + ' ' + path)
    result = ('\n'.join(prefix + ['/bin/sh ' + path]) + '\n').encode('ascii')
    validate(result, gate, run_name)
    return result
