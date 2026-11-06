"""Bounded client for the same native codec linked into the desktop."""
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path


def codec_path():
    name = 'hil-protocol.exe' if os.name == 'nt' else 'hil-protocol'
    if getattr(sys, 'frozen', False):
        candidates = [Path(sys.executable).parent / name, Path(sys.executable).parent / 'bin' / name]
    else:
        root = Path(__file__).resolve().parents[2]
        candidates = [root / 'target' / 'debug' / name, root / 'target' / 'release' / name]
    return next((p for p in candidates if p.is_file()), None)


class Codec:
    def __init__(self, protocol):
        executable = codec_path()
        if executable is None:
            raise RuntimeError('hil-protocol executable is missing; install the complete release')
        self.process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.responses = queue.Queue(maxsize=4)
        self.sequence = 0
        def read():
            while True:
                line = self.process.stdout.readline(4 * 1024 * 1024 + 1)
                if not line:
                    self.responses.put(None); break
                self.responses.put(line)
        threading.Thread(target=read, daemon=True).start()
        self.protocol = protocol
        try:
            self.call('configure', protocol=protocol)
        except BaseException:
            self.close(); raise

    def call(self, operation, **arguments):
        self.sequence += 1
        request = {'id': self.sequence, 'operation': operation, **arguments}
        data = (json.dumps(request, ensure_ascii=False) + '\n').encode('utf-8')
        if len(data) > 4 * 1024 * 1024:
            raise ValueError('Codec request too large')
        written = queue.Queue(maxsize=1)
        def write():
            try:
                self.process.stdin.write(data); self.process.stdin.flush(); written.put(None)
            except Exception as exc:
                written.put(exc)
        threading.Thread(target=write, daemon=True).start()
        try:
            error = written.get(timeout=3)
            if error: raise error
            raw = self.responses.get(timeout=3)
            if raw is None or len(raw) > 4 * 1024 * 1024: raise RuntimeError('Codec disconnected/oversize response')
            response = json.loads(raw)
            if response.get('id') != self.sequence: raise RuntimeError('Codec response ID mismatch')
            if 'error' in response: raise ValueError(response['error'])
            return response['result']
        except queue.Empty:
            self.process.kill()
            raise TimeoutError('Native codec deadline exceeded')

    def encode(self, values):
        return bytes.fromhex(self.call('encode', protocol=self.protocol, values=values)['data'])

    def feed(self, data, elapsed_ms):
        return self.call('feed', data=data.hex(), elapsed_ms=elapsed_ms)['frames']

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        self.process.stdin.close(); self.process.stdout.close()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
