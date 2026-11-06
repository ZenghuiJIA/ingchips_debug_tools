"""Validate ZIP integrity and every packaged file against its SHA-256 manifest."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

archive = Path(sys.argv[1]).resolve()
root = Path(__file__).resolve().parents[1]
with zipfile.ZipFile(archive) as package:
    assert package.testzip() is None, 'ZIP CRC validation failed'
    manifests = [name for name in package.namelist() if name.endswith('/SHA256SUMS.json')]
    assert len(manifests) == 1, manifests
    prefix = manifests[0].rsplit('/', 1)[0] + '/'
    manifest = json.loads(package.read(manifests[0]))
    for name, expected in manifest.items():
        normalized = name.replace('\\', '/')
        actual = hashlib.sha256(package.read(prefix + normalized)).hexdigest()
        assert actual == expected, name
    for packaged, built in [
        ('AI-HIL-Debugger.exe', root / 'src-tauri/target/release/ai-hil-debugger.exe'),
        ('bin/hil-daemon-x86_64-pc-windows-msvc.exe', root / 'build_dist/hil-native.exe'),
        ('bin/hil-native.exe', root / 'build_dist/hil-native.exe'),
        ('bin/hil-protocol.exe', root / 'src-tauri/target/release/hil-protocol.exe'),
        ('bin/hil-python-worker.exe', root / 'build_dist/hil-python-worker.exe'),
    ]:
        assert package.read(prefix + packaged) == built.read_bytes(), f'Stale binary: {packaged}'
    version = json.loads((root / 'package.json').read_text(encoding='utf-8'))['version']
    assert 'v' + version in package.read(prefix + 'RELEASE_NOTES.md').decode('utf-8')
    assert prefix + 'examples/hil/flash_stress.hiltest.yaml' in package.namelist()
print(f'PASS {archive.name}: ZIP CRC, {len(manifest)} file hashes, current desktop/daemon binaries and release notes')
