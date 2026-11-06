"""Cross-process, non-blocking ownership for physical debug probes."""
import hashlib
import os
import tempfile
import threading
from pathlib import Path


class ProbeLease:
    _guard = threading.RLock()
    _held = {}

    def __init__(self, unique_id, allow_nested=False):
        self.key = str(unique_id)
        self.owner = threading.get_ident()
        self.closed = False
        with self._guard:
            existing = self._held.get(self.key)
            if existing:
                if existing['owner'] != self.owner or not existing['allow_nested']:
                    raise RuntimeError(f'Resource {unique_id} is occupied by another HIL operation')
                existing['count'] += 1
                self.file = existing['file']
                return
            self._acquire(unique_id)
            self._held[self.key] = {'owner': self.owner, 'count': 1, 'file': self.file, 'allow_nested': allow_nested}

    def _acquire(self, unique_id):
        digest = hashlib.sha256(str(unique_id).encode()).hexdigest()
        folder = Path(tempfile.gettempdir()) / 'ai-hil-probe-leases'
        folder.mkdir(exist_ok=True)
        self.file = open(folder / (digest + '.lock'), 'a+b')
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.file.close()
            self.file = None
            raise RuntimeError(f'Probe {unique_id} is occupied by another HIL operation/process') from error

    def close(self):
        with self._guard:
            if self.closed:
                return
            self.closed = True
            entry = self._held.get(self.key)
            if entry:
                entry['count'] -= 1
                if not entry['count']:
                    entry['file'].close()
                    del self._held[self.key]
            self.file = None


class LeasedSession:
    def __init__(self, session, unique_id):
        self.session = session
        self.unique_id = unique_id
        self.lease = None

    def __getattr__(self, name):
        return getattr(self.session, name)

    def open(self):
        if self.lease:
            return
        self.lease = ProbeLease(self.unique_id)
        try:
            self.session.open()
        except BaseException:
            self.close()
            raise

    def close(self):
        try:
            self.session.close()
        finally:
            if self.lease:
                self.lease.close()
                self.lease = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.close()
