"""Verify the packaged daemon's file parsing and validation without opening probes."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from intelhex import IntelHex

exe = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / 'image.hex'
    image = IntelHex()
    image[0x20000001] = 0x42
    image.write_hex_file(str(path))
    requests = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'read_memory_image', 'params': {'file_path': str(path), 'address': '0x20000000', 'count': 4}},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'read_memory', 'params': {'address': '0x20000000', 'count': 65536}},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'write_memory', 'params': {'address': '0x20000001', 'value': 1}},
        {'jsonrpc': '2.0', 'id': 4, 'method': 'shutdown'},
    ]
    process = subprocess.run([str(exe)], input='\n'.join(json.dumps(r) for r in requests) + '\n',
                             capture_output=True, text=True, encoding='utf-8', timeout=60, check=True)
    responses = [json.loads(line) for line in process.stdout.splitlines() if line.startswith('{')]
    assert [r['id'] for r in responses] == [1, 2, 3, 4], responses
    assert responses[0]['result'] == [255, 0x42, 255, 255], responses[0]
    assert '4096' in responses[1]['error']['message'], responses[1]
    assert 'aligned' in responses[2]['error']['message'], responses[2]
print('PASS frozen daemon: HEX address mapping, oversize read rejection, unaligned write rejection')
