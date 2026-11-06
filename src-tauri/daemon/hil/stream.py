"""Non-destructive byte journal with absolute cursors and bounded memory."""
import threading
import time
from collections import deque


class Journal:
    def __init__(self, capacity=1024 * 1024, sink=None):
        self.capacity = capacity
        self.buffer = bytearray()
        self.start = 0
        self.end = 0
        self.error = None
        self.sink = sink
        self.condition = threading.Condition()
        self.chunks = deque()

    def append(self, data, timestamp=None):
        with self.condition:
            timestamp = time.monotonic() if timestamp is None else timestamp
            if self.sink:
                self.sink(data)
            self.buffer.extend(data)
            self.chunks.append((self.end, self.end + len(data), timestamp))
            self.end += len(data)
            excess = max(0, len(self.buffer) - self.capacity)
            if excess:
                del self.buffer[:excess]
                self.start += excess
            while self.chunks and self.chunks[0][1] <= self.start:
                self.chunks.popleft()
            while len(self.chunks) > 16384:
                _, end, _ = self.chunks.popleft()
                drop = max(0, end - self.start)
                del self.buffer[:drop]
                self.start += drop
            self.condition.notify_all()

    def read(self, cursor):
        with self.condition:
            if self.error:
                raise IOError(self.error)
            if cursor < self.start:
                raise IOError(f'Serial journal overrun: lost {self.start - cursor} bytes')
            return bytes(self.buffer[cursor - self.start:]), self.end

    def fail(self, error):
        with self.condition:
            self.error = str(error)
            self.condition.notify_all()

    def read_timed(self, cursor):
        with self.condition:
            self.read(cursor)  # validates overrun/disconnect under the same reentrant condition
            return [(bytes(self.buffer[max(cursor, start) - self.start:end - self.start]), stamp)
                    for start, end, stamp in self.chunks if end > cursor], self.end

    def mark(self):
        with self.condition:
            return self.end


def parse_hil(line):
    if not line.startswith('HILv1 '):
        return None
    parts = line.split()
    if len(parts) < 2:
        raise AssertionError('Malformed HILv1 event')
    fields = {}
    for part in parts[2:]:
        if '=' not in part:
            raise AssertionError(f'Malformed HILv1 field: {part}')
        k, v = part.split('=', 1)
        if k in fields or not k or not v:
            raise AssertionError(f'Invalid/duplicate HILv1 field: {part}')
        fields[k] = v
    return parts[1], fields


class HilObserver:
    """Incremental protocol monitor: noise never refreshes the HB deadline."""
    def __init__(self, params, now=None):
        self.params = params
        self.started = time.monotonic() if now is None else now
        self.last_hb = self.started
        self.pending = bytearray()
        self.boots = 0
        self.last_boot = None
        self.plan = None
        self.results = {}
        self.failures = []
        self.done = None

    @staticmethod
    def number(fields, name):
        v = fields.get(name, '')
        if not v.isdecimal():
            raise AssertionError(f'HILv1 {name} must be a nonnegative decimal integer')
        return int(v)

    def feed(self, data, now=None):
        now = time.monotonic() if now is None else now
        self.pending.extend(data)
        events = []
        while b'\n' in self.pending:
            raw, _, remaining = self.pending.partition(b'\n')
            self.pending = bytearray(remaining)
            if len(raw) > 65536:
                raise AssertionError('Serial line exceeds 64 KiB')
            line = raw.rstrip(b'\r').decode('ascii', errors='replace')
            event = parse_hil(line)
            if event is None:
                continue
            kind, f = event
            events.append({'event': kind, 'fields': f, 'line': line})
            if self.done is not None:
                raise AssertionError('HILv1 event after DONE in the same observation window')
            if kind == 'BOOT':
                self.boots += 1
                n = self.number(f, 'boot')
                if self.last_boot is not None and n != self.last_boot + 1:
                    raise AssertionError('BOOT counter did not increment by one')
                self.last_boot = n
                if self.boots > self.params.get('boot_count', 1):
                    raise AssertionError('Unexpected device reset (extra BOOT)')
                self.last_hb = now
            elif not self.boots:
                raise AssertionError(f'{kind} arrived before BOOT')
            elif kind == 'PLAN':
                total = self.number(f, 'total')
                if total < 1 or (self.plan is not None and total != self.plan):
                    raise AssertionError('Invalid/inconsistent PLAN total')
                self.plan = total
            elif kind == 'HB':
                self.last_hb = now
            elif kind == 'RESULT':
                cfg = f.get('id')
                if not cfg or cfg in self.results or f.get('status') not in ('PASS', 'FAIL'):
                    raise AssertionError('Invalid/duplicate RESULT')
                self.results[cfg] = f['status']
                if f['status'] == 'FAIL':
                    self.failures.append(line)
            elif kind == 'CRASH':
                self.failures.append(line)
            elif kind == 'DONE':
                total, passed, failed, fault = (self.number(f, k) for k in ('total', 'pass', 'fail', 'fault'))
                if total < 1 or total != passed + failed + fault:
                    raise AssertionError('DONE counts are inconsistent or empty')
                if self.plan is not None and self.plan != total:
                    raise AssertionError('DONE total differs from PLAN')
                if self.results and (sum(v == 'PASS' for v in self.results.values()) != passed or sum(v == 'FAIL' for v in self.results.values()) != failed):
                    raise AssertionError('RESULT counts differ from DONE')
                if self.boots != self.params.get('boot_count', 1):
                    raise AssertionError('BOOT count differs from expected')
                self.done = f
                if failed or fault:
                    self.failures.append(line)
        if len(self.pending) > 65536:
            raise AssertionError('Serial line exceeds 64 KiB')
        if self.failures and not self.params.get('continue_on_failure', True):
            raise AssertionError(self.failures[0])
        return events

    def check_time(self, now=None):
        now = time.monotonic() if now is None else now
        if not self.boots and (now - self.started) * 1000 >= self.params.get('boot_timeout_ms', 10000):
            raise TimeoutError('BOOT timeout')
        if self.boots and (now - self.last_hb) * 1000 >= self.params.get('idle_timeout_ms', 15000):
            raise TimeoutError('HB timeout: ordinary serial output does not count as heartbeat')
