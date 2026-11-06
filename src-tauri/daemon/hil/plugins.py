"""Trusted local Python decoders in deadline-bounded child processes, not a security sandbox."""
import contextlib
import hashlib
import json
import math
import os
import queue
import runpy
import subprocess
import sys
import threading
from pathlib import Path
from .runner import terminate_worker

LIMIT = 1024 * 1024


def validate_result(result):
    if not isinstance(result, dict) or set(result) - {'samples', 'annotations'}:
        raise ValueError('Plugin must return samples/annotations object')
    samples = result.get('samples', [])
    notes = result.get('annotations', [])
    if not isinstance(samples, list) or len(samples) > 10000 or not isinstance(notes, list) or len(notes) > 1000:
        raise ValueError('Plugin result limit exceeded')
    for sample in samples:
        if not isinstance(sample, dict) or not isinstance(sample.get('channel'), str) or len(sample['channel']) > 128:
            raise ValueError('Invalid plugin sample channel')
        for key in ('t', 'value'):
            if isinstance(sample.get(key), bool) or not isinstance(sample.get(key), (int, float)) or not math.isfinite(sample[key]):
                raise ValueError('Plugin samples require finite t and value')
        if sample['t'] < 0: raise ValueError('Plugin time must be nonnegative')
    for note in notes:
        if not isinstance(note, dict) or not isinstance(note.get('message'), str) or len(note['message']) > 4096:
            raise ValueError('Invalid plugin annotation')
    return {'samples': samples, 'annotations': notes}


def analyze(plugin_path, payload, timeout_ms=2000):
    path = Path(plugin_path).resolve()
    if path.suffix.lower() != '.py' or not path.is_file() or path.stat().st_size > LIMIT:
        raise ValueError('Plugin must be a local Python file <= 1 MiB')
    if not isinstance(timeout_ms, int) or not 100 <= timeout_ms <= 10000:
        raise ValueError('Plugin timeout must be 100..10000 ms')
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(data) > LIMIT: raise ValueError('Plugin input exceeds 1 MiB')
    command = [sys.executable]
    if not getattr(sys, 'frozen', False): command.append(str(Path(__file__).resolve().parents[1] / 'daemon_entry.py'))
    command.extend(['--protocol-plugin-worker', str(path)])
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'}, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    result = queue.Queue(maxsize=1)
    def io():
        try:
            process.stdin.write(data); process.stdin.close()
            result.put(process.stdout.read(LIMIT + 1))
        except Exception as exc: result.put(exc)
    threading.Thread(target=io, daemon=True).start()
    try:
        raw = result.get(timeout=timeout_ms / 1000)
        if isinstance(raw, Exception): raise raw
        if len(raw) > LIMIT: raise ValueError('Plugin output exceeds 1 MiB')
        process.wait(timeout=1)
        decoded = json.loads(raw)
        if 'error' in decoded: raise RuntimeError(decoded['error'])
        if process.returncode: raise RuntimeError(f'Plugin exited with {process.returncode}')
        output = validate_result(decoded)
        return {**output, 'mode': 'PLUGIN_ANALYSIS_ONLY', 'hardware_verified': False, 'plugin_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    except queue.Empty:
        raise TimeoutError('Plugin deadline exceeded')
    finally:
        if process.poll() is None: terminate_worker(process)
        process.stdout.close()


def worker(path):
    try:
        raw = sys.stdin.buffer.read(LIMIT + 1)
        if len(raw) > LIMIT: raise ValueError('Input limit exceeded')
        with contextlib.redirect_stdout(sys.stderr):
            module = runpy.run_path(path)
            function = module.get('decode')
            if not callable(function): raise ValueError('Plugin must define decode(payload)')
            result = validate_result(function(json.loads(raw)))
        sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False)); sys.stdout.flush()
    except BaseException as exc:
        sys.stdout.write(json.dumps({'error': str(exc)[:4096]}, ensure_ascii=False)); sys.stdout.flush()
        return 2
    return 0
