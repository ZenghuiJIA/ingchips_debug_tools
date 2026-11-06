"""Versioned configuration loading, migration and validation (no executable expressions)."""
import copy
import json
import re
from pathlib import Path

ALIASES = {'firmware.flash': 'flash_firmware', 'target.reset': 'reset_target',
           'serial.capture': 'serial_open', 'serial.send': 'serial_send',
           'serial.expect': 'serial_wait_match', 'test.observe': 'hil_observe',
           'memory.read': 'swd_read_block', 'repeat': 'loop_block'}
COMMON = {'probe_id', 'target_device', 'frequency', 'pack_path'}
SERIAL = {'port_name', 'baud_rate'}
PARAMS = {
    'protocol_request': SERIAL | {'protocol', 'values', 'expected', 'timeout_ms'},
    'delay': {'delay_ms'},
    'serial_open': SERIAL,
    'serial_send': SERIAL | {'send_data', 'send_format', 'send_ending'},
    'serial_wait_match': SERIAL | {'match_type', 'pattern', 'timeout_ms', 'idle_timeout_ms'},
    'hil_observe': SERIAL | {'timeout_ms', 'boot_timeout_ms', 'idle_timeout_ms', 'boot_count', 'continue_on_failure'},
    'flash_firmware': COMMON | {'flash_type', 'file_path', 'after_flash', 'single_addr', 'baud_rate', 'port_name'},
    'reset_target': COMMON | SERIAL | {'reset_method', 'pulse_ms'},
    'swd_read_assert': COMMON | {'memory_addr', 'read_width', 'operator', 'expected_value', 'timeout_ms'},
    'swd_read_block': COMMON | {'memory_addr', 'count', 'symbol', 'axf_path'},
    'svd_check_reg': COMMON | {'peripheral', 'register', 'field_name', 'operator', 'expected_reg_val', 'timeout_ms'},
    'loop_block': {'count'},
}
SAFE_RETRY = {'swd_read_assert', 'svd_read_block', 'svd_check_reg'}


def integer(value, name, minimum=0, maximum=0xffffffff):
    if isinstance(value, bool):
        raise ValueError(f'{name}: expected integer')
    if isinstance(value, int):
        n = value
    elif isinstance(value, str) and re.fullmatch(r'(?:0[xX][0-9a-fA-F]+|[0-9]+)', value):
        n = int(value, 16 if value.lower().startswith('0x') else 10)
    else:
        raise ValueError(f'{name}: expected integer, got {value!r}')
    if not minimum <= n <= maximum:
        raise ValueError(f'{name}: expected {minimum}..{maximum}')
    return n


def duration(value):
    if isinstance(value, str):
        m = re.fullmatch(r'(\d+(?:\.\d+)?)(ms|s|m|h)', value)
        if m:
            value = int(float(m[1]) * {'ms': 1, 's': 1000, 'm': 60000, 'h': 3600000}[m[2]])
    return integer(value, 'duration_ms', 1, 7 * 86400000)


def read_document(path):
    path = Path(path).resolve()
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Configuration exceeds 2 MiB')
    text = path.read_text(encoding='utf-8-sig')
    if path.suffix.lower() in ('.yaml', '.yml'):
        import yaml
        # Reject duplicate keys rather than silently changing test intent.
        class Loader(yaml.SafeLoader):
            pass
        def mapping(loader, node):
            result = {}
            for k, v in node.value:
                key = loader.construct_object(k)
                if key in result:
                    raise ValueError(f'Duplicate YAML key: {key}')
                result[key] = loader.construct_object(v)
            return result
        Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
        return yaml.load(text, Loader=Loader)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=pairs)


def load_plan(document=None, file=None, parameters=None, base_dir=None):
    if file:
        if document is not None:
            raise ValueError('Use document or file, not both')
        document = read_document(file)
        base_dir = str(Path(file).resolve().parent)
    base = Path(base_dir or Path.cwd()).resolve()
    if not isinstance(document, dict):
        raise ValueError('Test document must be an object')
    doc = copy.deepcopy(document)
    if len(json.dumps(doc)) > 2 * 1024 * 1024:
        raise ValueError('Configuration exceeds 2 MiB')
    allowed = {'$schema', 'schema_version', 'version', 'name', 'description', 'loop_count', 'stop_on_error',
               'steps', 'bench', 'parameters', 'evidence', 'timeout_ms'}
    unknown = set(doc) - allowed
    if unknown:
        raise ValueError(f'Unknown document fields: {sorted(unknown)}')
    if doc.get('schema_version', 1) not in (1, 2):
        raise ValueError('This compatibility Python runner supports v1/v2; use the native runtime for HIL v3')
    legacy = doc.get('schema_version', 1) == 1
    variables = doc.pop('parameters', {})
    if not isinstance(variables, dict) or not isinstance(parameters or {}, dict):
        raise ValueError('parameters must be an object')
    for key in parameters or {}:
        if key not in variables:
            raise ValueError(f'Unknown parameter: {key}')
    variables.update(parameters or {})
    def expand(value, depth=0):
        if depth > 32:
            raise ValueError('Configuration nesting exceeds 32')
        if isinstance(value, str):
            def replacement(m):
                if m[1] not in variables:
                    raise ValueError(f'Missing parameter: {m[1]}')
                return str(variables[m[1]])
            return re.sub(r'\$\{([\w.-]+)\}', replacement, value)
        if isinstance(value, list):
            return [expand(x, depth + 1) for x in value]
        if isinstance(value, dict):
            return {k: expand(v, depth + 1) for k, v in value.items()}
        return value
    doc = expand(doc)
    bench = doc.pop('bench', {})
    bench_base = base
    if isinstance(bench, str):
        bench_path = (base / bench).resolve()
        bench_base = bench_path.parent
        bench = expand(read_document(bench_path))
    if not isinstance(bench, dict) or set(bench) - (COMMON | SERIAL):
        raise ValueError('bench accepts probe_id, target_device, frequency, pack_path, port_name, baud_rate')
    if bench.get('pack_path'):
        bench['pack_path'] = str((bench_base / bench['pack_path']).resolve())
    ids = set()
    ports, probes = {}, set()
    count = 0
    def normalize(steps, depth=0):
        nonlocal count
        if not isinstance(steps, list) or not steps or depth > 8:
            raise ValueError('steps must be nonempty; nesting limit is 8')
        output = []
        for index, original in enumerate(steps):
            count += 1
            if count > 1000 or not isinstance(original, dict):
                raise ValueError('Invalid steps (maximum 1000 definitions)')
            s = copy.deepcopy(original)
            if set(s) - {'id', 'name', 'action', 'params', 'enabled', 'timeout_ms', 'on_failure', 'retry_count', 'steps'}:
                raise ValueError(f'Unknown fields in step {s.get("id", index)}')
            action = ALIASES.get(s.get('action'), s.get('action'))
            if action not in PARAMS:
                raise ValueError(f'Unsupported action: {action}')
            s['action'] = action
            s.setdefault('id', f'step_{count}')
            if not isinstance(s['id'], str) or not re.fullmatch(r'[\w.-]{1,80}', s['id']) or s['id'] in ids:
                raise ValueError(f'Invalid or duplicate step id: {s["id"]}')
            ids.add(s['id'])
            s.setdefault('name', s['id'])
            s.setdefault('enabled', True)
            if not isinstance(s['enabled'], bool):
                raise ValueError('enabled must be boolean')
            p = s.get('params', {})
            if not isinstance(p, dict) or set(p) - PARAMS[action]:
                raise ValueError(f'{s["id"]}: unknown parameters for {action}')
            p = {**{k: v for k, v in bench.items() if k in PARAMS[action]},
                 **{k: v for k, v in p.items() if not (k in (COMMON | SERIAL) and v == '')}}
            s['params'] = p
            if legacy:
                for numeric in ('expected_value', 'expected_reg_val'):
                    value = p.get(numeric)
                    if isinstance(value, str) and re.fullmatch(r'[0-9a-fA-F]+', value.strip()):
                        p[numeric] = '0x' + value.strip()
            if not s['enabled']:
                output.append(s)
                continue
            if 'steps' in s and action != 'loop_block':
                raise ValueError('Only loop_block can contain steps')
            if action == 'loop_block':
                p['count'] = integer(p.get('count', 1), 'loop count', 1, 10000)
                s['steps'] = normalize(s.get('steps'), depth + 1)
            if action.startswith('serial_') or action in ('hil_observe', 'protocol_request') or (action == 'reset_target' and p.get('reset_method', 'swd_soft_reset') != 'swd_soft_reset'):
                port = p.get('port_name')
                if not isinstance(port, str) or not port.strip():
                    raise ValueError(f'{s["id"]}: select an explicit serial port')
                port = port.strip().upper() if port.upper().startswith('COM') else port.strip()
                p['port_name'] = port
                baud = integer(p.get('baud_rate', 115200), 'baud_rate', 300, 4000000)
                if port in ports and ports[port] != baud:
                    raise ValueError(f'Conflicting baud rates for {port}')
                p['baud_rate'] = baud
                ports[port] = baud
            swd = action in ('flash_firmware', 'swd_read_assert', 'swd_read_block', 'svd_check_reg') or (action == 'reset_target' and p.get('reset_method', 'swd_soft_reset') == 'swd_soft_reset')
            if swd:
                if not p.get('probe_id') or not p.get('target_device'):
                    raise ValueError(f'{s["id"]}: probe_id and target_device are required')
                probes.add(p['probe_id'])
                p['frequency'] = integer(p.get('frequency', 1000000), 'frequency Hz', 1000, 50000000)
            for k in ('file_path', 'pack_path', 'axf_path'):
                if p.get(k):
                    p[k] = str((base / p[k]).resolve())
                    if not Path(p[k]).is_file():
                        raise ValueError(f'{k}: file not found: {p[k]}')
            if action == 'flash_firmware':
                if p.get('flash_type', 'pyocd') != 'pyocd':
                    raise ValueError('Headless ING flashing is not supported; use the manual ING page')
                if not p.get('file_path') or Path(p['file_path']).suffix.lower() not in ('.hex', '.elf', '.axf'):
                    raise ValueError('Automated flashing requires an addressed HEX/ELF/AXF image')
                if p.get('after_flash', 'halt') not in ('halt', 'reset', 'none'):
                    raise ValueError('after_flash must be halt, reset or none')
            if action == 'reset_target' and p.get('reset_method', 'swd_soft_reset') != 'swd_soft_reset':
                raise ValueError('Automated reset currently requires swd_soft_reset; pin wiring is board-specific')
            if action in ('swd_read_assert', 'swd_read_block'):
                if action == 'swd_read_block' and p.get('symbol'):
                    if not p.get('axf_path'):
                        raise ValueError('symbol requires axf_path')
                else:
                    p['memory_addr'] = integer(p.get('memory_addr'), 'memory_addr')
                if action == 'swd_read_block':
                    p['count'] = integer(p.get('count', 256), 'count bytes', 1, 4096)
                else:
                    p['read_width'] = integer(p.get('read_width', 32), 'read_width')
                    if p['read_width'] not in (8, 16, 32):
                        raise ValueError('read_width must be 8, 16, 32')
                    p['expected_value'] = integer(p.get('expected_value'), 'expected_value', 0, 2**p['read_width']-1)
            if action in ('swd_read_assert', 'svd_check_reg'):
                if p.get('operator', '==') not in ('==', '!=', '>', '<', '>=', '<=', 'mask'):
                    raise ValueError('Unsupported comparison operator')
            if action == 'svd_check_reg':
                if not p.get('peripheral') or not p.get('register'):
                    raise ValueError('SVD requires peripheral and register')
                p['expected_reg_val'] = integer(p.get('expected_reg_val'), 'expected_reg_val')
            if action == 'serial_wait_match':
                if not isinstance(p.get('pattern'), str) or not p['pattern'] or len(p['pattern']) > 4096:
                    raise ValueError('A nonempty pattern (max 4096 characters) is required')
                if p.get('match_type', 'contains') not in ('contains', 'regex'):
                    raise ValueError('match_type must be contains or regex')
                if p.get('match_type') == 'regex':
                    re.compile(p['pattern'])
            if action == 'serial_send':
                if not isinstance(p.get('send_data', ''), str) or len(p.get('send_data', '')) > 65536:
                    raise ValueError('send_data must be a string of at most 65536 characters')
                if p.get('send_format', 'string') not in ('string', 'hex') or p.get('send_ending', 'none') not in ('none', 'crlf', 'lf'):
                    raise ValueError('Invalid serial encoding')
                if p.get('send_format') == 'hex':
                    bytes.fromhex(p.get('send_data', ''))
            if action == 'protocol_request':
                from .codec import Codec
                if isinstance(p.get('protocol'), str):
                    p['protocol'] = read_document(base / p['protocol'])
                if not isinstance(p.get('protocol'), dict) or not isinstance(p.get('values'), dict) or not isinstance(p.get('expected'), dict) or not p['expected']:
                    raise ValueError('protocol_request requires protocol, values and nonempty expected fields')
                with Codec(p['protocol']) as codec:
                    codec.encode(p['values'])
            for k in ('timeout_ms', 'idle_timeout_ms', 'boot_timeout_ms', 'delay_ms', 'pulse_ms'):
                if k in p:
                    p[k] = duration(p[k])
            if action == 'hil_observe':
                p['boot_count'] = integer(p.get('boot_count', 1), 'boot_count', 1, 100)
                if not isinstance(p.get('continue_on_failure', True), bool):
                    raise ValueError('continue_on_failure must be boolean')
            default_timeout = 300000 if action == 'flash_firmware' else (1800000 if action == 'hil_observe' else 3000)
            s['timeout_ms'] = duration(s.get('timeout_ms', p.get('timeout_ms', default_timeout)))
            if action == 'delay' and p.get('delay_ms', 500) > s['timeout_ms']:
                raise ValueError('delay exceeds step timeout')
            s['on_failure'] = s.get('on_failure', 'abort' if doc.get('stop_on_error', True) else 'continue')
            if s['on_failure'] not in ('abort', 'continue', 'retry'):
                raise ValueError('Invalid on_failure')
            s['retry_count'] = integer(s.get('retry_count', 0), 'retry_count', 0, 10)
            if s['on_failure'] == 'retry' and action not in SAFE_RETRY:
                raise ValueError(f'{action}: automatic retry is unsafe; use an explicit loop')
            output.append(s)
        return output
    doc['steps'] = normalize(doc.get('steps'))
    doc['schema_version'] = 2
    doc['name'] = str(doc.get('name', 'HIL test'))
    doc['loop_count'] = integer(doc.get('loop_count', 1), 'loop_count', 1, 10000)
    if not isinstance(doc.get('stop_on_error', True), bool):
        raise ValueError('stop_on_error must be boolean')
    def expanded_count(steps):
        return sum((s['params']['count'] * expanded_count(s['steps']) if s['action'] == 'loop_block' else 1)
                   for s in steps if s['enabled'])
    expanded = expanded_count(doc['steps']) * doc['loop_count']
    if not 1 <= expanded <= 10000:
        raise ValueError('Plan must execute 1..10000 leaf steps (including loops)')
    doc['timeout_ms'] = duration(doc.get('timeout_ms', '24h'))
    evidence = doc.get('evidence', {})
    if not isinstance(evidence, dict) or set(evidence) - {'enabled', 'memory_addr', 'count', 'timeout_ms'}:
        raise ValueError('Invalid evidence configuration')
    if not isinstance(evidence.get('enabled', True), bool):
        raise ValueError('evidence.enabled must be boolean')
    if 'memory_addr' in evidence:
        evidence['memory_addr'] = integer(evidence['memory_addr'], 'crash memory address')
        evidence['count'] = integer(evidence.get('count', 256), 'crash memory count', 1, 4096)
    evidence['timeout_ms'] = duration(evidence.get('timeout_ms', '10s'))
    doc['evidence'] = evidence
    doc['_resources'] = {'ports': ports, 'probes': sorted(probes)}
    doc['_base_dir'] = str(base)
    return doc
